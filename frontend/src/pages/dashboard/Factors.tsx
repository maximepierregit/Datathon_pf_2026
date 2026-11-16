// Exposition aux facteurs (vue Avancé) : une carte par facteur, puis les actions qui font pencher le portefeuille.
import { useEffect, useState } from 'react'
import { Card } from '../../components/ui'
import { FACTOR_IDS, FACTOR_VIEW, LEVELS } from '../../data/catalog'
import { pct } from '../../lib/format'
import { FactorModel } from './FactorModel'
import { InfoTip } from './parts'
import type { FactorId, FactorRequest, FactorView, Portfolio } from '../../types'

const RANGE = 1.5 // bornes de la jauge, en écarts-types
const NEUTRAL = 0.1 // bande blanche autour de 0

/** « +0,51 », « −0,21 » (signe moins typographique). */
function score(v: number, digits = 2): string {
  const s = Math.abs(v).toLocaleString('fr-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return (v > 0.0049 ? '+' : v < -0.0049 ? '−' : '') + s
}

// Blanc au centre, bleus puis marine vers le positif, rouges vers le négatif.
const POSITIVE = [[255, 255, 255], [21, 114, 197], [0, 49, 77]]
const NEGATIVE = [[255, 255, 255], [242, 139, 143], [228, 28, 35]]

function mix(stops: number[][], t: number): number[] {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(x))
  return stops[i].map((c, k) => Math.round(c + (stops[i + 1][k] - c) * (x - i)))
}

/** Couleur d'une valeur sur l'échelle ±max, blanche dans la bande neutre. */
function colorOf(v: number, max = RANGE): string {
  const a = Math.abs(v)
  const t = a <= NEUTRAL * (max / RANGE) ? 0 : (a - NEUTRAL * (max / RANGE)) / (max - NEUTRAL * (max / RANGE))
  const [r, g, b] = mix(v >= 0 ? POSITIVE : NEGATIVE, t)
  return `rgb(${r} ${g} ${b})`
}

const strength = (v: number) => {
  const a = Math.abs(v)
  return a < NEUTRAL ? 'Neutre' : a < 0.3 ? 'Légère' : a < 0.6 ? 'Nette' : 'Forte'
}

// ---------- Carte d'un facteur ----------

// Aplats de la charte : bleu vers le positif, rouge vers le négatif, gris quand c'est neutre.
const TONE = {
  pos: { fill: '#00314D', text: 'text-navy' },
  neg: { fill: '#E41C23', text: 'text-red' },
  zero: { fill: '#7993A2', text: 'text-slate' },
}

/** Position horizontale (0 à 100 %) d'une valeur sur l'échelle −RANGE … +RANGE. */
const x = (v: number) => ((Math.max(-RANGE, Math.min(RANGE, v)) + RANGE) / (2 * RANGE)) * 100

function FactorCard({ id, value, request }: { id: FactorId; value: number; request?: FactorRequest }) {
  const view = FACTOR_VIEW[id]
  const target = request?.threshold
  const met = request?.met
  const levelLabel = LEVELS.find((l) => l.value === request?.level)?.label
  const sign = Math.abs(value) < NEUTRAL ? 'zero' : value > 0 ? 'pos' : 'neg'
  const tone = TONE[sign]
  // La barre part du centre et rejoint sa valeur (transition CSS, coupée si l'utilisateur réduit les animations).
  const [shown, setShown] = useState(0)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(value))
    return () => cancelAnimationFrame(frame)
  }, [value])
  const pos = x(shown)
  const motion = 'motion-safe:transition-all motion-safe:duration-700 motion-safe:ease-out'

  return (
    <li className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-line-soft bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <span className="text-[15px] font-semibold leading-5 text-navy">{view.label}</span>
          <span className="text-xs text-slate">{sign === 'zero' ? 'Neutre' : `Inclinaison ${strength(value).toLowerCase()}`}</span>
        </div>
        <span className={`text-xl font-bold leading-6 tabular-nums ${tone.text}`}>{score(value)}</span>
      </div>

      <div role="img" aria-label={`${view.label} : ${score(value)} sur une échelle de −1,5 à +1,5`} className="flex flex-col gap-1.5">
        <div className="relative h-3">
          <span className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-mist" />
          <span className="absolute top-0 left-1/2 h-3 w-px -translate-x-1/2 bg-slate-light" />
          <span
            className={`absolute top-1/2 h-1 -translate-y-1/2 ${motion}`}
            style={{ left: `${Math.min(50, pos)}%`, width: `${Math.abs(pos - 50)}%`, background: tone.fill }}
          />
          {target !== undefined && (
            <span className="absolute -top-0.5 h-4 w-0.5 -translate-x-1/2 rounded-full bg-ink" style={{ left: `${x(target)}%` }} />
          )}
          <span
            className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white ${motion}`}
            style={{ left: `${pos}%`, background: tone.fill }}
          />
        </div>
        <div className="flex justify-between text-[11px] text-slate">
          <span>{view.ends[0]}</span>
          <span>{view.ends[1]}</span>
        </div>
      </div>

      <p className="m-0 text-[13px] leading-5 text-ink-soft">
        Tes actions : {sign === 'zero' ? 'dans la moyenne de leur groupe comparable' : value > 0 ? view.high : view.low}.
      </p>
      {target !== undefined && (
        <p className={`m-0 mt-auto flex items-center gap-1.5 text-xs ${met ? 'text-navy' : 'text-slate'}`}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="shrink-0">
            {met ? <path d="M5 12l5 5 9-10" /> : <circle cx="12" cy="12" r="8" />}
          </svg>
          <span>
            Ta demande : <strong className="font-semibold">{levelLabel}</strong>{' '}
            <span className="whitespace-nowrap">({target > 0 ? '≥' : '≤'} {score(target, 1)})</span>
            {met ? '' : ' · pas atteinte'}
          </span>
        </p>
      )}
    </li>
  )
}

// ---------- Contributions ----------

function Contributions({ f }: { f: FactorView }) {
  const cell = (key: string, v: number) => {
    const strong = Math.abs(v) > 0.18
    return (
      <td key={key} className="px-2 py-1.5 text-right tabular-nums" style={{ background: colorOf(v, 0.3), color: strong ? '#fff' : '#303030' }}>
        {score(v)}
      </td>
    )
  }
  const count = f.stockCount ?? f.stocks.length
  return (
    <details className="group rounded-[var(--radius-card)] border border-line-soft">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 font-semibold text-navy [&::-webkit-details-marker]:hidden">
        <span>Qui fait pencher ton portefeuille? <span className="font-normal text-ink-soft">({count} action{count > 1 ? 's' : ''})</span></span>
        <svg className="shrink-0 transition-transform group-open:rotate-180" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </summary>
      <div className="flex flex-col gap-3 px-4 pb-4">
        <p className="m-0 text-[13px] text-ink-soft">
          Chaque case : la part de l’exposition qui vient de cette action (son poids parmi tes actions × son score). La ligne Total redonne les jauges.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="text-xs text-slate">
              <tr>
                <th className="py-2 pr-2 font-semibold">Action</th>
                <th className="px-2 py-2 text-right font-semibold">Poids</th>
                {FACTOR_IDS.map((id) => (
                  <th key={id} className="px-2 py-2 text-right font-semibold">{FACTOR_VIEW[id].label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {f.stocks.map((s) => (
                <tr key={s.ticker} className="border-t border-white">
                  <td className="py-1.5 pr-2">
                    <span className="font-semibold text-navy">{s.ticker}</span> <span className="text-ink-soft">{s.name}</span>
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{pct(s.weight)}</td>
                  {FACTOR_IDS.map((id) => cell(id, s.contributions?.[id] ?? 0))}
                </tr>
              ))}
              {f.others && (
                <tr className="border-t border-white text-ink-soft">
                  <td className="py-1.5 pr-2">Autres ({f.others.count})</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{pct(f.others.weight)}</td>
                  {FACTOR_IDS.map((id) => cell(id, f.others?.contributions[id] ?? 0))}
                </tr>
              )}
              <tr className="border-t-2 border-line font-semibold">
                <td className="py-2 pr-2 text-navy">Total</td>
                <td className="px-2 py-2 text-right tabular-nums">{pct(f.coverage)}</td>
                {FACTOR_IDS.map((id) => (
                  <td key={id} className="px-2 py-2 text-right text-navy tabular-nums">{score(f.exposure[id] ?? 0)}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </details>
  )
}

// ---------- Légende et infobulle ----------

function Legend() {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1.5 p-0 text-xs text-ink-soft" aria-label="Légende">
      <li className="flex items-center gap-2">
        <span className="relative h-3 w-6" aria-hidden>
          <span className="absolute top-1/2 left-0 h-1 w-5 -translate-y-1/2 bg-navy" />
          <span className="absolute top-1/2 right-0 h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-navy" />
        </span>
        Ton portefeuille
      </li>
      <li className="flex items-center gap-2">
        <span className="h-4 w-0.5 rounded-full bg-ink" aria-hidden />
        Ta demande (le seuil visé)
      </li>
      <li className="flex items-center gap-2">
        <span className="h-3 w-px bg-slate-light" aria-hidden />
        0 : moyenne du groupe comparable
      </li>
    </ul>
  )
}

// ---------- Carte ----------

export function FactorExposure({ p }: { p: Portfolio }) {
  const f = p.factors
  if (!f) return null
  return (
    <Card className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-[24px] font-semibold leading-7 text-navy">Exposition aux facteurs</h2>
        <p className="m-0 flex flex-wrap items-center gap-1 text-sm text-ink-soft">
          <span>0 = comme la moyenne de leur groupe comparable</span>
          <InfoTip label="C’est quoi, le groupe comparable?">
            Chaque action est comparée à des entreprises semblables. <strong className="font-semibold">Petites capitalisations</strong> : aux
            autres actions de son marché (Canada, États-Unis ou France). <strong className="font-semibold">Les autres facteurs</strong> : aux
            actions de son marché et de son secteur, par exemple les banques canadiennes entre elles.
          </InfoTip>
        </p>
        <p className="m-0 text-sm text-ink-soft">Un score positif penche vers le style, un score négatif à l’opposé.</p>
      </div>
      {f.coverage <= 0 ? (
        <p className="m-0 text-[15px] text-ink-soft">
          Ton portefeuille ne contient que des FNB : on ne peut pas mesurer ses facteurs, car seules les actions détenues en direct ont un score.
        </p>
      ) : (
        <>
          <p className="m-0 flex flex-wrap items-center gap-2 text-[15px] text-ink-soft">
            <span className="relative inline-block h-2 w-24 overflow-hidden rounded-full bg-mist" aria-hidden>
              <span className="absolute inset-y-0 left-0 rounded-full bg-navy" style={{ width: `${f.coverage * 100}%` }} />
            </span>
            Calculé sur tes actions détenues en direct : <strong className="text-navy">{pct(f.coverage, 0)}</strong> de ton portefeuille. Les FNB n’ont pas de score.
          </p>
          <Legend />
          <div className="@container">
          <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 @min-[560px]:grid-cols-3 @min-[880px]:grid-cols-5">
            {FACTOR_IDS.map((id) => (
              <FactorCard key={id} id={id} value={f.exposure[id] ?? 0} request={f.requests?.[id]} />
            ))}
          </ul>
          </div>
          <Contributions f={f} />
        </>
      )}
      <FactorModel />
    </Card>
  )
}
