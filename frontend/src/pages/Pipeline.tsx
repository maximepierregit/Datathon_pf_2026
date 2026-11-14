import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { runPipeline } from '../api'
import { Pepite, PepiteSays, type Pose } from '../components/Pepite'
import { Alert, Arrow, Badge, Button, Card, Separator } from '../components/ui'
import { riskLabel, riskScore } from '../lib/engine'
import { useApp } from '../store'
import type { AgentId, AgentStatus, PipelineEvent } from '../types'

const AGENTS: { id: AgentId; name: string; role: string; pose: Pose }[] = [
  { id: 'eclaireur', name: 'L’Éclaireur', role: 'Lit ton profil et filtre l’univers de placements', pose: 'binoculars' },
  { id: 'compositeur', name: 'Le Compositeur', role: 'Traduit tes réponses en contraintes et optimise 3 portefeuilles', pose: 'laptop' },
  { id: 'verificateur', name: 'Le Vérificateur', role: 'Relit chaque portefeuille et peut en demander un nouveau calcul', pose: 'thinking' },
]

const STATUS_LABEL: Record<AgentStatus, string> = { pending: 'À venir', running: 'En cours…', done: 'Terminé' }

export default function Pipeline() {
  const navigate = useNavigate()
  const state = useApp()
  const score = riskScore(state.profile)
  const [agents, setAgents] = useState<Record<AgentId, { status: AgentStatus; message: string }>>({
    eclaireur: { status: 'pending', message: '' },
    compositeur: { status: 'pending', message: '' },
    verificateur: { status: 'pending', message: '' },
  })
  const [log, setLog] = useState<PipelineEvent[]>([])
  const [pepite, setPepite] = useState('Je rassemble mes agents…')
  const [done, setDone] = useState(false)
  const [rerun, setRerun] = useState(false)
  useEffect(() => {
    const ctrl = new AbortController()
    runPipeline({ score, constraints: state.constraints }, (e) => {
      setLog((l) => [...l, e])
      if (e.type === 'agent_status') setAgents((a) => ({ ...a, [e.agent]: { status: e.status, message: e.message } }))
      if (e.type === 'pepite') setPepite(e.text)
      if (e.type === 'rerun') {
        setRerun(true)
        setPepite('Oh! Le Vérificateur n’est pas content du portefeuille Conviction.')
        setAgents((a) => ({ ...a, verificateur: { status: 'running', message: `Conviction ${e.reason}` } }))
      }
      if (e.type === 'done') {
        state.build()
        setDone(true)
      }
    }, ctrl.signal).catch(() => {})
    return () => ctrl.abort()
    // Le pipeline ne se lance qu'une fois par visite.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const universe = log.find((e): e is Extract<PipelineEvent, { type: 'universe' }> => e.type === 'universe')
  const warnings = log.filter((e): e is Extract<PipelineEvent, { type: 'warning' }> => e.type === 'warning')
  const pose: Pose = done ? 'thumbsup' : rerun && agents.verificateur.status === 'running' ? 'surprised' : 'coffee'

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

      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {AGENTS.map((a) => {
          const st = agents[a.id]
          return (
            <li key={a.id}>
              <Card className={`flex flex-wrap items-center gap-4 transition-colors ${st.status === 'running' ? 'border-navy' : ''} ${st.status === 'pending' ? 'opacity-60' : ''}`}>
                <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-sky">
                  <Pepite pose={a.pose} size={56} />
                </span>
                <div className="flex min-w-[200px] flex-1 flex-col">
                  <span className="flex items-center gap-2">
                    <span className="text-lg font-semibold text-navy">{a.name}</span>
                    <Badge tone={st.status === 'done' ? 'sky' : st.status === 'running' ? 'red' : 'mist'}>{STATUS_LABEL[st.status]}</Badge>
                  </span>
                  <span className="text-sm text-ink-soft">{a.role}</span>
                  {st.message && <span className="fade-in mt-1 text-[15px] text-ink">{st.message}</span>}
                </div>
                {a.id === 'eclaireur' && universe && (
                  <div className="fade-in text-right">
                    <div className="text-3xl font-light text-navy">
                      {universe.after}
                      <span className="text-base text-ink-soft"> / {universe.before}</span>
                    </div>
                    <div className="text-xs text-ink-soft">placements éligibles</div>
                  </div>
                )}
              </Card>
            </li>
          )
        })}
      </ol>

      {warnings.length > 0 && (
        <div className="flex flex-col gap-2">
          {warnings.map((w) => (
            <Alert key={w.text} title="Le Vérificateur signale">
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
