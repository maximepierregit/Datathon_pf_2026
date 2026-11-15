import { day, evidenceValue, monthYear } from '../../lib/format'
import type { Evidence } from '../../types'

/** Une preuve du responsable des risques : la valeur, le repère, les données et leur source. */
export function EvidenceCard({ e }: { e: Evidence }) {
  return (
    <li className="flex flex-col gap-2 rounded-[var(--radius-card)] bg-sky px-3 py-2.5">
      <span className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] leading-[18px] text-ink-soft">{e.label}</span>
        <span className="shrink-0 text-[15px] font-semibold tabular-nums text-navy">{evidenceValue(e.value, e.unit)}</span>
      </span>
      <Gauge e={e} />
      {e.series && e.series.length > 1 && <Spark e={e} />}
      <span className="text-xs leading-4 text-slate">
        Source : {e.source}
        {e.period && ` · ${monthYear(e.period[0])} – ${monthYear(e.period[1])}`}
      </span>
    </li>
  )
}

/** La valeur sur une barre, avec le repère quand il y en a un (ta limite, la moyenne sur 5 ans…). */
function Gauge({ e }: { e: Evidence }) {
  if (e.unit === 'ans') return null
  const v = Math.abs(e.value)
  const l = e.limit ? Math.abs(e.limit.value) : undefined
  if (l === undefined && e.unit !== 'pct') return null
  const scale = l === undefined ? 1 : Math.max(v, l) * 1.15 || 1
  const over = l !== undefined && v > l + 1e-9
  return (
    <span className="flex flex-col gap-1">
      <span className="relative h-2 rounded-full bg-white" aria-hidden>
        <span className={`absolute inset-y-0 left-0 rounded-full ${over ? 'bg-red' : 'bg-navy'}`} style={{ width: `${Math.min(100, (v / scale) * 100)}%` }} />
        {l !== undefined && <span className="absolute -inset-y-1 w-0.5 rounded-full bg-ink" style={{ left: `${(l / scale) * 100}%` }} />}
      </span>
      {e.limit && (
        <span className={`text-xs ${over ? 'font-semibold text-red-dark' : 'text-ink-soft'}`}>
          {e.limit.label} : {evidenceValue(e.limit.value, e.unit)}
          {over && ' · dépassé'}
        </span>
      )}
    </span>
  )
}

const W = 300
const H = 56

/** La série des données : la pire baisse en rouge (sommet → creux), ou la moyenne sur 5 ans en pointillé. */
function Spark({ e }: { e: Evidence }) {
  const pts = e.series!
  const values = pts.map((p) => p.value)
  const ref = e.limit && !e.span ? e.limit.value : undefined
  const lo = Math.min(...values, ref ?? Infinity)
  const hi = Math.max(...values, ref ?? -Infinity)
  const x = (i: number) => (i / (pts.length - 1)) * W
  const y = (v: number) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8)
  const path = (from: number, to: number) => pts.slice(from, to + 1).map((p, i) => `${i ? 'L' : 'M'}${x(from + i).toFixed(1)},${y(p.value).toFixed(1)}`).join('')
  const [a, b] = e.span ? [pts.findIndex((p) => p.date >= e.span![0]), pts.findIndex((p) => p.date >= e.span![1])] : [-1, -1]
  const bEnd = b < 0 ? pts.length - 1 : b
  return (
    <span className="flex flex-col gap-0.5">
      <span className="relative block">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block h-14 w-full" role="img" aria-label={sparkLabel(e)}>
          {ref !== undefined && <line x1="0" x2={W} y1={y(ref)} y2={y(ref)} className="stroke-slate-light" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />}
          <path d={path(0, pts.length - 1)} fill="none" className="stroke-navy" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          {a >= 0 && <path d={path(a, bEnd)} fill="none" className="stroke-red" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />}
        </svg>
        {a >= 0 && (
          <span
            className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-red ring-2 ring-white"
            style={{ left: `${(x(bEnd) / W) * 100}%`, top: `${(y(pts[bEnd].value) / H) * 100}%` }}
            aria-hidden
          />
        )}
      </span>
      <span className="flex justify-between text-[11px] text-slate-light" aria-hidden>
        <span>{monthYear(pts[0].date)}</span>
        <span>{monthYear(pts[pts.length - 1].date)}</span>
      </span>
      {e.span ? (
        <span className="text-xs text-ink-soft">
          <span className="font-semibold text-red-dark">En rouge</span> : du {day(e.span[0])} au {day(e.span[1])}
        </span>
      ) : (
        ref !== undefined && <span className="text-xs text-ink-soft">Pointillé : {e.limit!.label.toLowerCase()}</span>
      )}
    </span>
  )
}

function sparkLabel(e: Evidence): string {
  const pts = e.series!
  const from = monthYear(pts[0].date)
  const to = monthYear(pts[pts.length - 1].date)
  return e.span ? `Valeur du portefeuille de ${from} à ${to}, pire baisse du ${day(e.span[0])} au ${day(e.span[1])}` : `${e.label}, de ${from} à ${to}`
}
