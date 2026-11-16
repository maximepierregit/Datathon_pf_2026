import { useState } from 'react'
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Pepite } from '../../components/Pepite'
import { Card } from '../../components/ui'
import { CLASS_COLORS, CLASS_LABELS, PERIODS_PER_YEAR, REBALANCE_LABELS } from '../../data/catalog'
import { backtestOf, projection, riskContribution } from '../../lib/engine'
import { contribution as contributionText, kindOf, money, pct, signedPct } from '../../lib/format'
import { useApp } from '../../store'
import type { ContributionFrequency, Portfolio } from '../../types'
import { FactorExposure } from './Factors'
import { BacktestNote, BacktestWarning, Breakdown, ChartLegend, ChartTip } from './charts'
import { AgentNotes, AllocationBar, classesOf, HoldingsTable, InfoTip, Kpi, SectionTitle } from './parts'

const axis = { fontSize: 12, fill: '#565656' }
const grid = <CartesianGrid stroke="#E1E1E1" vertical={false} />
const FREQUENCIES = Object.keys(REBALANCE_LABELS) as ContributionFrequency[]

/** « 12 k$ » pour les axes. */
const compact = (v: number) => (v >= 1000 ? `${Math.round(v / 1000).toLocaleString('fr-CA')} k$` : `${Math.round(v)} $`)
const year = (iso: string) => iso.slice(0, 4)
const dateFr = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString('fr-CA', { year: 'numeric', month: 'long', day: 'numeric' })

// ---------- Débutant ----------

function Geography({ p }: { p: Portfolio }) {
  return (
    <Card>
      <Breakdown p={p} title="Où ton argent est investi" views={['region', 'secteur']} />
    </Card>
  )
}

export function Beginner({ p, amount }: { p: Portfolio; amount: number }) {
  const eq = p.allocation.actions
  const gain = p.metrics.expectedReturn * amount
  const loss = p.metrics.worstYear * amount
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <SectionTitle>Comment ton argent est réparti</SectionTitle>
        <AllocationBar p={p} tall />
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-8">
          <SectionTitle>À quoi t’attendre</SectionTitle>
          <dl className="m-0 flex flex-col gap-8">
            <div className="flex flex-col gap-2">
              <dt className="text-sm text-slate">Une année normale</dt>
              <dd className="m-0 text-[34px] font-light leading-10 text-navy">≈ {signedPct(p.metrics.expectedReturn, 0)}</dd>
              <dd className="m-0 text-[15px] leading-6 text-ink-soft">
                Environ {gain >= 0 ? '+' : '−'}
                {money(Math.abs(gain))} sur tes {money(amount)} de départ, sans garantie.
              </dd>
            </div>
            <div className="flex flex-col gap-2">
              <dt className="text-sm text-slate">Une mauvaise année</dt>
              <dd className="m-0 text-[34px] font-light leading-10 text-red">{signedPct(p.metrics.worstYear, 0)}</dd>
              <dd className="m-0 text-[15px] leading-6 text-ink-soft">
                Tes {money(amount)} pourraient descendre à {money(amount + loss)}, soit {money(Math.abs(loss))} de moins. Avec le temps, les marchés ont toujours fini par remonter.
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

      <Geography p={p} />

      <Card>
        <SectionTitle sub={`${p.holdings.length} placements, regroupés par famille, pour tes ${money(amount)} de départ`}>Ce que tu achètes</SectionTitle>
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
                  <div key={h.ticker} className="flex items-start justify-between gap-4 py-1.5 text-[15px]">
                    <span className="flex min-w-0 flex-col">
                      <span>{h.name}</span>
                      {kindOf(h) && <span className="text-[13px] text-ink-soft">{kindOf(h)}</span>}
                    </span>
                    <span className="shrink-0 text-ink-soft">{money(h.weight * amount)}</span>
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
  const frequency = useApp((s) => s.contribution.frequency)
  const run = backtestOf(p)?.runs[frequency]
  const s = run?.stats
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Kpi
        label="Rendement attendu"
        value={pct(m.expectedReturn)}
        unit="/ an"
        note="Une estimation, sans garantie"
        secondary={advanced ? [['Sharpe', m.sharpe.toFixed(2).replace('.', ',')], ['Placements', String(p.holdings.length)]] : undefined}
      />
      <Kpi
        label="Volatilité"
        value={pct(m.volatility)}
        note="Variation typique sur un an"
        secondary={advanced ? [['Pire recul (backtest)', signedPct(s?.maxDrawdown ?? m.maxDrawdown)], ['Vol. mensuelle', pct(m.volatility / Math.sqrt(12))]] : undefined}
      />
      <Kpi
        label="Pire année (estimation)"
        value={signedPct(m.worstYear, 0)}
        note="1 chance sur 100"
        secondary={advanced && s?.var95 != null && s.es95 != null ? [['VaR 95 % (12 mois)', signedPct(-s.var95)], ['ES 95 % (12 mois)', signedPct(-s.es95)]] : undefined}
      />
    </div>
  )
}

function ProjectionChart({ p, amount }: { p: Portfolio; amount: number }) {
  const c = useApp((s) => s.contribution)
  const data = projection(p.metrics, amount, c).map((d) => ({ ...d, wide: [d.p05, d.p95], likely: [d.p25, d.p75] }))
  const last = data[data.length - 1]
  const n = PERIODS_PER_YEAR[c.frequency]
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle sub={`${money(amount)} au départ${c.frequency === 'aucune' ? '' : ` + ${contributionText(c)}`}`}>Projection sur 10 ans</SectionTitle>
      <div className="h-64">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
            {grid}
            <XAxis dataKey="year" tick={axis} tickFormatter={(y) => (y === 0 ? 'Auj.' : `${y} ans`)} />
            <YAxis tick={axis} tickFormatter={compact} width={52} domain={['auto', 'auto']} />
            <Tooltip content={<ChartTip title={(y) => (Number(y) === 0 ? 'Aujourd’hui' : `Dans ${y} an${Number(y) > 1 ? 's' : ''}`)} format={money} />} />
            <Area dataKey="wide" stroke="none" fill="#EEF6FB" name="Fourchette large" isAnimationActive={false} />
            <Area dataKey="likely" stroke="none" fill="#B9D4E9" name="Fourchette probable" isAnimationActive={false} />
            <Line dataKey="invested" stroke="#7993A2" strokeDasharray="4 4" dot={false} name="Montant versé" isAnimationActive={false} />
            <Line dataKey="expected" stroke="#00314D" strokeWidth={2} dot={false} name="Rendement moyen" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          { label: 'Rendement moyen', color: '#00314D', kind: 'line' },
          { label: 'Montant versé', color: '#7993A2', kind: 'dash' },
          { label: 'Fourchette probable (50 %)', color: '#B9D4E9', kind: 'box' },
          { label: 'Fourchette large (90 %)', color: '#EEF6FB', kind: 'box' },
        ]}
      />
      <p className="m-0 text-sm text-ink-soft">
        Dans 10 ans : ≈ <strong className="text-navy">{money(last.expected)}</strong>, dont {money(last.invested)} versés.
      </p>
      <p className="m-0 text-xs text-ink-soft">
        Rendement moyen de {pct(p.metrics.expectedReturn)} par an{n > 1 ? `, ÷ ${n} et composé à chaque versement` : ''}.
      </p>
    </Card>
  )
}

function DistributionChart({ p }: { p: Portfolio }) {
  const frequency = useApp((s) => s.contribution.frequency)
  const b = backtestOf(p)
  const run = b?.runs[frequency]
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle sub="Rendement de chaque période de 12 mois du backtest">Distribution des rendements</SectionTitle>
      {!b || !run || run.stats.var95 === null ? (
        <p className="m-0 text-[15px] text-ink-soft">Historique trop court pour cette analyse.</p>
      ) : (
        <>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={run.distribution} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                {grid}
                <XAxis dataKey="bucket" tick={axis} tickFormatter={(v) => `${v} %`} />
                <YAxis tick={axis} tickFormatter={(v) => `${Math.round(v * 100)} %`} />
                <Tooltip content={<ChartTip title={(v) => `Rendement autour de ${v} %`} format={(v) => pct(v)} />} />
                <Bar dataKey="share" name="Part des périodes" fill="#7993A2" isAnimationActive={false}>
                  {run.distribution.map((d) => (
                    <Cell key={d.bucket} fill={d.tail ? '#E41C23' : '#7993A2'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ChartLegend
            items={[
              { label: 'Périodes de 12 mois', color: '#7993A2', kind: 'box' },
              { label: '5 % les pires', color: '#E41C23', kind: 'box' },
            ]}
          />
          <p className="m-0 text-sm text-ink-soft">
            VaR 95 % : <strong className="text-navy">{signedPct(-run.stats.var95)}</strong> · ES 95 % :{' '}
            <strong className="text-navy">{signedPct(-(run.stats.es95 ?? 0))}</strong>
          </p>
          <BacktestNote b={b} />
        </>
      )}
    </Card>
  )
}

export function Intermediate({ p, amount }: { p: Portfolio; amount: number }) {
  return (
    <div className="flex flex-col gap-6">
      <KpiRow p={p} />
      <Card>
        <Breakdown p={p} />
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <ProjectionChart p={p} amount={amount} />
        <DistributionChart p={p} />
      </div>
      <Card>
        <SectionTitle sub={`Pour tes ${money(amount)} de départ`}>Liste proposée de positions</SectionTitle>
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
  const userFrequency = useApp((s) => s.contribution.frequency)
  const [frequency, setFrequency] = useState<ContributionFrequency>(userFrequency)
  const b = backtestOf(p)
  if (!b) {
    return (
      <Card>
        <SectionTitle>Performance</SectionTitle>
        <p className="m-0 text-[15px] text-ink-soft">L’historique commun de tes placements est trop court pour rejouer ce portefeuille.</p>
      </Card>
    )
  }
  const run = b.runs[frequency]
  const s = run.stats
  // Une graduation par année : le premier point de chaque année.
  const yearTicks = run.series.filter((d, i, a) => i > 0 && year(d.date) !== year(a[i - 1].date)).map((d) => d.date)
  const cumulative = run.series.map((d) => ({ date: d.date, value: d.value / 100 - 1, drawdown: d.drawdown }))
  const rows: [string, string][] = [
    ['Rendement annualisé', signedPct(s.annualReturn)],
    ['Rendement cumulé', signedPct(s.finalValue / 100 - 1)],
    ['Volatilité réalisée', pct(s.volatility)],
    ['Ratio de Sharpe', s.sharpe.toFixed(2).replace('.', ',')],
    ['Pire recul', signedPct(s.maxDrawdown)],
    ...(s.worst12m !== null && s.best12m !== null
      ? ([
          ['Pire période de 12 mois', signedPct(s.worst12m)],
          ['Meilleure période de 12 mois', signedPct(s.best12m)],
        ] as [string, string][])
      : []),
  ]
  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-4">
        <SectionTitle sub="Rendement cumulé depuis le départ, puis recul depuis le dernier sommet">Performance</SectionTitle>
        <BacktestWarning b={b} />
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Fréquence de rééquilibrage">
          <span className="mr-1 text-sm text-ink-soft">Rééquilibrage :</span>
          {FREQUENCIES.map((f) => (
            <button
              key={f}
              aria-pressed={frequency === f}
              onClick={() => setFrequency(f)}
              className={`min-h-9 rounded-full border px-4 text-sm font-medium ${frequency === f ? 'border-navy bg-sky text-navy' : 'border-line-soft bg-white text-ink-soft hover:text-navy'}`}
            >
              {REBALANCE_LABELS[f]}
              {f === userFrequency && <span className="ml-1 text-xs text-slate">(tes ajouts)</span>}
            </button>
          ))}
        </div>
        <div className="h-72">
          <ResponsiveContainer>
            <ComposedChart data={cumulative} syncId="performance" margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              {grid}
              <XAxis dataKey="date" tick={axis} tickFormatter={year} ticks={yearTicks} interval={0} />
              <YAxis tick={axis} tickFormatter={(v) => signedPct(v, 0)} width={56} domain={['auto', 'auto']} />
              <ReferenceLine y={0} stroke="#7993A2" />
              <Tooltip content={<ChartTip title={(d) => dateFr(String(d))} format={(v) => signedPct(v)} />} />
              <Line dataKey="value" name="Rendement cumulé" stroke="#00314D" strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        {/* Même axe du temps, mêmes marges et même largeur d'axe : les deux graphiques restent alignés. */}
        <div className="h-36">
          <ResponsiveContainer>
            <ComposedChart data={cumulative} syncId="performance" margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              {grid}
              <XAxis dataKey="date" tick={axis} tickFormatter={year} ticks={yearTicks} interval={0} />
              <YAxis tick={axis} tickFormatter={(v) => signedPct(v, 0)} width={56} domain={['auto', 0]} />
              <ReferenceLine y={0} stroke="#7993A2" />
              <Tooltip content={<ChartTip title={(d) => dateFr(String(d))} format={(v) => signedPct(v)} />} />
              <Area dataKey="drawdown" name="Recul depuis le sommet" stroke="#E41C23" strokeWidth={1.5} fill="#FDECEC" isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <ChartLegend
          items={[
            { label: `Rendement cumulé, rééquilibré : ${REBALANCE_LABELS[frequency].toLowerCase()}`, color: '#00314D', kind: 'line' },
            { label: 'Recul depuis le dernier sommet (drawdown)', color: '#E41C23', kind: 'line' },
            { label: '0 %', color: '#7993A2', kind: 'line' },
          ]}
        />
        <BacktestNote b={b} />
      </Card>
      <Card>
        <SectionTitle sub={`Rééquilibrage : ${REBALANCE_LABELS[frequency].toLowerCase()}`}>Statistiques</SectionTitle>
        <table className="w-full border-collapse text-left text-[15px]">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-t border-line-soft first:border-t-0">
                <td className="py-2">{k}</td>
                <td className="py-2 text-right font-semibold text-navy tabular-nums">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function RiskTab({ p, amount }: { p: Portfolio; amount: number }) {
  const contrib = p.riskContribution ?? riskContribution(p)
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <Breakdown p={p} />
      </Card>
      <FactorExposure p={p} />
      <div className="grid gap-6 lg:grid-cols-2">
        <DistributionChart p={p} />
        <Card>
          <div className="mb-4 flex flex-col gap-1">
            <h2 className="flex items-center gap-2 text-[24px] font-semibold leading-7 text-navy">
              Contribution au risque
              <InfoTip label="Comment c’est calculé?">
                {p.riskContribution ? (
                  <>
                    La part de la variation totale du portefeuille qui vient de chaque famille : pour chaque placement, son poids × sa
                    covariance avec le portefeuille, divisé par la variance du portefeuille. Les parts additionnent à 100 %. Une famille
                    volatile, ou qui bouge avec le reste, pèse plus dans le risque que dans les poids.
                  </>
                ) : (
                  <>Approximation d’exemple : poids de chaque famille × sa volatilité typique, ramené à 100 %.</>
                )}
              </InfoTip>
            </h2>
            <p className="m-0 text-sm text-ink-soft">Part du poids vs part du risque</p>
          </div>
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
                  <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(0, Math.min(1, c.risk)) * 100}%`, background: CLASS_COLORS[c.assetClass], opacity: 0.85, height: '50%', top: '25%' }} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Card>
        <SectionTitle sub={`Poids et montants pour tes ${money(amount)} de départ`}>Tes positions</SectionTitle>
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
