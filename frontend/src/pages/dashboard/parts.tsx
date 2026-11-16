import { useId, useState } from 'react'
import { Card } from '../../components/ui'
import { CLASS_COLORS, CLASS_LABELS } from '../../data/catalog'
import { kindOf, money, pct } from '../../lib/format'
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

/** Positions ligne par ligne, filtrables par classe. Les montants (`amount`) viennent du backend, sur le montant de départ du client. */
export function HoldingsTable({ p, detailed = false }: { p: Portfolio; detailed?: boolean }) {
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
        <table className="w-full min-w-[640px] border-collapse text-left text-[15px]">
          <thead className="bg-mist text-xs text-slate">
            <tr>
              <th className="px-4 py-2 font-semibold">Code</th>
              <th className="px-4 py-2 font-semibold">Placement</th>
              <th className="px-4 py-2 font-semibold">Type · secteur ou catégorie</th>
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
                <td className="px-4 py-2.5 text-sm text-ink-soft">{kindOf(h) || '—'}</td>
                {detailed && <td className="px-4 py-2.5 text-ink-soft">{CLASS_LABELS[h.assetClass]}</td>}
                <td className="px-4 py-2.5 text-right font-semibold text-navy">{pct(h.weight)}</td>
                <td className="px-4 py-2.5 text-right">{h.amount != null ? money(h.amount) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function AgentNotes({ p }: { p: Portfolio }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {p.agentNotes.map((n) => (
        <li key={n} className="flex gap-2 text-[15px]">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-red" aria-hidden />
          {n}
        </li>
      ))}
    </ul>
  )
}

/** Petit « i » : l'explication s'affiche au survol, au focus clavier et au toucher. */
export function InfoTip({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId()
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-light text-[11px] font-bold leading-none text-slate hover:border-navy hover:text-navy"
      >
        i
      </button>
      <span
        role="tooltip"
        id={id}
        className="invisible absolute top-full left-1/2 z-20 mt-2 w-72 -translate-x-1/2 rounded-[var(--radius-card)] bg-navy px-3 py-2 text-[13px] leading-5 text-white opacity-0 group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 motion-safe:transition-opacity"
      >
        {children}
      </span>
    </span>
  )
}
