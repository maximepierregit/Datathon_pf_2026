import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { runPipeline } from '../api'
import { Pepite, PepiteSays, type Pose } from '../components/Pepite'
import { Alert, Arrow, Badge, Button, Card, Separator } from '../components/ui'
import { PORTFOLIO_IDS, PORTFOLIO_META, riskLabel, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { AgentId, AgentStatus, PipelineEvent } from '../types'

interface Agent {
  id: AgentId
  name: string
  pose: Pose
}

/** Les agents du backend, dans l'ordre du pipeline. Gestionnaires et juges travaillent en parallèle. */
const STEPS: { title: string; role: string; agents: Agent[] }[] = [
  {
    title: 'Profil',
    role: 'Analyse tes réponses et filtre l’univers de placements.',
    agents: [{ id: 'profil', name: 'Profil', pose: 'binoculars' }],
  },
  {
    title: 'Trois gestionnaires, en parallèle',
    role: 'Chacun choisit les placements d’un portefeuille. L’optimiseur calcule les poids.',
    agents: PORTFOLIO_IDS.map((id) => ({ id: `gestionnaire-${id}`, name: `Gestionnaire ${PORTFOLIO_META[id].name}`, pose: 'laptop' })),
  },
  {
    title: 'Trois juges',
    role: 'Chacun vérifie qu’un portefeuille respecte tes limites et peut le renvoyer à son gestionnaire.',
    agents: PORTFOLIO_IDS.map((id) => ({ id: `juge-${id}`, name: `Juge ${PORTFOLIO_META[id].name}`, pose: 'thinking' })),
  },
  {
    title: 'Responsable des risques',
    role: 'Cherche les incohérences avec ton profil et prépare les mises en garde.',
    agents: [{ id: 'risques', name: 'Responsable des risques', pose: 'flag' }],
  },
]

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
  const [agents, setAgents] = useState<Record<AgentId, AgentState>>(
    () => Object.fromEntries(STEPS.flatMap((s) => s.agents).map((a) => [a.id, { status: 'pending', message: '' }])) as Record<AgentId, AgentState>,
  )
  const [log, setLog] = useState<PipelineEvent[]>([])
  const [pepite, setPepite] = useState('Je rassemble mes agents…')
  const [done, setDone] = useState(false)
  const [rerun, setRerun] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const ctrl = new AbortController()
    let received = false
    let failed = false
    runPipeline({ score, profile: state.profile, constraints: state.constraints }, (e) => {
      setLog((l) => [...l, e])
      if (e.type === 'agent_status') setAgents((a) => ({ ...a, [e.agent]: { status: e.status, message: e.message } }))
      if (e.type === 'pepite') setPepite(e.text)
      if (e.type === 'rerun') {
        const name = PORTFOLIO_META[e.portfolio].name
        setRerun(true)
        setPepite(`Oh! Le juge ${name} renvoie son portefeuille au gestionnaire.`)
        setAgents((a) => ({
          ...a,
          [`juge-${e.portfolio}`]: { status: 'running', message: `Portefeuille ${e.reason}` },
          [`gestionnaire-${e.portfolio}`]: { status: 'running', message: 'Nouveau calcul demandé par le juge…' },
        }))
      }
      if (e.type === 'portfolios') {
        state.setPortfolios(e.portfolios)
        received = true
      }
      if (e.type === 'error') {
        setError(e.message)
        failed = true
      }
      if (e.type === 'done') {
        // Sans portefeuilles reçus (script d'exemple ou échec du backend), le moteur d'exemple prend le relais.
        if (!received) state.build()
        if (failed) setPepite('Mes agents ont eu un pépin. Je te montre des portefeuilles d’exemple pour l’instant.')
        setDone(true)
      }
    }, ctrl.signal).catch(() => {})
    return () => ctrl.abort()
    // Le pipeline ne se lance qu'une fois par visite.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const universe = log.find((e): e is Extract<PipelineEvent, { type: 'universe' }> => e.type === 'universe')
  const warnings = log.filter((e): e is Extract<PipelineEvent, { type: 'warning' }> => e.type === 'warning')
  const judging = PORTFOLIO_IDS.some((id) => agents[`juge-${id}`].status === 'running')
  const pose: Pose = done ? 'thumbsup' : rerun && judging ? 'surprised' : 'coffee'

  return (
    <div className="mx-auto flex w-full max-w-[1020px] flex-col gap-8 px-4 py-12 sm:px-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold text-slate">Profil retenu</span>
        <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[54px]">Profil {riskLabel(score)}</h1>
        <Separator />
        <p className="m-0 max-w-[560px] text-ink-soft">
          Selon tes réponses : {state.profile.age} ans, horizon de {state.profile.horizon} ans. Les agents construisent maintenant trois propositions.
        </p>
      </div>

      <PepiteSays pose={pose}>
        <span aria-live="polite">{pepite}</span>
      </PepiteSays>

      <ol className="m-0 flex list-none flex-col gap-6 p-0">
        {STEPS.map((step, i) => (
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
                    {a.id === 'profil' && universe && (
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
          Voir mes 3 portefeuilles <Arrow />
        </Button>
      </div>
    </div>
  )
}
