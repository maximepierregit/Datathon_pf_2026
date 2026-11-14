import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Pepite } from '../../components/Pepite'
import { Card } from '../../components/ui'
import { CLASS_COLORS, CLASS_EXPLAINERS, CLASS_LABELS } from '../../data/catalog'
import { backtest, projection, returnDistribution, riskContribution } from '../../lib/engine'
import { money, pct, signedPct } from '../../lib/format'
import type { Portfolio } from '../../types'
import { AgentNotes, AllocationBar, classesOf, Donut, HoldingsTable, Kpi, Legend, SectionTitle } from './parts'

const axis = { fontSize: 12, fill: '#565656' }
const grid = <CartesianGrid stroke="#E1E1E1" vertical={false} />

// ---------- Débutant ----------

export function Beginner({ p, amount }: { p: Portfolio; amount: number }) {
  const eq = p.allocation.actions
  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-4">
        <SectionTitle>Comment ton argent est réparti</SectionTitle>
        <AllocationBar p={p} tall />
        <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2">
          {classesOf(p).map((k) => (
            <li key={k} className="flex gap-3">
              <span className="mt-1 h-4 w-4 shrink-0 rounded-sm" style={{ background: CLASS_COLORS[k] }} aria-hidden />
              <span className="flex flex-col">
                <span className="font-semibold text-navy">
                  {CLASS_LABELS[k]} · {pct(p.allocation[k], 0)}
                </span>
                <span className="text-[15px] text-ink-soft">{CLASS_EXPLAINERS[k]}</span>
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <SectionTitle>À quoi t’attendre</SectionTitle>
          <dl className="m-0 flex flex-col gap-4">
            <div>
              <dt className="text-sm text-slate">Une année normale</dt>
              <dd className="m-0 text-[30px] font-light text-navy">≈ {signedPct(p.metrics.expectedReturn, 0)}</dd>
              <dd className="m-0 text-sm text-ink-soft">soit environ {money(p.metrics.expectedReturn * amount)} sur {money(amount)}, sans garantie.</dd>
            </div>
            <div>
              <dt className="text-sm text-slate">Une mauvaise année</dt>
              <dd className="m-0 text-[30px] font-light text-red">{signedPct(p.metrics.worstYear, 0)}</dd>
              <dd className="m-0 text-sm text-ink-soft">
                Ton {money(amount)} pourrait descendre à {money(amount * (1 + p.metrics.worstYear))}. C’est normal : avec le temps, les marchés ont toujours fini par remonter.
              </dd>
            </div>
          </dl>
        </Card>
        <Card className="flex flex-col">
          <SectionTitle>En une phrase</SectionTitle>
          <p className="m-0 text-[15px]">
            Environ {pct(eq, 0)} de ton argent sert à le faire grandir (les actions), et le reste le garde stable. {p.tagline}
          </p>
          <div className="mt-auto flex items-end justify-between pt-4">
            <ol className="m-0 flex flex-col gap-1 pl-5 text-[15px]">
              <li>Compare les 3 portefeuilles avec les onglets.</li>
              <li>Demande un changement à Pépite.</li>
              <li>Passe en vue Intermédiaire pour plus de détails.</li>
            </ol>
            <Pepite pose="flag" size={88} />
          </div>
        </Card>
      </div>

      <Card>
        <SectionTitle sub={`${p.holdings.length} placements, regroupés par famille`}>Ce que tu achètes</SectionTitle>
        <div className="flex flex-col gap-4">
          {classesOf(p).map((k) => (
            <div key={k}>
              <div className="mb-1 flex justify-between border-b border-line-soft pb-1 text-sm font-semibold text-slate">
                <span>{CLASS_LABELS[k]}</span>
                <span>{pct(p.allocation[k], 0)}</span>
              </div>
              {p.holdings
                .filter((h) => h.assetClass === k)
                .map((h) => (
                  <div key={h.ticker} className="flex justify-between py-1 text-[15px]">
                    <span>{h.name}</span>
                    <span className="text-ink-soft">{money(h.weight * amount)}</span>
                  </div>
                ))}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

// ---------- Intermédiaire ----------

function KpiRow({ p, advanced = false }: { p: Portfolio; advanced?: boolean }) {
  const m = p.metrics
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Kpi label="Rendement attendu" value={pct(m.expectedReturn)} unit="/ an" note="Une estimation, sans garantie" secondary={advanced ? [['Sharpe', m.sharpe.toFixed(2).replace('.', ',')], ['Prime / liquidités', signedPct(m.expectedReturn - 0.025)]] : undefined} />
      <Kpi label="Volatilité" value={pct(m.volatility)} note="Variation typique sur un an" secondary={advanced ? [['Max drawdown', signedPct(m.maxDrawdown)], ['Vol. mensuelle', pct(m.volatility / Math.sqrt(12))]] : undefined} />
      <Kpi label="Pire année (estimation)" value={signedPct(m.worstYear, 0)} note="1 chance sur 100" secondary={advanced ? [['VaR 95 %', signedPct(-m.var95)], ['ES 95 %', signedPct(-m.es95)]] : undefined} />
      <Kpi label="Frais moyens" value={pct(m.fees, 2)} unit="/ an" note="Pondérés sur tous les placements" secondary={advanced ? [['Placements', String(p.holdings.length)], ['Plus grosse ligne', pct(p.holdings[0]?.weight ?? 0, 0)]] : undefined} />
    </div>
  )
}

function ProjectionChart({ p, amount }: { p: Portfolio; amount: number }) {
  const data = projection(p.metrics).map((d) => ({ ...d, wide: [d.p05, d.p95], likely: [d.p25, d.p75] }))
  const last = data[data.length - 1]
  return (
    <Card>
      <SectionTitle sub="Évolution de 100 $ investis aujourd’hui">Projection sur 10 ans</SectionTitle>
      <div className="h-64">
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            {grid}
            <XAxis dataKey="year" tick={axis} tickFormatter={(y) => (y === 0 ? 'Auj.' : `${y} ans`)} />
            <YAxis tick={axis} domain={['auto', 'auto']} />
            <Tooltip formatter={(v) => (Array.isArray(v) ? v.join(' – ') : String(v))} labelFormatter={(y) => `Année ${y}`} />
            <Area dataKey="wide" stroke="none" fill="#EEF6FB" name="Fourchette large (90 %)" isAnimationActive={false} />
            <Area dataKey="likely" stroke="none" fill="#B9D4E9" name="Fourchette probable (50 %)" isAnimationActive={false} />
            <Area dataKey="median" stroke="#00314D" strokeWidth={2} fill="none" name="Médiane" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="m-0 mt-2 text-sm text-ink-soft">
        Médiane après 10 ans : <strong className="text-navy">{money((last.median / 100) * amount)}</strong> pour {money(amount)} investis (probablement entre {money((last.p25 / 100) * amount)} et {money((last.p75 / 100) * amount)}).
      </p>
    </Card>
  )
}

function DistributionChart({ p }: { p: Portfolio }) {
  const data = returnDistribution(p.metrics)
  return (
    <Card>
      <SectionTitle sub="Rendements possibles sur un an">Distribution des rendements</SectionTitle>
      <div className="h-56">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
            {grid}
            <XAxis dataKey="bucket" tick={axis} tickFormatter={(v) => `${v} %`} />
            <YAxis tick={false} />
            <Bar dataKey="density" isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.bucket} fill={d.tail ? '#E41C23' : '#7993A2'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="m-0 mt-2 text-sm text-ink-soft">
        <strong className="text-red">En rouge</strong> : les 5 % de pires années. Dans ces cas, tu perdrais au moins {pct(p.metrics.var95, 0)} (VaR 95 %), en moyenne {pct(p.metrics.es95, 0)} (ES 95 %).
      </p>
    </Card>
  )
}

export function Intermediate({ p, amount }: { p: Portfolio; amount: number }) {
  return (
    <div className="flex flex-col gap-6">
      <KpiRow p={p} />
      <Card className="flex flex-col items-center gap-6 sm:flex-row">
        <Donut p={p} />
        <div className="flex flex-col gap-3">
          <SectionTitle>Répartition</SectionTitle>
          <Legend p={p} />
        </div>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <ProjectionChart p={p} amount={amount} />
        <DistributionChart p={p} />
      </div>
      <Card>
        <SectionTitle sub={`Pour ${money(amount)} investis`}>Liste d’achat</SectionTitle>
        <HoldingsTable p={p} amount={amount} />
      </Card>
      <Card>
        <SectionTitle>Notes des agents</SectionTitle>
        <AgentNotes p={p} />
      </Card>
    </div>
  )
}

// ---------- Avancé ----------

function PerformanceTab({ p }: { p: Portfolio }) {
  const data = backtest(p)
  const last = data[data.length - 1]
  const yrs = (data.length - 1) / 12
  const cagr = (v: number) => (v / 100) ** (1 / yrs) - 1
  const minDd = Math.min(...data.map((d) => d.drawdown)) / 100
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <SectionTitle sub="Simulation mensuelle sur 5 ans, base 100 (données d’exemple)">Performance vs 60/40</SectionTitle>
        <div className="h-72">
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              {grid}
              <XAxis dataKey="month" tick={axis} tickFormatter={(m) => (m % 12 === 0 ? `${m / 12} an${m > 12 ? 's' : ''}` : '')} interval={0} />
              <YAxis tick={axis} domain={['auto', 'auto']} />
              <Tooltip labelFormatter={(m) => `Mois ${m}`} />
              <Line dataKey="value" name={p.name} stroke="#00314D" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="bench" name="60/40" stroke="#7993A2" strokeDasharray="4 4" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card>
        <SectionTitle sub="Recul depuis le dernier sommet">Drawdown</SectionTitle>
        <div className="h-40">
          <ResponsiveContainer>
            <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              {grid}
              <XAxis dataKey="month" tick={axis} hide />
              <YAxis tick={axis} tickFormatter={(v) => `${v} %`} />
              <ReferenceLine y={0} stroke="#D2D2D2" />
              <Area dataKey="drawdown" stroke="#E41C23" fill="#FDECEC" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card>
        <SectionTitle>Statistiques</SectionTitle>
        <table className="w-full border-collapse text-left text-[15px]">
          <thead className="text-xs text-slate">
            <tr>
              <th className="py-2 font-semibold">Indicateur</th>
              <th className="py-2 text-right font-semibold">{p.name}</th>
              <th className="py-2 text-right font-semibold">60/40</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Rendement annualisé', signedPct(cagr(last.value)), signedPct(cagr(last.bench))],
              ['Valeur finale (base 100)', last.value.toFixed(1), last.bench.toFixed(1)],
              ['Pire recul', signedPct(minDd), '—'],
              ['Volatilité attendue', pct(p.metrics.volatility), pct(0.1)],
            ].map(([k, a, b]) => (
              <tr key={k} className="border-t border-line-soft">
                <td className="py-2">{k}</td>
                <td className="py-2 text-right font-semibold text-navy">{a}</td>
                <td className="py-2 text-right">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function RiskTab({ p, amount }: { p: Portfolio; amount: number }) {
  const contrib = riskContribution(p)
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <DistributionChart p={p} />
        <Card>
          <SectionTitle sub="Part du poids vs part du risque">Contribution au risque</SectionTitle>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {contrib.map((c) => (
              <li key={c.assetClass} className="flex flex-col gap-1 text-sm">
                <span className="flex justify-between">
                  <span>{CLASS_LABELS[c.assetClass]}</span>
                  <span className="text-ink-soft">
                    poids {pct(c.weight, 0)} · <strong className="text-navy">risque {pct(c.risk, 0)}</strong>
                  </span>
                </span>
                <span className="relative h-2 rounded-full bg-mist">
                  <span className="absolute inset-y-0 left-0 rounded-full bg-slate-light" style={{ width: `${c.weight * 100}%` }} />
                  <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${c.risk * 100}%`, background: CLASS_COLORS[c.assetClass], opacity: 0.85, height: '50%', top: '25%' }} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Card>
        <SectionTitle sub={`Pour ${money(amount)} investis`}>Positions détaillées</SectionTitle>
        <HoldingsTable p={p} amount={amount} detailed />
      </Card>
      <Card>
        <SectionTitle>Journal des agents</SectionTitle>
        <AgentNotes p={p} />
      </Card>
    </div>
  )
}

export function Advanced({ p, amount }: { p: Portfolio; amount: number }) {
  const [tab, setTab] = useState<'perf' | 'risk'>('perf')
  return (
    <div className="flex flex-col gap-6">
      <KpiRow p={p} advanced />
      <div role="tablist" aria-label="Analyses" className="flex gap-1 border-b border-line-soft">
        {(
          [
            ['perf', 'Performance'],
            ['risk', 'Risque et positions'],
          ] as const
        ).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`-mb-px min-h-11 border-b-2 px-4 font-medium ${tab === id ? 'border-red text-navy' : 'border-transparent text-ink-soft hover:text-navy'}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'perf' ? <PerformanceTab p={p} /> : <RiskTab p={p} amount={amount} />}
    </div>
  )
}
