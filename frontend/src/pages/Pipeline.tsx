import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { rebuildPipeline, runPipeline } from '../api'
import { Pepite, PepiteSays, type Pose } from '../components/Pepite'
import { Alert, Arrow, Badge, Button, Card, Separator } from '../components/ui'
import { PORTFOLIO_IDS, PORTFOLIO_META, riskLabel, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { AgentId, AgentStatus, PipelineEvent, PortfolioId } from '../types'

interface Agent {
  id: AgentId
  name: string
  pose: Pose
}

// Ce que construit chaque gestionnaire (mêmes noms que VARIANT_NAMES et BASE_NAMES dans monport.py).
const VARIANTS: Record<PortfolioId, string> = { prudent: 'Variante prudente', equilibre: 'Variante fidèle', conviction: 'Variante audacieuse' }
const BASES: Record<PortfolioId, string> = { prudent: 'Ton profil', equilibre: 'Tes contraintes', conviction: 'Tes préférences' }

/** Les agents, regroupés pour l'affichage (l'ordre réel du pipeline ne change pas). Profil cohérent : concurrence et juge final. Incohérent : trois bases, puis les mélanges 80/20. */
function stepsFor(coherent: boolean): { title: string; role: string; agents: Agent[] }[] {
  const names = coherent ? VARIANTS : BASES
  return [
    {
      title: 'Pépite',
      role: 'Seule à te parler : elle calcule ton profil, écrit les consignes des gestionnaires et coordonne toute l’équipe.',
      agents: [{ id: 'pepite', name: 'Pépite', pose: 'map' }],
    },
    {
      title: coherent ? 'Trois gestionnaires en concurrence' : 'Trois gestionnaires, en parallèle',
      role: coherent
        ? 'Un suit exactement tes consignes, les deux autres une variante proposée par Pépite. L’optimiseur calcule les poids.'
        : 'Un portefeuille de base chacun : ton profil, tes contraintes, tes préférences. L’optimiseur calcule les poids.',
      agents: PORTFOLIO_IDS.map((id) => ({ id: `gestionnaire-${id}`, name: names[id], pose: 'laptop' })),
    },
    {
      title: 'Vérification des limites',
      role: 'Pour chaque portefeuille, le juge vérifie que tes limites sont respectées.',
      agents: PORTFOLIO_IDS.map((id) => ({ id: `juge-${id}` as const, name: `Limites · ${names[id]}`, pose: 'thinking' as const })),
    },
    {
      title: 'Juge',
      role: coherent
        ? 'Lit les rapports de risque, demande une réoptimisation au besoin et garde le meilleur portefeuille.'
        : 'Lit les rapports de risque et demande une réoptimisation au besoin.',
      agents: [{ id: 'juge-final', name: 'Juge', pose: 'cool' }],
    },
    {
      title: 'Agents Risque',
      role: 'Chaque gestionnaire a son agent Risque : il relit le portefeuille et envoie son rapport au juge.',
      agents: [{ id: 'risques', name: 'Agents Risque', pose: 'flag' }],
    },
  ]
}

const STATUS_LABEL: Record<AgentStatus, string> = { pending: 'À venir', running: 'En cours…', done: 'Terminé' }

type AgentState = { status: AgentStatus; message: string }

function AgentCard({ agent, st, children }: { agent: Agent; st: AgentState; children?: React.ReactNode }) {
  return (
    <Card className={`flex h-full flex-wrap items-center gap-4 transition-colors ${st.status === 'running' ? 'border-navy' : ''} ${st.status === 'pending' ? 'opacity-60' : ''}`}>
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-sky">
        <Pepite pose={agent.pose} size={48} />
      </span>
      <div className="flex min-w-[140px] flex-1 flex-col gap-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-lg font-semibold text-navy">{agent.name}</span>
          <Badge tone={st.status === 'done' ? 'sky' : st.status === 'running' ? 'red' : 'mist'}>{STATUS_LABEL[st.status]}</Badge>
        </span>
        {st.message && <span className="fade-in text-[15px] text-ink">{st.message}</span>}
      </div>
      {children}
    </Card>
  )
}

export default function Pipeline() {
  const navigate = useNavigate()
  const state = useApp()
  const score = riskScore(state.profile)
  const coherent = state.check?.coherent ?? false
  const steps = stepsFor(coherent)
  const [agents, setAgents] = useState<Record<AgentId, AgentState>>(
    () => Object.fromEntries(steps.flatMap((s) => s.agents).map((a) => [a.id, { status: 'pending', message: '' }])) as Record<AgentId, AgentState>,
  )
  // Relance demandée depuis le chat : lu une seule fois, le mode strict remonte la page sans réinitialiser l'état.
  const [rebuild] = useState(() => state.rebuild && Boolean(state.session))
  const [log, setLog] = useState<PipelineEvent[]>([])
  const [pepite, setPepite] = useState(rebuild ? 'Je relance mes agents avec tes changements…' : 'Je rassemble mes agents…')
  const [done, setDone] = useState(false)
  const [rerun, setRerun] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!state.check) return
    const ctrl = new AbortController()
    let received = false
    let failed = false
    let said = ''
    if (!rebuild) state.setChat(() => [])
    const onEvent = (e: PipelineEvent) => {
      setLog((l) => [...l, e])
      if (e.type === 'agent_status') setAgents((a) => ({ ...a, [e.agent]: { status: e.status, message: e.message } }))
      if (e.type === 'pepite') {
        setPepite(e.text)
        said = e.text
      }
      if (e.type === 'rerun') {
        const name = (coherent ? VARIANTS : BASES)[e.portfolio] ?? PORTFOLIO_META[e.portfolio].name
        setRerun(true)
        setPepite(`Oh! Le juge renvoie le portefeuille « ${name} » à son gestionnaire.`)
        setAgents((a) => ({
          ...a,
          [`juge-${e.portfolio}`]: { status: 'running', message: e.reason },
          [`gestionnaire-${e.portfolio}`]: { status: 'running', message: 'Nouveau calcul demandé par le juge…' },
        }))
      }
      if (e.type === 'portfolios') {
        state.setPortfolios(e.portfolios)
        if (e.session) state.setSession(e.session)
        received = true
      }
      if (e.type === 'error') {
        setError(e.message)
        failed = true
      }
      if (e.type === 'done') {
        if (rebuild) {
          // Une relance ratée garde les portefeuilles d'avant ; réussie, le chat le note et on y retourne.
          state.setRebuild(false)
          if (received) {
            state.setChat((m) => [...m, { from: 'info', text: 'Portefeuilles reconstruits' }, ...(said ? [{ from: 'pepite' as const, text: said }] : [])])
            setTimeout(() => !ctrl.signal.aborted && navigate('/portefeuille'), 1500)
          } else setPepite('Mes agents ont eu un pépin. Tes portefeuilles d’avant n’ont pas changé.')
        } else {
          // Sans portefeuilles reçus (script d'exemple ou échec du backend), le moteur d'exemple prend le relais.
          if (!received) state.build()
          if (failed) setPepite('Mes agents ont eu un pépin. Je te montre des portefeuilles d’exemple pour l’instant.')
        }
        setDone(true)
      }
    }
    const input = { score, profile: state.profile, constraints: state.constraints, contribution: state.contribution, check: state.check, adjustment: state.adjustment, session: state.session }
    const run = rebuild
      ? rebuildPipeline(state.session!, onEvent, ctrl.signal).then((ok) => {
          if (ok) return
          onEvent({ type: 'error', message: 'Mes agents ne sont pas joignables pour l’instant.' })
          onEvent({ type: 'done' })
        })
      : runPipeline(input, onEvent, ctrl.signal)
    run.catch(() => {})
    return () => ctrl.abort()
    // Le pipeline ne se lance qu'une fois par visite.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const universe = log.find((e): e is Extract<PipelineEvent, { type: 'universe' }> => e.type === 'universe')
  const warnings = log.filter((e): e is Extract<PipelineEvent, { type: 'warning' }> => e.type === 'warning')
  const judging = PORTFOLIO_IDS.some((id) => agents[`juge-${id}`].status === 'running')
  const pose: Pose = done ? 'thumbsup' : rerun && judging ? 'surprised' : 'coffee'
  // Sans vérification de Pépite, on y retourne : c'est elle qui décide du scénario.
  if (!state.check) return <Navigate to="/verification" replace />

  return (
    <div className="mx-auto flex w-full max-w-[1020px] flex-col gap-8 px-4 py-12 sm:px-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold text-slate">{rebuild ? 'Tes changements' : 'Profil retenu'}</span>
        <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[54px]">
          {rebuild ? 'Pépite relance ses agents' : `Profil ${riskLabel(score).toLowerCase()}`}
        </h1>
        <Separator />
        <p className="m-0 max-w-[560px] text-ink-soft">
          {rebuild ? (
            'J’applique ce qu’on s’est dit dans le chat. Tu reviens à ton tableau de bord dès que tes nouveaux portefeuilles sont prêts.'
          ) : (
            <>
              Selon tes réponses : {state.profile.age} ans, horizon de {state.profile.horizon} ans.{' '}
              {coherent ? 'Trois gestionnaires se font concurrence ; le juge gardera le meilleur portefeuille.' : 'Les agents préparent maintenant trois propositions.'}
            </>
          )}
        </p>
      </div>

      <PepiteSays pose={pose}>
        <span aria-live="polite">{pepite}</span>
      </PepiteSays>

      <ol className="m-0 flex list-none flex-col gap-6 p-0">
        {steps.map((step, i) => (
          <li key={step.title} className="flex flex-col gap-3">
            <div className="flex flex-col">
              <span className="text-sm font-semibold text-slate">
                Étape {i + 1} · {step.title}
              </span>
              <span className="text-sm text-ink-soft">{step.role}</span>
            </div>
            <ul className={`m-0 grid list-none gap-3 p-0 ${step.agents.length > 1 ? 'md:grid-cols-3' : ''}`}>
              {step.agents.map((a) => (
                <li key={a.id}>
                  <AgentCard agent={a} st={agents[a.id]}>
                    {a.id === 'pepite' && universe && (
                      <div className="fade-in text-right">
                        <div className="text-3xl font-light text-navy">
                          {universe.after}
                          <span className="text-base text-ink-soft"> / {universe.before}</span>
                        </div>
                        <div className="text-xs text-ink-soft">placements éligibles</div>
                      </div>
                    )}
                  </AgentCard>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      {error && <Alert title="Petit pépin">{error}</Alert>}

      {warnings.length > 0 && (
        <div className="flex flex-col gap-2">
          {warnings.map((w) => (
            <Alert key={w.text} title="Le responsable des risques signale">
              {w.text}
            </Alert>
          ))}
        </div>
      )}

      <div className="flex justify-end">
        <Button disabled={!done} onClick={() => navigate('/portefeuille')}>
          {rebuild ? (coherent ? 'Retour à mon portefeuille' : 'Retour à mes portefeuilles') : coherent ? 'Voir mon portefeuille' : 'Voir mes 3 portefeuilles'} <Arrow />
        </Button>
      </div>
    </div>
  )
}
