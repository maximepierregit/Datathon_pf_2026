// Explication du modèle des scores de facteurs (vue Avancé) : étapes de calcul, sous-mesures et leurs poids.
import { FACTOR_IDS, FACTOR_MODEL, FACTOR_VIEW } from '../../data/catalog'
import { pct } from '../../lib/format'

// Teintes de marine pour distinguer les sous-mesures d'un même facteur (aplats, du plus foncé au plus clair).
const SHADES = ['#00314D', '#33566E', '#667C8C', '#99A9B3']

const STEPS = [
  { title: 'Plafonner les extrêmes', text: 'Chaque mesure est ramenée entre son 1er et son 99e centile, pour qu’une donnée aberrante ne fausse pas tout.' },
  { title: 'Comparer au groupe', text: 'Chaque mesure devient un z-score dans le groupe comparable : 0 = moyenne, +1 = un écart-type mieux.' },
  { title: 'Combiner', text: 'Moyenne simple des sous-mesures disponibles, à poids égaux. Une mesure manquante est ignorée.' },
  { title: 'Remettre à l’échelle', text: 'La moyenne est de nouveau ramenée en z-score dans le groupe : c’est le score final de l’action.' },
]

const GROUP = {
  'marche-secteur': 'Comparée à son marché et son secteur',
  marche: 'Comparée à son marché seulement',
}

export function FactorModel() {
  return (
    <details className="group rounded-[var(--radius-card)] border border-line-soft">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 font-semibold text-navy [&::-webkit-details-marker]:hidden">
        <span>
          Comment on calcule les scores? <span className="font-normal text-ink-soft">(le modèle)</span>
        </span>
        <svg className="shrink-0 transition-transform group-open:rotate-180" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </summary>

      <div className="flex flex-col gap-6 px-4 pb-5">
        {/* Étapes */}
        <section className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold tracking-[0.4px] text-slate uppercase">Pour chaque action, en 4 étapes</h3>
          <ol className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-navy text-xs font-bold text-white">{i + 1}</span>
                <span className="flex flex-col gap-0.5">
                  <span className="text-sm font-semibold text-navy">{s.title}</span>
                  <span className="text-[13px] leading-5 text-ink-soft">{s.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>

        {/* Sous-mesures et poids */}
        <section className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold tracking-[0.4px] text-slate uppercase">Ce que mesure chaque facteur</h3>
          <ul className="m-0 grid list-none gap-3 p-0 md:grid-cols-2">
            {FACTOR_IDS.map((id) => {
              const m = FACTOR_MODEL[id]
              const w = 1 / m.metrics.length
              return (
                <li key={id} className="flex flex-col gap-3 rounded-[var(--radius-card)] bg-mist/60 p-4">
                  <div className="flex flex-col gap-0.5">
                    <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="text-[15px] font-semibold text-navy">{FACTOR_VIEW[id].label}</span>
                      <span className="text-xs text-slate">{GROUP[m.group]}</span>
                    </span>
                    <span className="text-[13px] leading-5 text-ink-soft">{m.idea}</span>
                  </div>
                  <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                    {m.metrics.map((x, i) => (
                      <span key={x.label} className="h-full" style={{ flex: 1, background: SHADES[i % SHADES.length] }} />
                    ))}
                  </div>
                  <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {m.metrics.map((x, i) => (
                      <li key={x.label} className="flex items-center gap-2 text-[13px] leading-5">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SHADES[i % SHADES.length] }} aria-hidden />
                        <span className="min-w-0 flex-1 text-ink">{x.label}</span>
                        <span className="shrink-0 font-semibold text-navy tabular-nums">{pct(w, Number.isInteger(Math.round(w * 1000) / 10) ? 0 : 1)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              )
            })}
          </ul>
        </section>

        {/* Du titre au portefeuille */}
        <section className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-line-soft p-4">
          <h3 className="text-xs font-semibold tracking-[0.4px] text-slate uppercase">De l’action à ton portefeuille</h3>
          <p className="m-0 text-center text-[15px] text-navy">
            Exposition = <span className="font-semibold">Σ (poids × score)</span> ÷ <span className="font-semibold">Σ poids des actions notées</span>
          </p>
          <p className="m-0 text-[13px] leading-5 text-ink-soft">
            Les FNB et les cryptos n’ont pas de score : ils ne comptent ni dans le calcul ni dans le total des poids. Données : Yahoo Finance, une photo
            prise à une date donnée, pas une prévision. Une action sans aucune donnée pour un facteur reçoit 0 (neutre).
          </p>
        </section>
      </div>
    </details>
  )
}
