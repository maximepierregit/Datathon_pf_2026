import { useId } from 'react'
import { LEVELS, type CatalogItem } from '../data/catalog'
import type { Level } from '../types'

export interface Option<T> {
  value: T
  label: string
  desc?: string
}

const selected = 'border-navy bg-sky text-navy'
const idle = 'border-line-soft bg-white text-ink hover:border-slate-light'

function Radio({ on }: { on: boolean }) {
  return (
    <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${on ? 'border-navy' : 'border-line'}`} aria-hidden>
      {on && <span className="h-2.5 w-2.5 rounded-full bg-navy" />}
    </span>
  )
}

/** QCM vertical : une option par ligne. */
export function ChoiceList<T extends string | number>({ options, value, onChange, label }: { options: Option<T>[]; value: T | undefined; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-col gap-2">
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={String(o.value)} role="radio" aria-checked={on} onClick={() => onChange(o.value)} className={`flex min-h-14 items-center gap-4 rounded-[var(--radius-card)] border px-4 py-3 text-left transition-colors ${on ? selected : idle}`}>
            <Radio on={on} />
            <span className="flex flex-col">
              <span className="font-semibold">{o.label}</span>
              {o.desc && <span className="text-sm text-ink-soft">{o.desc}</span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}

/** QCM horizontal en cartes. */
export function ChoiceCards<T extends string | number>({ options, value, onChange, label }: { options: Option<T>[]; value: T | undefined; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="grid gap-3 sm:grid-cols-3">
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={String(o.value)} role="radio" aria-checked={on} onClick={() => onChange(o.value)} className={`flex min-h-28 flex-col items-start gap-2 rounded-[var(--radius-card)] border p-4 text-left transition-colors ${on ? selected : idle}`}>
            <Radio on={on} />
            <span className="font-semibold">{o.label}</span>
            {o.desc && <span className="text-sm text-ink-soft">{o.desc}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** Échelle 1–5. */
export function Scale({ value, onChange, minLabel, maxLabel, label }: { value: number | undefined; onChange: (v: number) => void; minLabel: string; maxLabel: string; label: string }) {
  return (
    <div className="flex flex-col gap-3">
      <div role="radiogroup" aria-label={label} className="grid grid-cols-5 gap-2">
        {[1, 2, 3, 4, 5].map((n) => {
          const on = n === value
          return (
            <button key={n} role="radio" aria-checked={on} aria-label={`${n} sur 5`} onClick={() => onChange(n)} className={`h-16 rounded-[var(--radius-card)] border text-xl font-semibold transition-colors ${on ? 'border-navy bg-navy text-white' : idle}`}>
              {n}
            </button>
          )
        })}
      </div>
      <div className="flex justify-between text-sm text-ink-soft">
        <span>{minLabel}</span>
        <span>{maxLabel}</span>
      </div>
    </div>
  )
}

/** Curseur avec valeur affichée en grand. */
export function Slider({ value, onChange, min, max, step = 1, format, label }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; format: (v: number) => string; label: string }) {
  const id = useId()
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="flex flex-col gap-4">
      <output htmlFor={id} className="text-5xl font-light text-navy">
        {format(value)}
      </output>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-2 w-full cursor-pointer appearance-none rounded-full accent-red"
        style={{ background: `linear-gradient(to right, #E41C23 ${pct}%, #E1E1E1 ${pct}%)` }}
      />
      <div className="flex justify-between text-sm text-ink-soft">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
    </div>
  )
}

/** Montant en dollars avec raccourcis. */
export function AmountInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const id = useId()
  return (
    <div className="flex flex-col gap-4">
      <label htmlFor={id} className="sr-only">
        Montant à investir
      </label>
      <div className="flex items-baseline gap-2 border-b-2 border-navy pb-2">
        <input
          id={id}
          inputMode="numeric"
          value={value ? value.toLocaleString('fr-CA') : ''}
          onChange={(e) => onChange(Number(e.target.value.replace(/\D/g, '')) || 0)}
          className="w-full bg-transparent text-5xl font-light text-navy outline-none focus-visible:shadow-none"
          placeholder="0"
        />
        <span className="text-3xl font-light text-slate">$</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {[5000, 10000, 25000, 50000, 100000].map((v) => (
          <button key={v} onClick={() => onChange(v)} className={`min-h-9 rounded-full border px-4 text-sm font-medium ${v === value ? selected : idle}`}>
            {v.toLocaleString('fr-CA')}&nbsp;$
          </button>
        ))}
      </div>
    </div>
  )
}

const LEVEL_STYLE: Record<Level, string> = {
  [-2]: 'bg-red text-white',
  [-1]: 'bg-[#FDECEC] text-red-dark',
  0: 'bg-white text-navy ring-1 ring-line',
  1: 'bg-sky text-navy',
  2: 'bg-navy text-white',
}

/** Échelle unique Exclure → Imposer, une ligne par élément. */
export function PreferenceTuner({ items, value, onChange }: { items: CatalogItem[]; value: Record<string, Level>; onChange: (id: string, l: Level) => void }) {
  return (
    <div className="flex flex-col gap-2">
      {items.map((it) => {
        const cur = value[it.id] ?? 0
        return (
          <div key={it.id} role="group" aria-label={it.label} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-card)] border border-line-soft bg-white py-2 pl-4 pr-2">
            <span className="flex min-w-[150px] flex-1 flex-col">
              <span className="font-semibold text-navy">{it.label}</span>
              {it.hint && <span className="text-sm text-ink-soft">{it.hint}</span>}
            </span>
            <span className="flex flex-wrap gap-0.5 rounded-[var(--radius-card)] bg-mist p-1">
              {LEVELS.map((l) => {
                const on = cur === l.value
                return (
                  <button key={l.value} aria-pressed={on} onClick={() => onChange(it.id, l.value)} className={`min-h-9 rounded-md px-3 text-[13px] font-semibold transition-colors ${on ? LEVEL_STYLE[l.value] : 'text-ink-soft hover:text-navy'}`}>
                    {l.label}
                  </button>
                )
              })}
            </span>
          </div>
        )
      })}
    </div>
  )
}
