import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { askPepite, proposeAdjustment } from '../../api'
import { Pepite, type Pose } from '../../components/Pepite'
import { RichText } from '../../components/RichText'
import { Alert, Button } from '../../components/ui'
import { riskScore } from '../../lib/engine'
import { pct, points } from '../../lib/format'
import { useApp } from '../../store'
import type { AgentId, ChatMsg as Msg, ChatStep as Step, Portfolio } from '../../types'

const SUGGESTIONS = ['Plus de tech', 'Pas de pétrole', 'Plus de crypto', 'Moins de risque']
const LIVE_SUGGESTIONS = ['Pourquoi ce portefeuille?', 'C’est quoi un FNB?', 'Pas de pétrole', 'Moins de risque']

const AGENTS: Record<string, { name: string; pose: Pose }> = {
  pepite: { name: 'Pépite', pose: 'thinking' },
  gestionnaire: { name: 'Gestionnaire', pose: 'laptop' },
  juge: { name: 'Juge', pose: 'cool' },
  'juge-final': { name: 'Juge final', pose: 'cool' },
  risques: { name: 'Responsable des risques', pose: 'flag' },
}
const agentOf = (id: AgentId) => AGENTS[id] ?? AGENTS[id.split('-')[0]] ?? AGENTS.pepite

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Ajoute une étape ; un « Terminé » clôt les étapes en cours du même agent. */
function track(steps: Step[], agent: AgentId, text: string, done: boolean): Step[] {
  const next = steps.map((s) => (done && s.agent === agent ? { ...s, done: true } : s))
  const last = next[next.length - 1]
  if (last?.agent === agent && last.text === text) return next
  return done && next.some((s) => s.agent === agent && s.text === text) ? next : [...next, { agent, text, done }]
}

/**
 * Chat avec Pépite, toujours visible à droite sur grand écran (tiroir sur mobile). Avec le backend (session
 * ouverte), elle répond elle-même : elle interroge au besoin ses gestionnaires, ses agents Risque et le juge. Pour un
 * changement, elle pose des questions jusqu'à ce qu'il soit clair, le récapitule et demande si on y va : la page de
 * construction relance alors les agents. Sans backend, le moteur d'exemple propose des ajustements simulés.
 */
export function AdjustPanel({ p, open, onClose }: { p: Portfolio; open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const state = useApp()
  const live = Boolean(state.session)
  const msgs = state.chat
  const setMsgs = state.setChat
  const [steps, setSteps] = useState<Step[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const list = useRef<HTMLDivElement>(null)
  const ctrl = useRef<AbortController | null>(null)
  const trace = useRef<Step[]>([])
  const mine = state.adjustments.filter((a) => a.portfolio === p.id)

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [msgs, steps])
  useEffect(() => () => ctrl.current?.abort(), [])

  const step = (agent: AgentId, text: string, done = false) => {
    trace.current = track(trace.current, agent, text, done)
    setSteps(trace.current)
  }
  const reply = (m: Omit<Msg, 'from' | 'steps'>) => {
    const done = trace.current.map((s) => ({ ...s, done: true }))
    trace.current = []
    setSteps([])
    setMsgs((all) => [...all, { from: 'pepite', steps: done.length ? done : undefined, ...m }])
  }

  async function simulated(t: string) {
    // Sans backend, aucun agent n'est consulté : on ne montre que ce que fait le moteur d'exemple.
    step('pepite', 'Je cherche ta demande dans mes règles d’exemple')
    const proposal = await proposeAdjustment(p, t, riskScore(state.profile), (patch, riskShift) =>
      state.previewAdjustment({ portfolio: p.id, patch, riskShift }),
    )
    if (proposal.changes.length) step('pepite', `Je recalcule « ${p.name} » avec le moteur d’exemple`)
    reply({ text: proposal.reply, proposal, request: t, status: proposal.changes.length ? 'open' : undefined })
  }

  async function withPepite(session: string, t: string) {
    ctrl.current = new AbortController()
    let answered = false
    step('pepite', 'Je lis ton message')
    const ok = await askPepite(session, `[Portefeuille affiché : ${p.name}]\n${t}`, (e) => {
      if (e.type === 'agent_status') step(e.agent, e.message.replace(/…$/, ''), e.status === 'done')
      if (e.type === 'pepite' && e.final) {
        answered = true
        reply({ text: e.text, confirm: e.ready ? 'open' : undefined })
      }
      if (e.type === 'portfolios') {
        state.setPortfolios(e.portfolios)
        setMsgs((m) => [...m, { from: 'info', text: 'Portefeuilles mis à jour' }])
      }
      if (e.type === 'error') {
        answered = true
        reply({ text: e.message })
        if (/expiré/.test(e.message)) state.setSession(null)
      }
    }, ctrl.current.signal).catch(() => true)
    if (!ok) {
      state.setSession(null) // backend injoignable : on repasse au moteur d'exemple
      return simulated(t)
    }
    if (!answered) reply({ text: 'Je n’ai pas réussi à te répondre. Réessaie dans un instant.' })
  }

  async function send(text: string) {
    const t = text.trim()
    if (!t || busy) return
    setDraft('')
    // Un nouveau message remplace le récapitulatif en attente : Pépite en refera un si besoin.
    setMsgs((m) => [...m.map((x) => (x.confirm === 'open' ? { ...x, confirm: 'stale' as const } : x)), { from: 'user', text: t }])
    setBusy(true)
    trace.current = []
    try {
      if (state.session) await withPepite(state.session, t)
      else await simulated(t)
    } finally {
      setBusy(false)
    }
  }

  function decide(i: number, apply: boolean) {
    const msg = msgs[i]
    if (apply && msg.proposal) state.applyAdjustment({ portfolio: p.id, label: msg.request!, patch: msg.proposal.patch ?? {}, riskShift: msg.proposal.riskShift ?? 0 })
    setMsgs((m) => m.map((x, j) => (j === i ? { ...x, status: apply ? 'applied' : 'dismissed' } : x)))
  }

  function confirm(i: number, go: boolean) {
    setMsgs((m) => [
      ...m.map((x, j) => (j === i ? { ...x, confirm: go ? ('accepted' as const) : ('dismissed' as const) } : x)),
      ...(go ? [] : [{ from: 'pepite' as const, text: '<p>Pas de souci! Dis-moi ce que tu veux changer d’autre, ou pose-moi une question.</p>' }]),
    ])
    if (!go) return
    state.setRebuild(true)
    navigate('/construction')
  }

  // Profil cohérent : le portefeuille s'appelle déjà « Ton portefeuille ».
  const which = /^ton portefeuille$/i.test(p.name) ? '<strong>ton portefeuille</strong>' : `le portefeuille <strong>${esc(p.name)}</strong>`
  const greeting = live
    ? `<p>Salut! Je connais ${which} sur le bout des doigts.</p><ul><li>Pose-moi une question dessus</li><li>Demande-moi un changement : je te pose quelques questions, puis je relance mes agents</li><li>Fais-toi expliquer une notion de finance</li></ul>`
    : `<p>Que veux-tu changer dans ${which}? Je te montre l’effet avant d’appliquer quoi que ce soit.</p><attention>Mode exemple : mes agents ne sont pas joignables. Je réponds avec quelques règles simples (plus de tech, pas de pétrole, plus de crypto, moins de risque).</attention>`

  return (
    <div
      className={`${open ? 'fixed inset-0 z-40 flex justify-end bg-navy/30' : 'hidden'} lg:sticky lg:top-16 lg:z-auto lg:flex lg:h-[calc(100dvh-4rem)] lg:self-start lg:bg-transparent`}
      onClick={onClose}
    >
      <aside
        aria-label={live ? 'Discuter avec Pépite' : 'Ajuster avec Pépite'}
        className="fade-in flex h-full w-full max-w-[440px] flex-col border-line-soft bg-white lg:max-w-none lg:border-l"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line-soft px-5 py-3">
          <span className="relative shrink-0">
            <Pepite pose={busy ? 'thinking' : 'happy'} size={44} />
            <span className={`absolute bottom-0.5 right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-white ${busy ? 'bg-taupe' : live ? 'bg-[#2E9E5B]' : 'bg-line'}`} aria-hidden />
          </span>
          <div className="flex-1">
            <div className="font-semibold text-navy">Pépite</div>
            <div className="text-xs text-ink-soft" aria-live="polite">
              {busy ? 'Travaille sur ta demande…' : live ? `Portefeuille ${p.name} · agents branchés` : `Portefeuille ${p.name} · mode exemple`}
            </div>
          </div>
          <button aria-label="Fermer" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-full text-slate hover:bg-mist lg:hidden">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div ref={list} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4" aria-live="polite">
          <Bubble>
            <RichText text={greeting} />
          </Bubble>
          {msgs.map((m, i) =>
            m.from === 'user' ? (
              <div key={i} className="fade-in max-w-[85%] self-end rounded-[var(--radius-card)] rounded-br-sm bg-navy px-4 py-2.5 text-[15px] text-white">
                {m.text}
              </div>
            ) : m.from === 'info' ? (
              <div key={i} className="fade-in flex items-center gap-2 self-center rounded-full bg-mist px-3 py-1 text-xs font-semibold text-slate">
                <Check /> {m.text}
              </div>
            ) : (
              <div key={i} className="fade-in flex flex-col gap-2">
                {m.steps && <Trace steps={m.steps} />}
                <Bubble>
                  <RichText text={m.text} />
                </Bubble>
                {m.proposal && m.proposal.changes.length > 0 && <Proposal m={m} onDecide={(apply) => decide(i, apply)} />}
                {m.confirm && m.confirm !== 'stale' && <Confirm status={m.confirm} disabled={busy} onDecide={(go) => confirm(i, go)} />}
              </div>
            ),
          )}
          {busy && <Live steps={steps} />}
        </div>

        {mine.length > 0 && (
          <div className="border-t border-line-soft px-5 py-3">
            <div className="mb-1 text-xs font-semibold text-slate">Ajustements appliqués</div>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {mine.map((a) => (
                <li key={a.id} className="flex items-center justify-between text-sm">
                  {a.label}
                  <button onClick={() => state.undoAdjustment(a.id)} className="min-h-8 px-2 text-sm font-medium text-blue hover:text-blue-dark">
                    Annuler
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="border-t border-line-soft px-4 py-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {(live ? LIVE_SUGGESTIONS : SUGGESTIONS).map((s) => (
              <button key={s} disabled={busy} onClick={() => send(s)} className="min-h-8 rounded-full bg-mist px-3 text-sm font-medium text-navy hover:bg-sky disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              send(draft)
            }}
          >
            <label htmlFor="adjust-input" className="sr-only">
              Ta demande
            </label>
            <input id="adjust-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={live ? 'Ex. : pourquoi autant d’obligations?' : 'Ex. : plus de tech, pas de pétrole…'} className="min-h-11 min-w-0 flex-1 rounded-[var(--radius-card)] border border-line px-3 text-[15px] outline-none focus:border-navy" />
            <Button type="submit" className="min-w-0 px-5" disabled={!draft.trim() || busy}>
              Envoyer
            </Button>
          </form>
        </div>
      </aside>
    </div>
  )
}

function Bubble({ children }: { children: React.ReactNode }) {
  return <div className="max-w-[92%] self-start rounded-[var(--radius-card)] rounded-bl-sm bg-sky px-4 py-3 text-navy">{children}</div>
}

function Check() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12l5 5L20 7" />
    </svg>
  )
}

function StepRow({ s, current }: { s: Step; current: boolean }) {
  const a = agentOf(s.agent)
  return (
    <li className="flex items-start gap-2.5">
      <Pepite pose={a.pose} size={26} className="mt-[-2px] shrink-0" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-xs font-semibold text-slate">{a.name}</span>
        <span className={`text-[13px] leading-[18px] ${current ? 'text-navy' : 'text-ink-soft'}`}>{s.text}</span>
      </span>
      <span className="mt-1 flex h-4 w-4 shrink-0 items-center justify-center">
        {s.done || !current ? (
          <span className="text-[#2E9E5B]">
            <Check />
          </span>
        ) : (
          <span className="h-3.5 w-3.5 rounded-full border-2 border-line border-t-navy motion-safe:animate-spin" aria-hidden />
        )}
      </span>
    </li>
  )
}

/** Pendant que Pépite travaille : chaque étape s'ajoute, la dernière tourne. */
function Live({ steps }: { steps: Step[] }) {
  return (
    <div className="fade-in flex flex-col gap-2.5 rounded-[var(--radius-card)] border border-line-soft px-3.5 py-3">
      <span className="text-xs font-semibold text-slate">Pépite travaille</span>
      <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
        {steps.length ? (
          steps.map((s, i) => <StepRow key={i} s={s} current={i === steps.length - 1} />)
        ) : (
          <StepRow s={{ agent: 'pepite', text: 'Je réfléchis', done: false }} current />
        )}
      </ol>
    </div>
  )
}

/** Après la réponse : le fil des étapes, replié. */
function Trace({ steps }: { steps: Step[] }) {
  const agents = new Set(steps.map((s) => agentOf(s.agent).name)).size
  return (
    <details className="group self-start text-xs text-slate">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-semibold hover:text-navy [&::-webkit-details-marker]:hidden">
        <span className="text-[#2E9E5B]">
          <Check />
        </span>
        {steps.length} étape{steps.length > 1 ? 's' : ''}
        {agents > 1 ? ` · ${agents} agents consultés` : ''}
        <svg className="transition-transform group-open:rotate-180" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </summary>
      <ol className="m-0 mt-2.5 flex list-none flex-col gap-2.5 rounded-[var(--radius-card)] border border-line-soft p-3">
        {steps.map((s, i) => (
          <StepRow key={i} s={s} current={false} />
        ))}
      </ol>
    </details>
  )
}

/** Pépite a récapitulé un changement : on relance ses agents, ou on continue à en parler. */
function Confirm({ status, disabled, onDecide }: { status: Msg['confirm']; disabled: boolean; onDecide: (go: boolean) => void }) {
  if (status !== 'open')
    return (
      <p className="m-0 flex items-center gap-1.5 text-xs font-semibold text-slate">
        {status === 'accepted' && <Check />}
        {status === 'accepted' ? 'Changements envoyés à mes agents.' : 'On continue d’en parler.'}
      </p>
    )
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-navy p-3.5">
      <span className="text-sm font-semibold text-navy">Je relance mes agents avec ces changements?</span>
      <span className="text-xs text-ink-soft">Tu verras chaque agent travailler, puis tes nouveaux portefeuilles. Ça prend environ une minute.</span>
      <div className="flex gap-2">
        <Button className="min-w-0 flex-1 px-4 py-1.5 text-sm" disabled={disabled} onClick={() => onDecide(true)}>
          Oui, on y va
        </Button>
        <Button variant="tertiary" className="min-w-0 flex-1 px-4 py-1.5 text-sm" disabled={disabled} onClick={() => onDecide(false)}>
          Pas encore
        </Button>
      </div>
    </div>
  )
}

function Proposal({ m, onDecide }: { m: Msg; onDecide: (apply: boolean) => void }) {
  const proposal = m.proposal!
  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-line-soft p-3.5">
      <span className="text-xs font-semibold text-slate">Ce qui changerait</span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {proposal.changes.map((c) => (
          <li key={c.label} className="flex items-center justify-between gap-3 text-sm">
            <span>{c.label}</span>
            <span className="flex items-center gap-2 whitespace-nowrap">
              <span className="text-ink-soft">{pct(c.before)}</span>
              <span className="text-slate" aria-label="devient">→</span>
              <strong className="text-navy">{pct(c.after)}</strong>
              <span className={`rounded-full px-1.5 text-xs font-semibold ${c.after > c.before ? 'bg-sky text-navy' : 'bg-mist text-slate'}`}>{points(c.after - c.before)}</span>
            </span>
          </li>
        ))}
      </ul>
      {proposal.warning && <Alert>{proposal.warning}</Alert>}
      {m.status === 'open' ? (
        <div className="flex gap-2">
          <Button className="min-w-0 flex-1 px-4 py-1.5 text-sm" onClick={() => onDecide(true)}>
            Appliquer
          </Button>
          <Button variant="tertiary" className="min-w-0 flex-1 px-4 py-1.5 text-sm" onClick={() => onDecide(false)}>
            Non merci
          </Button>
        </div>
      ) : (
        <p className="m-0 flex items-center gap-1.5 text-xs font-semibold text-slate">
          {m.status === 'applied' && <Check />}
          {m.status === 'applied' ? 'Appliqué. Le portefeuille a été recalculé.' : 'Proposition ignorée.'}
        </p>
      )}
    </div>
  )
}
