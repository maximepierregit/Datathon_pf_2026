import { useState } from 'react'
import { Pepite, PepiteSays, type Pose } from '../components/Pepite'
import { BLOCKS, CLASS_LABELS, FACTOR_TARGETS, LEVELS, shownClasses } from '../data/catalog'
import { AVERSION_ANCHORS, PORTFOLIO_IDS, profileLimits, riskAversion, riskBreakdown, riskLabel, slotPosition } from '../lib/engine'
import { pct, share } from '../lib/format'
import type { Constraints, Level, PortfolioId, Profile, ProfileCheck, ShareBlock } from '../types'

/**
 * Le carnet de Pépite : caché derrière un « psst », il montre pas à pas comment elle mesure ton niveau de risque
 * (capacité, tolérance, position S, aversion A) et ce que chaque gestionnaire recevra. Mêmes étapes que
 * risk_breakdown() de backend/src/invest_agents/monport.py, que Pépite reçoit pour l'expliquer dans le chat.
 */
export function RiskNotebook({ profile, constraints, check }: { profile: Profile; constraints: Constraints; check: ProfileCheck }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(0)

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="group flex items-center gap-3 self-start rounded-[var(--radius-card)] border border-dashed border-line py-2 pl-2 pr-4 text-left transition-colors hover:border-navy hover:bg-sky"
      >
        <Pepite pose="laptop" size={44} className="shrink-0 transition-transform motion-safe:group-hover:-translate-y-1 motion-safe:group-hover:-rotate-3" />
        <span className="flex flex-col">
          <span className="text-[15px] font-semibold text-navy">Psst… tu veux voir mes calculs?</span>
          <span className="text-[13px] text-ink-soft">Mon carnet : comment j’ai mesuré ton niveau de risque, et ce qui se passe ensuite</span>
        </span>
      </button>
    )

  const b = riskBreakdown(profile)
  const s = check.risk_position ?? b.s
  const a = check.risk_aversion ?? riskAversion(s)
  const pages = PAGES(profile, constraints, b, s, a, check.coherent)
  const current = pages[page]

  return (
    <section aria-label="Le carnet de Pépite" className="fade-in relative overflow-hidden rounded-[var(--radius-card)] border border-line bg-white shadow-[var(--shadow-hover)]">
      {/* Papier ligné et marge rouge : un vrai carnet. */}
      <span
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{ backgroundImage: 'repeating-linear-gradient(to bottom, transparent 0 27px, var(--color-sky) 27px 28px)' }}
        aria-hidden
      />
      <span className="pointer-events-none absolute inset-y-0 left-7 w-px bg-red/40 sm:left-9" aria-hidden />
      <div className="relative flex flex-col gap-5 py-5 pl-11 pr-4 sm:pl-14 sm:pr-6">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-semibold text-slate">Le carnet de Pépite</span>
            <button onClick={() => setOpen(false)} className="shrink-0 rounded-full px-2 py-1 text-[13px] font-medium text-blue hover:bg-sky hover:text-blue-dark">
              Refermer
            </button>
          </div>
          {/* Les pages en haut : elles ne bougent pas quand la hauteur de la page change. */}
          <ol aria-label="Pages du carnet" className="m-0 flex list-none gap-1.5 p-0">
            {pages.map((p, i) => (
              <li key={p.title}>
                <button
                  onClick={() => setPage(i)}
                  aria-current={i === page ? 'step' : undefined}
                  aria-label={`Page ${i + 1} : ${p.title}`}
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-colors ${i === page ? 'bg-navy text-white' : 'bg-sky text-navy hover:bg-line-soft'}`}
                >
                  {i + 1}
                </button>
              </li>
            ))}
          </ol>
          <h2 className="text-xl font-semibold leading-7 text-navy">{current.title}</h2>
        </div>

        {page === 0 && <PepiteSays pose="happy" size={64}>{check.risk_explanation || explanation(b, a)}</PepiteSays>}

        <div key={page} className="fade-in flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <Pepite pose={current.pose} size={56} className="shrink-0" />
            <p className="m-0 text-[15px] leading-6 text-ink">{current.intro}</p>
          </div>
          {current.body}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-4">
          <button onClick={() => setPage((p) => p - 1)} disabled={page === 0} className="text-[13px] font-medium text-blue hover:text-blue-dark disabled:invisible">
            ← Page précédente
          </button>
          <button onClick={() => setPage((p) => p + 1)} disabled={page === pages.length - 1} className="text-[13px] font-medium text-blue hover:text-blue-dark disabled:invisible">
            Page suivante →
          </button>
        </div>
      </div>
    </section>
  )
}

type Breakdown = ReturnType<typeof riskBreakdown>

const REACTIONS = ['Je vends tout', 'Je vends une partie', 'J’attends', 'J’investis plus']
const OBJECTIVES: Record<Profile['objective'], string> = { securiser: 'Sécuriser', fructifier: 'Faire fructifier', 'viser-haut': 'Viser haut' }
const NAMES: Record<'coherent' | 'incoherent', Record<PortfolioId, string>> = {
  coherent: { prudent: 'Variante prudente', equilibre: 'Variante fidèle', conviction: 'Variante audacieuse' },
  incoherent: { prudent: 'Ton profil', equilibre: 'Tes contraintes', conviction: 'Tes préférences' },
}

/** Si Pépite n'a rien écrit (backend hors ligne) : ce qui a le plus pesé, tiré du calcul. */
function explanation(b: Breakdown, a: number): string {
  const why = b.capped
    ? 'Tu es prêt à vivre des secousses, mais ton horizon et ton âge me retiennent : je reste près de ce que ta situation permet.'
    : b.capacity > b.tolerance + 0.15
      ? 'Ta situation te permettrait plus de risque, mais ta réaction à une baisse et ton objectif me rendent plus prudente.'
      : 'Ta situation et ta tolérance vont dans le même sens : je les prends à parts égales.'
  return `${why} Tes gestionnaires recevront une aversion au risque de ${num(a, 1)}. Feuillette mon carnet pour voir chaque étape.`
}

const num = (v: number, digits = 2) => v.toLocaleString('fr-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })

function PAGES(profile: Profile, constraints: Constraints, b: Breakdown, s: number, a: number, coherent: boolean): { title: string; pose: Pose; intro: string; body: React.ReactNode }[] {
  return [
    {
      title: '1. Ce que ta situation te permet',
      pose: 'map',
      intro: 'D’abord, ta capacité à prendre du risque. Plus ton horizon est long et plus tu es jeune, plus tu as le temps de te remettre d’une baisse.',
      body: (
        <Sum
          rows={[
            { label: 'Ton horizon', answer: `${profile.horizon} an${profile.horizon > 1 ? 's' : ''}`, value: b.horizon, weight: 0.6 },
            { label: 'Ton âge', answer: `${profile.age} ans`, value: b.age, weight: 0.4 },
          ]}
          total={{ label: 'Ta capacité', symbol: 'C', value: b.capacity }}
        />
      ),
    },
    {
      title: '2. Ce que tu es prêt à vivre',
      pose: 'coffee',
      intro: 'Ensuite, ta tolérance : comment tu réagis quand ça baisse, ce que tu vises et ton aisance avec les placements. Ta réaction à une baisse compte le plus.',
      body: (
        <Sum
          rows={[
            { label: 'Si ça baisse de 20 %', answer: REACTIONS[profile.lossReaction], value: b.reaction, weight: 0.5 },
            { label: 'Ton objectif', answer: OBJECTIVES[profile.objective], value: b.objective, weight: 0.3 },
            { label: 'Ton aisance', answer: `${profile.comfort} sur 5`, value: b.comfort, weight: 0.2 },
          ]}
          total={{ label: 'Ta tolérance', symbol: 'T', value: b.tolerance }}
        />
      ),
    },
    {
      title: '3. Ton niveau de risque',
      pose: 'binoculars',
      intro: b.capped
        ? 'Ta tolérance dépasse ce que ta situation permet. Je fais la moyenne des deux, mais je ne dépasse jamais ta capacité de plus de 0,125 : on ne prend pas plus de risque que ta situation le permet.'
        : 'Je fais la moyenne de ta capacité et de ta tolérance. Ça place ton niveau de risque S quelque part entre 0 (très prudent) et 1 (très audacieux).',
      body: (
        <div className="flex flex-col gap-3">
          <Ruler s={s} c={b.capacity} t={b.tolerance} />
          <Formula>S = min((C + T) / 2 ; C + 0,125) = {num(s)}</Formula>
        </div>
      ),
    },
    {
      title: '4. Ton aversion au risque',
      pose: 'laptop',
      intro: 'Ton niveau devient un seul chiffre pour l’optimiseur : l’aversion au risque A, de 25 (très prudent) à 1 (très audacieux). Plus A est grand, plus chaque point de risque doit rapporter.',
      body: <Aversion s={s} a={a} />,
    },
    {
      title: '5. Tes choix deviennent des règles',
      pose: 'question',
      intro: 'Chaque pourcentage que tu as saisi devient une règle que tes gestionnaires ne peuvent pas contourner. Ce que tu as laissé neutre, c’est l’optimiseur qui le répartit, avec ton aversion au risque.',
      body: <Choices constraints={constraints} s={s} a={a} coherent={coherent} />,
    },
    {
      title: '6. Ce qui se passe ensuite',
      pose: 'excited',
      intro: coherent
        ? 'Tes réponses se tiennent : trois gestionnaires se font concurrence, chacun avec son propre A, et le juge garde le meilleur portefeuille pour toi.'
        : 'Tes réponses se contredisent un peu : chaque gestionnaire construit une base différente, puis je mélange leur capital. C’est toi qui choisiras.',
      body: <Process s={s} coherent={coherent} />,
    },
  ]
}

/** Une somme pondérée : chaque réponse ramenée entre 0 et 1, son poids, puis le total. */
function Sum({ rows, total }: { rows: { label: string; answer: string; value: number; weight: number }[]; total: { label: string; symbol: string; value: number } }) {
  return (
    <div className="flex flex-col gap-3">
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[160px_1fr_auto]">
            <span className="col-start-1 row-start-1 flex flex-col">
              <span className="text-[13px] text-ink-soft">{r.label}</span>
              <span className="text-[15px] font-semibold text-navy">{r.answer}</span>
            </span>
            <Bar value={r.value} className="col-span-2 row-start-2 sm:col-span-1 sm:col-start-2 sm:row-start-1" />
            <span className="col-start-2 row-start-1 text-right text-[13px] tabular-nums text-ink-soft sm:col-start-3">
              {num(r.value)} × {num(r.weight, 1)}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] bg-sky px-3 py-2">
        <span className="font-semibold text-navy">{total.label}</span>
        <span className="text-lg font-semibold tabular-nums text-navy">
          {total.symbol} = {num(total.value)}
        </span>
      </div>
    </div>
  )
}

function Bar({ value, className = '' }: { value: number; className?: string }) {
  return (
    <span className={`relative h-2 rounded-full bg-sky ${className}`} aria-hidden>
      <span className="absolute inset-y-0 left-0 rounded-full bg-navy" style={{ width: `${value * 100}%` }} />
    </span>
  )
}

function Formula({ children }: { children: React.ReactNode }) {
  return <code className="self-start rounded-md bg-mist px-2 py-1 font-mono text-[13px] text-slate">{children}</code>
}

const ZONES = ['Très prudent', 'Prudent', 'Équilibré', 'Audacieux', 'Très audacieux']

/** La règle de 0 à 1 et ses 5 profils ; Pépite se pose sur S. */
function Ruler({ s, c, t }: { s: number; c: number; t: number }) {
  return (
    <div className="flex flex-col gap-1 pt-11">
      <div className="relative">
        <span className="absolute bottom-full mb-1 -translate-x-1/2 transition-[left] duration-300" style={{ left: `${s * 100}%` }}>
          <Pepite pose="happy" size={40} />
        </span>
        <div className="grid h-3 grid-cols-5 overflow-hidden rounded-full">
          {ZONES.map((z, i) => (
            <span key={z} style={{ background: `color-mix(in srgb, var(--color-navy) ${18 + i * 18}%, white)` }} />
          ))}
        </div>
        {[
          { v: c, label: 'C' },
          { v: t, label: 'T' },
        ].map((m) => (
          <span key={m.label} className="absolute top-full mt-1 -translate-x-1/2 text-[11px] font-semibold text-slate" style={{ left: `${m.v * 100}%` }}>
            ▲{m.label}
          </span>
        ))}
      </div>
      <div className="mt-5 grid grid-cols-5 text-center text-[11px] leading-[14px] text-ink-soft">
        {ZONES.map((z) => (
          <span key={z}>{z}</span>
        ))}
      </div>
      <p className="m-0 mt-2 text-[15px] text-ink">
        Ton niveau : <strong className="text-navy">{riskLabel(Math.round(5 + 90 * s))}</strong> (S = {num(s)}).
      </p>
      <p className="m-0 text-[13px] text-ink-soft">
        ▲C : ta capacité ({num(c)}) · ▲T : ta tolérance ({num(t)})
      </p>
    </div>
  )
}

/** A sur une échelle de 25 à 1, et un curseur pour jouer avec S. */
function Aversion({ s, a }: { s: number; a: number }) {
  const [tryS, setTryS] = useState<number | null>(null)
  const playing = tryS !== null
  const shownS = tryS ?? s
  const shownA = playing ? riskAversion(shownS) : a
  // Pour passer de 10 % à 15 % de variations par an, l'optimiseur demande A/2 × (0,15² − 0,10²) de rendement en plus.
  const extra = (shownA / 2) * (0.15 ** 2 - 0.1 ** 2) * 100
  const pos = (v: number) => (Math.log(25 / v) / Math.log(25)) * 100
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <div className="relative h-3 rounded-full" style={{ background: 'linear-gradient(to right, color-mix(in srgb, var(--color-navy) 20%, white), var(--color-navy))' }}>
          <span
            className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-white bg-red shadow transition-[left] duration-200"
            style={{ left: `${pos(shownA)}%` }}
            aria-hidden
          />
        </div>
        <div className="relative h-4 text-[11px] text-ink-soft" aria-hidden>
          {AVERSION_ANCHORS.filter(([, v], i, all) => i === 0 || v !== all[i - 1][1]).map(([, v]) => (
            <span key={v} className="absolute -translate-x-1/2 tabular-nums" style={{ left: `${pos(v)}%` }}>
              {v}
            </span>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[28px] font-semibold leading-8 tabular-nums text-navy">A = {num(shownA, 1)}</span>
        <span className="text-[15px] text-ink-soft">{playing ? `si ton niveau était ${riskLabel(Math.round(5 + 90 * shownS)).toLowerCase()}` : 'ton aversion au risque'}</span>
      </div>
      <p className="m-0 rounded-[var(--radius-card)] bg-sky px-3 py-2 text-[15px] leading-6 text-navy">
        Concrètement : pour accepter qu’un portefeuille bouge de 15 % par année au lieu de 10 %, tes gestionnaires exigent au moins{' '}
        <strong className="tabular-nums">{num(extra, 1)} points</strong> de rendement de plus par année.
      </p>
      <Formula>meilleur compromis = rendement − A/2 × risque²</Formula>
      <label className="flex flex-col gap-1.5">
        <span className="flex items-center justify-between gap-3 text-[13px] font-semibold text-navy">
          Et si…? Glisse pour voir A changer
          {playing && (
            <button type="button" onClick={() => setTryS(null)} className="font-medium text-blue hover:text-blue-dark">
              Revenir à mon profil
            </button>
          )}
        </span>
        <input type="range" min={0} max={1} step={0.01} value={shownS} onChange={(e) => setTryS(Number(e.target.value))} className="accent-navy" aria-valuetext={`S = ${num(shownS)}, A = ${num(shownA, 1)}`} />
        <span className="flex justify-between text-[11px] text-ink-soft" aria-hidden>
          <span>Très prudent</span>
          <span>Très audacieux</span>
        </span>
      </label>
    </div>
  )
}

const TOLERANCE = 2 // points, comme SHARE_TOLERANCE de monport.py
const SHARE_BLOCKS: ShareBlock[] = ['classes', 'regions', 'themes']
const BLOCK_NAMES: Record<ShareBlock, string> = { classes: 'Types de placements', regions: 'Régions', themes: 'Thématiques' }
const OF: Record<ShareBlock, string> = { classes: 'du portefeuille', regions: 'de tes actions', themes: 'de tes actions' }

const labelOf = (block: ShareBlock | 'factors', id: string) =>
  block === 'classes' ? CLASS_LABELS[id as keyof typeof CLASS_LABELS] : (BLOCKS[block].items.find((i) => i.id === id)?.label ?? id)

/** Les choix du client traduits en règles, puis ce que l'optimiseur fait de ce qui reste neutre. */
function Choices({ constraints: c, s, a, coherent }: { constraints: Constraints; s: number; a: number; coherent: boolean }) {
  const items = (block: ShareBlock) => (block === 'classes' ? shownClasses(c.vehicles) : BLOCKS[block].items.map((i) => i.id))
  const fixed = SHARE_BLOCKS.flatMap((block) =>
    items(block).flatMap((id) => {
      const v = c[block][id]
      return typeof v === 'number' ? [{ block, id, v }] : []
    }),
  )
  const excluded = SHARE_BLOCKS.flatMap((block) => items(block).filter((id) => c[block][id] === 'exclure').map((id) => labelOf(block, id)))
  const factors = c.vehicles === 'fnb' ? [] : (Object.entries(c.factors) as [string, Level][]).filter(([, l]) => l !== 0)
  const neutral = SHARE_BLOCKS.map((block) => ({ block, ids: items(block).filter((id) => c[block][id] === undefined) })).filter((n) => n.ids.length)
  const lim = profileLimits(s)
  // Une classe fixée par le client garde son pourcentage : le plancher d'obligations ne s'applique pas sur elle.
  const bondsFixed = c.classes.obligations !== undefined || c.vehicles === 'titres'
  const cryptoFixed = c.classes.crypto !== undefined
  // Le plancher d'obligations se loge dans la place que tes pourcentages de classes laissent libre (follow_profile()).
  const room = 1 - fixed.filter((f) => f.block === 'classes').reduce((sum, f) => sum + Math.max(0, f.v - TOLERANCE) / 100, 0)
  const bondFloor = Math.max(0, Math.min(lim.bondFloor, room))
  const nothing = !fixed.length && !excluded.length && !factors.length && c.vehicles === 'tous'

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h3 className="text-[15px] font-semibold text-navy">Ce que tu as imposé</h3>
        {nothing ? (
          <p className="m-0 text-sm text-ink-soft">Rien : tout est neutre. Les gestionnaires ont les mains libres, sous les garde-fous de ton profil.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {c.vehicles !== 'tous' && (
              <Rule tag="Véhicule" text={c.vehicles === 'fnb' ? 'FNB seulement : aucun titre détenu en direct.' : 'Titres individuels seulement : aucun FNB, donc aucune obligation.'} />
            )}
            {fixed.map(({ block, id, v }) => {
              const lo = Math.max(0, v - TOLERANCE)
              const hi = Math.min(100, v + TOLERANCE)
              return (
                <li key={block + id} className="flex flex-col gap-1.5 rounded-[var(--radius-card)] border border-line-soft bg-white px-3 py-2">
                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="text-[15px] font-semibold text-navy">
                      {labelOf(block, id)} : {share(v)}
                    </span>
                    <span className="text-[13px] text-ink-soft">
                      entre {share(lo)} et {share(hi)} {OF[block]}
                    </span>
                  </span>
                  {/* La bande permise, sur 0 à 100 %. */}
                  <span className="relative h-2 rounded-full bg-sky" aria-hidden>
                    <span className="absolute inset-y-0 rounded-full bg-navy" style={{ left: `${lo}%`, width: `${Math.max(1.5, hi - lo)}%` }} />
                  </span>
                </li>
              )
            })}
            {excluded.length > 0 && <Rule tag="Exclu" text={`${excluded.join(', ')} : 0 %, dans les 3 portefeuilles.`} />}
            {factors.map(([id, level]) => (
              <Rule
                key={id}
                tag="Style"
                text={`${labelOf('factors', id)} (${LEVELS.find((l) => l.value === level)!.label}) : score moyen de tes actions ${level > 0 ? 'd’au moins' : 'd’au plus'} ${num(FACTOR_TARGETS[level as Exclude<Level, 0>], 1)}${Math.abs(level) === 2 ? ', obligatoire' : ''}${level === -2 ? ' dans les 3 portefeuilles' : ''}.`}
              />
            ))}
          </ul>
        )}
        {fixed.length > 0 && (
          <p className="m-0 text-[13px] leading-5 text-ink-soft">
            Une marge de {TOLERANCE} points de chaque côté laisse l’optimiseur respirer. Régions et thématiques comptent tes actions détenues en direct : un FNB n’a ni pays ni secteur.{' '}
            {coherent ? 'Les 3 gestionnaires respectent tes pourcentages.' : '« Tes contraintes » et « Tes préférences » respectent tes pourcentages ; « Ton profil » ne garde que tes exclusions.'}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-[15px] font-semibold text-navy">Ce que tu as laissé neutre</h3>
        {neutral.length > 0 ? (
          <p className="m-0 text-sm text-ink-soft">
            {neutral
              .map((n) => `${BLOCK_NAMES[n.block]} : ${n.ids.length === items(n.block).length ? 'toutes' : n.ids.length > 4 ? `${n.ids.length} sur ${items(n.block).length}` : n.ids.map((id) => labelOf(n.block, id)).join(', ')}`)
              .join(' · ')}
          </p>
        ) : (
          <p className="m-0 text-sm text-ink-soft">Rien : tu as tout décidé toi-même.</p>
        )}
        <p className="m-0 rounded-[var(--radius-card)] bg-sky px-3 py-2 text-[15px] leading-6 text-navy">
          Pour le neutre, personne ne choisit au hasard : l’optimiseur calcule la répartition qui offre le meilleur compromis rendement − A/2 × risque², avec ton A = {num(a, 1)}. Il ne dépasse jamais
          ces garde-fous :
        </p>
        <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
          {bondFloor > 0 && !bondsFixed && (
            <Guard value={`≥ ${pct(bondFloor, 0)}`} text={coherent ? 'd’obligations (±10 points selon la variante), pour amortir les baisses' : 'd’obligations dans « Ton profil », pour amortir les baisses'} />
          )}
          {lim.noCrypto && !cryptoFixed && <Guard value="0 %" text={coherent ? 'de crypto : ton profil est prudent' : 'de crypto dans « Ton profil » : il est prudent'} />}
          <Guard value={`≤ ${pct(lim.lineCap, 0)}`} text="par placement, FNB compris : jamais tout sur un seul" />
          <Guard value={`≤ ${pct(lim.maxStock, 0)}`} text="par action détenue en direct (un FNB est déjà diversifié)" />
          <Guard value={`≤ ${pct(lim.maxVolatility, 0)}`} text="de variations par an : un filet de sécurité sous A" />
          <Guard value="≥ 1 %" text="par placement retenu : pas de miettes" />
        </ul>
        {coherent && <p className="m-0 text-[13px] leading-5 text-ink-soft">Pour les variantes prudente et audacieuse, je peux ajouter quelques limites raisonnables sur ce qui est neutre, comme un plafond par secteur.</p>}
      </div>
    </div>
  )
}

function Rule({ tag, text }: { tag: string; text: string }) {
  return (
    <li className="flex items-start gap-2 rounded-[var(--radius-card)] border border-line-soft bg-white px-3 py-2 text-sm text-ink">
      <span className="mt-0.5 shrink-0 rounded-full bg-sky px-2 text-xs font-semibold leading-5 text-navy">{tag}</span>
      <span>{text}</span>
    </li>
  )
}

function Guard({ value, text }: { value: string; text: string }) {
  return (
    <li className="flex items-baseline gap-2 rounded-[var(--radius-card)] border border-line-soft bg-white px-3 py-2">
      <span className="shrink-0 text-[15px] font-semibold tabular-nums text-navy">{value}</span>
      <span className="text-[13px] leading-5 text-ink-soft">{text}</span>
    </li>
  )
}

/** Ce que reçoit chaque gestionnaire, puis qui vérifie quoi. */
function Process({ s, coherent }: { s: number; coherent: boolean }) {
  const names = NAMES[coherent ? 'coherent' : 'incoherent']
  const steps: { pose: Pose; who: string; what: string }[] = [
    { pose: 'map', who: 'Pépite', what: 'J’écris les consignes de chaque gestionnaire : tes exclusions, tes pourcentages et son aversion au risque A.' },
    {
      pose: 'thinking',
      who: 'Les juges',
      what: coherent ? 'Ils vérifient que chaque portefeuille respecte tes limites. Le juge final garde le meilleur.' : 'Ils vérifient que chaque portefeuille respecte tes limites. Je mélange ensuite le capital : 80/20 profil d’abord, 80/20 préférences d’abord.',
    },
    { pose: 'flag', who: 'Le responsable des risques', what: 'Il relit chaque portefeuille et appuie chaque mise en garde sur des preuves chiffrées, avec leur source.' },
  ]
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      <Step {...steps[0]} />
      <li className="grid gap-2 sm:grid-cols-3">
        {PORTFOLIO_IDS.map((id) => {
          const slot = slotPosition(s, coherent, id)
          return (
            <div key={id} className="flex items-center gap-2 rounded-[var(--radius-card)] border border-line-soft bg-white px-3 py-2">
              <Pepite pose="laptop" size={32} className="shrink-0" />
              <span className="flex flex-col">
                <span className="text-[13px] font-semibold leading-4 text-navy">{names[id]}</span>
                <span className="text-xs text-ink-soft">{slot === null ? 'Meilleur rendement pour le risque' : `A = ${num(riskAversion(slot), 1)}`}</span>
              </span>
            </div>
          )
        })}
      </li>
      {steps.slice(1).map((st) => (
        <Step key={st.who} {...st} />
      ))}
    </ol>
  )
}

function Step({ pose, who, what }: { pose: Pose; who: string; what: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sky">
        <Pepite pose={pose} size={34} />
      </span>
      <span className="flex flex-col">
        <span className="text-[15px] font-semibold text-navy">{who}</span>
        <span className="text-sm leading-[21px] text-ink-soft">{what}</span>
      </span>
    </li>
  )
}
