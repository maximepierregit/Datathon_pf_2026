import { useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { Alert, Button, Separator } from '../../components/ui'
import { PORTFOLIO_IDS } from '../../lib/engine'
import { money, pct } from '../../lib/format'
import { defaultDashboardLevel, useApp } from '../../store'
import type { DashboardLevel, PortfolioId } from '../../types'
import { AdjustPanel } from './AdjustPanel'
import { Disclaimer } from './Disclaimer'
import { Advanced, Beginner, Intermediate } from './Views'

const LEVELS: { id: DashboardLevel; label: string }[] = [
  { id: 'debutant', label: 'Débutant' },
  { id: 'intermediaire', label: 'Intermédiaire' },
  { id: 'avance', label: 'Avancé' },
]

export default function Dashboard() {
  const portfolios = useApp((s) => s.portfolios)
  const profile = useApp((s) => s.profile)
  const disclaimerSeen = useApp((s) => s.disclaimerSeen)
  const acceptDisclaimer = useApp((s) => s.acceptDisclaimer)
  const [params, setParams] = useSearchParams()
  const [chat, setChat] = useState(false)
  if (!portfolios) return <Navigate to="/" replace />

  const id = (PORTFOLIO_IDS.includes(params.get('p') as PortfolioId) ? params.get('p') : 'equilibre') as PortfolioId
  const level = (LEVELS.some((l) => l.id === params.get('niveau')) ? params.get('niveau') : defaultDashboardLevel(profile.comfort)) as DashboardLevel
  const p = portfolios[id]
  const set = (k: string, v: string) => setParams((prev) => ({ ...Object.fromEntries(prev), [k]: v }), { replace: true })
  const View = { debutant: Beginner, intermediaire: Intermediate, avance: Advanced }[level]

  return (
    <div className="flex flex-col">
      <section className="bg-white">
        <div className="mx-auto flex max-w-[1020px] flex-col gap-6 px-4 pt-10 sm:px-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-col">
              <span className="text-sm font-semibold text-slate">
                Proposition {PORTFOLIO_IDS.indexOf(id) + 1} sur 3 · {money(profile.amount)}
              </span>
              <h1 className="text-[36px] font-semibold leading-10 text-navy md:text-[50px] md:leading-[54px]">Portefeuille {p.name}</h1>
              <Separator />
              <p className="m-0 max-w-[560px] text-ink-soft">{p.tagline}</p>
            </div>
            <Button onClick={() => setChat(true)}>Ajuster avec Pépite</Button>
          </div>

          <div role="tablist" aria-label="Les 3 portefeuilles proposés" className="grid gap-2 sm:grid-cols-3">
            {PORTFOLIO_IDS.map((pid) => {
              const q = portfolios[pid]
              const on = pid === id
              return (
                <button
                  key={pid}
                  role="tab"
                  aria-selected={on}
                  onClick={() => set('p', pid)}
                  className={`flex flex-col items-start gap-1 rounded-t-[var(--radius-card)] border-x border-t px-4 py-3 text-left transition-colors ${on ? 'border-line-soft border-t-red border-t-[3px] bg-mist' : 'border-transparent bg-white hover:bg-mist/60'}`}
                >
                  <span className="flex w-full items-center justify-between">
                    <span className={`text-lg font-semibold ${on ? 'text-navy' : 'text-slate'}`}>{q.name}</span>
                    {pid === 'equilibre' && <span className="text-xs font-semibold text-red">Point de départ</span>}
                  </span>
                  <span className="text-sm text-ink-soft">
                    {pct(q.allocation.actions, 0)} actions · ≈ {pct(q.metrics.expectedReturn)} / an
                  </span>
                  {q.warnings.length > 0 && <span className="text-xs font-semibold text-red-dark">⚠ À lire avant de choisir</span>}
                </button>
              )
            })}
          </div>
        </div>
      </section>

      <section className="flex-1 bg-mist">
        <div className="mx-auto flex max-w-[1020px] flex-col gap-6 px-4 py-8 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div role="group" aria-label="Niveau de détail" className="flex rounded-[var(--radius-pill)] border border-line bg-white p-1">
              {LEVELS.map((l) => (
                <button key={l.id} aria-pressed={level === l.id} onClick={() => set('niveau', l.id)} className={`min-h-9 rounded-[var(--radius-pill)] px-4 text-sm font-medium transition-colors ${level === l.id ? 'bg-navy text-white' : 'text-slate hover:text-navy'}`}>
                  {l.label}
                </button>
              ))}
            </div>
            <span className="text-xs text-ink-soft">Données d’exemple · proposition, pas une recommandation</span>
          </div>

          {p.warnings.map((w) => (
            <Alert key={w} title="Le responsable des risques te prévient">
              {w}
            </Alert>
          ))}

          <View p={p} amount={profile.amount} />
        </div>
      </section>

      {chat && <AdjustPanel p={p} onClose={() => setChat(false)} />}
      {!disclaimerSeen && <Disclaimer onAccept={acceptDisclaimer} />}
    </div>
  )
}
