import { useEffect, useRef, useState } from 'react'
import { askPepite, proposeAdjustment } from '../../api'
import { Pepite } from '../../components/Pepite'
import { Alert, Button } from '../../components/ui'
import { riskScore } from '../../lib/engine'
import { pct, points } from '../../lib/format'
import { useApp } from '../../store'
import type { AdjustProposal, Portfolio } from '../../types'

interface Msg {
  from: 'user' | 'pepite'
  text: string
  proposal?: AdjustProposal
  request?: string
  status?: 'open' | 'applied' | 'dismissed'
}

const SUGGESTIONS = ['Plus de tech', 'Pas de pétrole', 'Plus de crypto', 'Moins de risque']
const LIVE_SUGGESTIONS = ['Pourquoi ce portefeuille?', 'C’est quoi un FNB?', 'Pas de pétrole', 'Moins de risque']

/**
 * Chat avec Pépite. Avec le backend (session ouverte), elle répond elle-même : elle interroge au besoin ses
 * gestionnaires, ses agents Risque et le juge, et peut reconstruire les portefeuilles. Sans backend, le moteur
 * d'exemple propose des ajustements simulés sur le portefeuille affiché.
 */
export function AdjustPanel({ p, onClose }: { p: Portfolio; onClose: () => void }) {
  const state = useApp()
  const live = Boolean(state.session)
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      from: 'pepite',
      text: live
        ? `Pose-moi tes questions sur le portefeuille ${p.name}, ou dis-moi ce que tu veux changer. Je peux aussi t’expliquer une notion de finance.`
        : `Que veux-tu changer dans le portefeuille ${p.name}? Dis-le avec tes mots.`,
    },
  ])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const ctrl = useRef<AbortController | null>(null)
  const mine = state.adjustments.filter((a) => a.portfolio === p.id)

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, activity])
  useEffect(() => () => ctrl.current?.abort(), [])

  async function simulated(t: string) {
    const proposal = await proposeAdjustment(p, t, riskScore(state.profile), (patch, riskShift) =>
      state.previewAdjustment({ portfolio: p.id, patch, riskShift }),
    )
    setMsgs((m) => [...m, { from: 'pepite', text: proposal.reply, proposal, request: t, status: proposal.changes.length ? 'open' : undefined }])
  }

  async function withPepite(session: string, t: string) {
    ctrl.current = new AbortController()
    let answered = false
    const ok = await askPepite(session, `[Portefeuille affiché : ${p.name}]\n${t}`, (e) => {
      if (e.type === 'agent_status') setActivity(e.message)
      if (e.type === 'pepite' && e.final) {
        answered = true
        setMsgs((m) => [...m, { from: 'pepite', text: e.text }])
      }
      if (e.type === 'portfolios') {
        state.setPortfolios(e.portfolios)
        setMsgs((m) => [...m, { from: 'pepite', text: 'J’ai mis à jour tes portefeuilles : jette un coup d’œil au tableau de bord.' }])
      }
      if (e.type === 'error') {
        answered = true
        setMsgs((m) => [...m, { from: 'pepite', text: e.message }])
        if (/expiré/.test(e.message)) state.setSession(null)
      }
    }, ctrl.current.signal).catch(() => true)
    if (!ok) {
      state.setSession(null) // backend injoignable : on repasse au moteur d'exemple
      return simulated(t)
    }
    if (!answered) setMsgs((m) => [...m, { from: 'pepite', text: 'Je n’ai pas réussi à te répondre. Réessaie dans un instant.' }])
  }

  async function send(text: string) {
    const t = text.trim()
    if (!t || busy) return
    setDraft('')
    setMsgs((m) => [...m, { from: 'user', text: t }])
    setBusy(true)
    setActivity('')
    try {
      if (state.session) await withPepite(state.session, t)
      else await simulated(t)
    } finally {
      setBusy(false)
      setActivity('')
    }
  }

  function decide(i: number, apply: boolean) {
    const msg = msgs[i]
    if (apply && msg.proposal) state.applyAdjustment({ portfolio: p.id, label: msg.request!, patch: msg.proposal.patch ?? {}, riskShift: msg.proposal.riskShift ?? 0 })
    setMsgs((m) => m.map((x, j) => (j === i ? { ...x, status: apply ? 'applied' : 'dismissed' } : x)))
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-navy/30" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label="Ajuster avec Pépite" className="fade-in flex h-full w-full max-w-[440px] flex-col bg-white" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line-soft px-5 py-3">
          <Pepite pose="happy" size={44} />
          <div className="flex-1">
            <div className="font-semibold text-navy">{live ? 'Discuter avec Pépite' : 'Ajuster avec Pépite'}</div>
            <div className="text-xs text-ink-soft">Portefeuille {p.name}</div>
          </div>
          <button aria-label="Fermer" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-full text-slate hover:bg-mist">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-4" aria-live="polite">
          {msgs.map((m, i) => (
            <div key={i} className={`flex flex-col gap-2 ${m.from === 'user' ? 'items-end' : 'items-start'}`}>
              <div className={`max-w-[85%] rounded-[var(--radius-card)] px-4 py-2.5 text-[15px] ${m.from === 'user' ? 'bg-navy text-white' : 'bg-sky text-navy'}`}>{m.text}</div>
              {m.proposal && m.proposal.changes.length > 0 && (
                <div className="w-full rounded-[var(--radius-card)] border border-line-soft p-3">
                  <table className="w-full text-sm">
                    <tbody>
                      {m.proposal.changes.map((c) => (
                        <tr key={c.label}>
                          <td className="py-1">{c.label}</td>
                          <td className="py-1 text-right text-ink-soft">
                            {pct(c.before)} → <strong className="text-navy">{pct(c.after)}</strong>
                          </td>
                          <td className="py-1 pl-2 text-right text-xs font-semibold text-slate">{points(c.after - c.before)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {m.proposal.warning && (
                    <div className="mt-2">
                      <Alert>{m.proposal.warning}</Alert>
                    </div>
                  )}
                  {m.status === 'open' ? (
                    <div className="mt-3 flex gap-2">
                      <Button className="min-w-0 flex-1 px-4 py-1.5 text-sm" onClick={() => decide(i, true)}>
                        Appliquer
                      </Button>
                      <Button variant="tertiary" className="min-w-0 flex-1 px-4 py-1.5 text-sm" onClick={() => decide(i, false)}>
                        Non merci
                      </Button>
                    </div>
                  ) : (
                    <p className="m-0 mt-2 text-xs font-semibold text-slate">{m.status === 'applied' ? 'Appliqué. Le portefeuille a été recalculé.' : 'Proposition ignorée.'}</p>
                  )}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="fade-in text-sm text-ink-soft">{activity || 'Pépite réfléchit…'}</div>}
          <div ref={end} />
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

        <div className="border-t border-line-soft px-5 py-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {(live ? LIVE_SUGGESTIONS : SUGGESTIONS).map((s) => (
              <button key={s} onClick={() => send(s)} className="min-h-8 rounded-full bg-mist px-3 text-sm font-medium text-navy hover:bg-sky">
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
            <input id="adjust-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={live ? 'Ex. : pourquoi autant d’obligations?' : 'Ex. : plus de tech, pas de pétrole…'} className="min-h-11 flex-1 rounded-[var(--radius-card)] border border-line px-3 text-[15px] outline-none" />
            <Button type="submit" className="min-w-0 px-5" disabled={!draft.trim() || busy}>
              Envoyer
            </Button>
          </form>
        </div>
      </aside>
    </div>
  )
}
