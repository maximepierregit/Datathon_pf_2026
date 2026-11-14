import { useState } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { Card } from '../../components/ui'
import { CLASS_COLORS, CLASS_LABELS } from '../../data/catalog'
import { money, pct } from '../../lib/format'
import type { AssetClass, Portfolio } from '../../types'

export const classesOf = (p: Portfolio) =>
  (Object.keys(p.allocation) as AssetClass[]).filter((k) => p.allocation[k] > 0.0005).sort((a, b) => p.allocation[b] - p.allocation[a])

export function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-4 flex flex-col gap-1">
      <h2 className="text-[24px] font-semibold leading-7 text-navy">{children}</h2>
      {sub && <p className="m-0 text-sm text-ink-soft">{sub}</p>}
    </div>
  )
}

/** Barre de répartition horizontale. */
export function AllocationBar({ p, tall = false }: { p: Portfolio; tall?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <div className={`flex w-full overflow-hidden rounded-[var(--radius-card)] ${tall ? 'h-10' : 'h-4'}`} role="img" aria-label={classesOf(p).map((k) => `${CLASS_LABELS[k]} ${pct(p.allocation[k], 0)}`).join(', ')}>
        {classesOf(p).map((k) => (
          <div key={k} style={{ width: `${p.allocation[k] * 100}%`, background: CLASS_COLORS[k] }} />
        ))}
      </div>
      <Legend p={p} />
    </div>
  )
}

export function Legend({ p }: { p: Portfolio }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm">
      {classesOf(p).map((k) => (
        <li key={k} className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm" style={{ background: CLASS_COLORS[k] }} aria-hidden />
          {CLASS_LABELS[k]} <strong className="font-semibold text-navy">{pct(p.allocation[k], 0)}</strong>
        </li>
      ))}
    </ul>
  )
}

export function Donut({ p }: { p: Portfolio }) {
  const data = classesOf(p).map((k) => ({ k, name: CLASS_LABELS[k], value: p.allocation[k] }))
  return (
    <div className="relative h-56 w-56 shrink-0" role="img" aria-label="Répartition par classe d’actifs">
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="value" innerRadius="62%" outerRadius="100%" stroke="#fff" strokeWidth={2} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.k} fill={CLASS_COLORS[d.k]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-light text-navy">{p.holdings.length}</span>
        <span className="text-xs text-ink-soft">placements</span>
      </div>
    </div>
  )
}

export function Kpi({ label, value, unit, note, secondary }: { label: string; value: string; unit?: string; note: string; secondary?: [string, string][] }) {
  return (
    <Card className="flex flex-col gap-1 p-5">
      <span className="text-sm font-medium text-slate">{label}</span>
      <span className="text-[38px] font-light leading-[44px] text-navy">
        {value}
        {unit && <span className="ml-1 text-base text-ink-soft">{unit}</span>}
      </span>
      <span className="text-xs text-ink-soft">{note}</span>
      {secondary && (
        <dl className="m-0 mt-2 grid grid-cols-2 gap-2 border-t border-line-soft pt-2 text-xs">
          {secondary.map(([k, v]) => (
            <div key={k}>
              <dt className="text-ink-soft">{k}</dt>
              <dd className="m-0 font-semibold text-navy">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  )
}

/** Liste d'achat ligne par ligne, filtrable par classe. */
export function HoldingsTable({ p, amount, detailed = false }: { p: Portfolio; amount: number; detailed?: boolean }) {
  const [filter, setFilter] = useState<AssetClass | 'all'>('all')
  const rows = p.holdings.filter((h) => filter === 'all' || h.assetClass === filter)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrer par classe">
        {(['all', ...classesOf(p)] as const).map((k) => (
          <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)} className={`min-h-9 rounded-full border px-4 text-sm font-medium ${filter === k ? 'border-navy bg-sky text-navy' : 'border-line-soft bg-white text-ink-soft hover:text-navy'}`}>
            {k === 'all' ? 'Tout' : CLASS_LABELS[k]}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line-soft">
        <table className="w-full min-w-[520px] border-collapse text-left text-[15px]">
          <thead className="bg-mist text-xs text-slate">
            <tr>
              <th className="px-4 py-2 font-semibold">Code</th>
              <th className="px-4 py-2 font-semibold">Placement</th>
              {detailed && <th className="px-4 py-2 font-semibold">Classe</th>}
              <th className="px-4 py-2 text-right font-semibold">Poids</th>
              <th className="px-4 py-2 text-right font-semibold">Montant</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.ticker} className="border-t border-line-soft">
                <td className="px-4 py-2.5 font-mono text-sm text-slate">{h.ticker}</td>
                <td className="px-4 py-2.5">
                  <span className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: CLASS_COLORS[h.assetClass] }} aria-hidden />
                    {h.name}
                  </span>
                </td>
                {detailed && <td className="px-4 py-2.5 text-ink-soft">{CLASS_LABELS[h.assetClass]}</td>}
                <td className="px-4 py-2.5 text-right font-semibold text-navy">{pct(h.weight)}</td>
                <td className="px-4 py-2.5 text-right">{money(h.weight * amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="m-0 text-xs text-ink-soft">Données d’exemple : placements fictifs en attendant l’univers réel.</p>
    </div>
  )
}

export function AgentNotes({ p }: { p: Portfolio }) {
  const notes = [...p.agentNotes, 'Le Vérificateur confirme que ce portefeuille respecte les limites de sécurité.']
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {notes.map((n) => (
        <li key={n} className="flex gap-2 text-[15px]">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-red" aria-hidden />
          {n}
        </li>
      ))}
    </ul>
  )
}
