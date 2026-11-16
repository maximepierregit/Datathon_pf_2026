// Briques des graphiques du tableau de bord : légende, infobulle lisible, barres de répartition, note du backtest.
import { useState } from 'react'
import { CLASS_COLORS, CLASS_LABELS, REGION_COLORS, REGION_LABELS } from '../../data/catalog'
import { pct } from '../../lib/format'
import type { AssetClass, Backtest, Portfolio, RegionId } from '../../types'

export type LegendItem = { label: string; color: string; kind: 'line' | 'dash' | 'box' }

/** Légende sous un graphique : trait plein, pointillé ou aplat. */
export function ChartLegend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-ink-soft">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          {it.kind === 'box' ? (
            <span className="h-2.5 w-3.5 rounded-sm" style={{ background: it.color }} aria-hidden />
          ) : (
            <span className="w-4 border-t-2" style={{ borderColor: it.color, borderStyle: it.kind === 'dash' ? 'dashed' : 'solid' }} aria-hidden />
          )}
          {it.label}
        </li>
      ))}
    </ul>
  )
}

type TipRow = { name?: string | number; value?: unknown; color?: string; fill?: string; stroke?: string; dataKey?: unknown }

/** Infobulle des graphiques : fond blanc, texte foncé, une pastille de couleur par série. */
export function ChartTip({
  active,
  payload,
  label,
  title,
  format,
}: {
  active?: boolean
  payload?: TipRow[]
  label?: string | number
  title: (label: string | number) => string
  format: (v: number) => string
}) {
  if (!active || !payload?.length || label === undefined) return null
  return (
    <div className="rounded-[var(--radius-card)] border border-line-soft bg-white px-3 py-2 text-xs shadow-[var(--shadow-hover)]">
      <p className="m-0 mb-1 font-semibold text-navy">{title(label)}</p>
      <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
        {payload.map((row) => {
          const v = row.value
          const text = Array.isArray(v) ? v.map((x) => format(Number(x))).join(' – ') : format(Number(v))
          const swatch = row.stroke && row.stroke !== 'none' ? row.stroke : (row.fill ?? row.color)
          return (
            <li key={String(row.dataKey ?? row.name)} className="flex items-center justify-between gap-4 text-ink">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: swatch }} aria-hidden />
                {row.name}
              </span>
              <span className="font-semibold tabular-nums">{text}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Barres horizontales de répartition, une ligne par groupe. */
export function Bars({ rows }: { rows: { key: string; label: string; weight: number; color: string }[] }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,200px)_1fr_auto] items-center gap-3 text-[15px]">
          <span className="truncate">{r.label}</span>
          <span className="h-2 rounded-full bg-mist" aria-hidden>
            <span className="block h-2 rounded-full" style={{ width: `${r.weight * 100}%`, background: r.color }} />
          </span>
          <span className="w-14 text-right font-semibold text-navy tabular-nums">{pct(r.weight, r.weight < 0.01 ? 1 : 0)}</span>
        </li>
      ))}
    </ul>
  )
}

/** Libellé et couleur d'une ligne de répartition. Les sommes viennent du backend (`breakdowns()`), le front les met en page. */
const ROWS = {
  classe: (key: string) => ({ label: CLASS_LABELS[key as AssetClass] ?? key, color: CLASS_COLORS[key as AssetClass] ?? '#7993A2' }),
  region: (key: string) => ({ label: REGION_LABELS[key as RegionId] ?? key, color: REGION_COLORS[key as RegionId] ?? '#7993A2' }),
  secteur: (key: string) => ({ label: key, color: '#00314D' }),
}

const VIEWS = {
  classe: { label: 'Par classe d’actifs', note: 'La famille de chaque placement.' },
  region: { label: 'Par géographie', note: 'Le pays de chaque action, le marché principal de chaque FNB.' },
  secteur: { label: 'Par secteur', note: 'Le secteur de chaque action et de chaque FNB sectoriel.' },
}
type View = keyof typeof VIEWS

/** Répartition en barres, avec un bouton par vue (mêmes boutons et mêmes barres dans les 3 niveaux). */
export function Breakdown({ p, title = 'Répartition', views = ['classe', 'region', 'secteur'] }: { p: Portfolio; title?: string; views?: View[] }) {
  const [view, setView] = useState<View>(views[0])
  if (!p.breakdown) return null
  const rows = p.breakdown[view].map((r) => ({ key: r.key, weight: r.weight, ...ROWS[view](r.key) }))
  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-[24px] font-semibold leading-7 text-navy">{title}</h2>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Répartir par">
        {views.map((id) => (
          <button
            key={id}
            aria-pressed={view === id}
            onClick={() => setView(id)}
            className={`min-h-9 rounded-full border px-4 text-sm font-medium ${view === id ? 'border-navy bg-sky text-navy' : 'border-line-soft bg-white text-ink-soft hover:text-navy'}`}
          >
            {VIEWS[id].label}
          </button>
        ))}
      </div>
      <Bars rows={rows} />
      <p className="m-0 text-xs text-ink-soft">{VIEWS[view].note}</p>
    </div>
  )
}

/** Mode hors ligne : cette section est calculée par le backend, que le front n'a pas pu joindre. */
export function NeedsBackend({ short = false }: { short?: boolean }) {
  return <p className="m-0 text-[15px] text-ink-soft">{short ? 'Calculé par le serveur, indisponible hors ligne.' : 'Cette section est calculée par le serveur. Elle sera disponible dès que les agents répondent.'}</p>
}

const dateFr = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString('fr-CA', { year: 'numeric', month: 'short', day: 'numeric' })

/** Sous les graphiques tirés du backtest : la période et le rappel. */
export function BacktestNote({ b }: { b: Backtest }) {
  return (
    <p className="m-0 text-xs text-ink-soft">
      Simulé sur des données passées, du {dateFr(b.start)} au {dateFr(b.end)}. Les rendements passés ne garantissent pas les rendements futurs.
    </p>
  )
}

/** Avertissement en tête de la performance : historique limité, résultats possiblement biaisés. */
export function BacktestWarning() {
  return (
    <div role="note" className="flex gap-3 rounded-[var(--radius-card)] border border-[#F5C2C4] bg-[#FDECEC] px-4 py-3 text-[14px] leading-5 text-red-dark">
      <svg className="mt-0.5 shrink-0" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
        <path d="M12 3l10 18H2zM12 10v5M12 18h.01" />
      </svg>
      <p className="m-0">
        Simulé sur des données passées, avec un historique limité : les résultats peuvent être biaisés.{' '}
        <strong className="font-semibold">Les rendements passés ne garantissent pas les rendements futurs.</strong>
      </p>
    </div>
  )
}
