// Moteur d'exemple côté front : il imite les agents Strands et l'optimiseur Python quand le backend ne répond pas
// (mode hors ligne), pour que l'interface s'affiche quand même. Il ne produit que le portefeuille lui-même (poids, rendement
// et risque d'ordre de grandeur, notes). Le backtest, la VaR, la projection, les répartitions, les montants et les facteurs
// sont calculés par le backend (`to_portfolio()`) : sans lui, ces sections restent vides.
import { CLASS_ASSUMPTIONS, CLASS_LABELS, BLOCKS, FACTOR_IDS, shownClasses, UNIVERSE, type UniverseLine } from '../data/catalog'
import type { AssetClass, Constraints, Evidence, Holding, Level, Metrics, Portfolio, PortfolioId, Profile, RiskNote, Share } from '../types'

const CLASSES = Object.keys(CLASS_LABELS) as AssetClass[]
const LINE_CAP = 0.4

/** Profil incohérent : les 3 portefeuilles présentés (mêmes libellés que TRIO dans backend/src/invest_agents/monport.py). */
export const PORTFOLIO_META: Record<PortfolioId, { name: string; tagline: string }> = {
  prudent: {
    name: 'Profil d’abord (80/20)',
    tagline: '80 % calé sur ton profil, 20 % sur tes préférences.',
  },
  equilibre: {
    name: 'Tes contraintes',
    tagline: 'Exactement ce que tu as demandé, même là où ça s’écarte de ton profil.',
  },
  conviction: {
    name: 'Préférences d’abord (80/20)',
    tagline: '80 % calé sur tes préférences, 20 % sur ton profil.',
  },
}

/** Profil cohérent : un seul portefeuille, celui que le juge final a gardé. */
export const WINNER_META = {
  name: 'Ton portefeuille',
  tagline: 'Trois gestionnaires se sont fait concurrence ; le juge a gardé celui-ci pour toi.',
}

export const PORTFOLIO_IDS: PortfolioId[] = ['prudent', 'equilibre', 'conviction']

export function emptyConstraints(): Constraints {
  return { vehicles: 'tous', classes: {}, regions: {}, themes: {}, factors: {} }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

// Mêmes règles que risk_position() de backend/src/invest_agents/monport.py, qui en tire l'aversion au risque A
// donnée à l'optimiseur. Une catégorie par tranche de 0,2 de S.
const OBJECTIVE_TOLERANCE = { securiser: 0, fructifier: 0.5, 'viser-haut': 1 }
const RISK_LABELS = ['Très prudent', 'Prudent', 'Équilibré', 'Audacieux', 'Très audacieux']

const CAPACITY_MARGIN = 0.125

/** Chaque réponse ramenée entre 0 et 1, puis capacité C, tolérance T et position S (le carnet de Pépite les montre). */
export function riskBreakdown(p: Profile) {
  const horizon = clamp((Math.min(p.horizon, 20) - 1) / 19, 0, 1)
  const age = clamp((75 - p.age) / 50, 0, 1)
  const reaction = clamp(p.lossReaction / 3, 0, 1)
  const objective = OBJECTIVE_TOLERANCE[p.objective]
  const comfort = clamp((p.comfort - 1) / 4, 0, 1)
  const capacity = 0.6 * horizon + 0.4 * age
  const tolerance = 0.5 * reaction + 0.3 * objective + 0.2 * comfort
  // La tolérance ne dépasse pas la capacité de plus de 3 crans sur 24.
  const capped = (capacity + tolerance) / 2 > capacity + CAPACITY_MARGIN
  const s = clamp(Math.min((capacity + tolerance) / 2, capacity + CAPACITY_MARGIN), 0, 1)
  return { horizon, age, reaction, objective, comfort, capacity, tolerance, capped, s }
}

/** S, de 0 (très prudent) à 1 (très audacieux) : capacité (horizon, âge) et tolérance (baisse, objectif, aisance). */
function riskPosition(p: Profile): number {
  return riskBreakdown(p).s
}

// Mêmes bornes que AVERSION_ANCHORS de monport.py : une par profil, interpolées en log.
export const AVERSION_ANCHORS: [number, number][] = [[0, 25], [0.2, 14], [0.4, 7], [0.6, 3.5], [0.8, 1.5], [1, 1]]

/** Aversion au risque A donnée à l'optimiseur : 25 très prudent … 1 très audacieux (risk_aversion() de monport.py). */
export function riskAversion(s: number): number {
  const x = clamp(s, 0, 1)
  for (let i = 1; i < AVERSION_ANCHORS.length; i++) {
    const [s0, a0] = AVERSION_ANCHORS[i - 1]
    const [s1, a1] = AVERSION_ANCHORS[i]
    if (x <= s1) return a0 * (a1 / a0) ** ((x - s0) / (s1 - s0))
  }
  return 1
}

const lerp = (s: number, anchors: number[]) => {
  const x = clamp(s, 0, 1) / 0.2
  const i = Math.min(4, Math.floor(x))
  return anchors[i] + (anchors[i + 1] - anchors[i]) * (x - i)
}

/**
 * Garde-fous du profil sous lesquels l'optimiseur répartit ce qui est neutre (BOND_FLOOR, NO_CRYPTO, VOL_ANCHORS et
 * STOCK_ANCHORS de monport.py).
 */
export function profileLimits(s: number) {
  const band = Math.min(4, Math.floor(clamp(s, 0, 1) / 0.2))
  return {
    bondFloor: [0.8, 0.6, 0.4, 0.2, 0][band],
    noCrypto: band <= 1,
    maxVolatility: lerp(s, [0.06, 0.08, 0.11, 0.14, 0.18, 0.25]),
    maxStock: Math.min(LINE_CAP, lerp(s, [0.07, 0.09, 0.11, 0.13, 0.17, 0.22])),
    lineCap: LINE_CAP,
  }
}

/** La position S de chaque gestionnaire (slot_position() de monport.py) ; null : « Tes préférences » ignore le profil. */
export function slotPosition(s: number, coherent: boolean, id: PortfolioId): number | null {
  if (!coherent) return id === 'conviction' ? null : s
  return clamp(s + { prudent: -0.1, equilibre: 0, conviction: 0.1 }[id], 0, 1)
}

/** Score de risque 5–95 tiré du profil. */
export function riskScore(p: Profile): number {
  return Math.round(5 + 90 * riskPosition(p))
}

export function riskLabel(score: number): string {
  return RISK_LABELS[Math.min(4, Math.floor(clamp((score - 5) / 90, 0, 1) / 0.2))]
}

const factor = (c: Constraints, id: string): Level => c.factors[id] ?? 0

/** Le pourcentage saisi, en fraction ; undefined pour neutre ou « exclure ». */
const shareOf = (v: Share | undefined): number | undefined => (typeof v === 'number' ? v / 100 : undefined)

/**
 * Répartit `total` : un élément exclu reçoit 0, un pourcentage saisi sa part de `total`, et les neutres se partagent
 * le reste au prorata de `base`.
 */
function fill(base: Record<string, number>, values: Record<string, Share>, total: number): Record<string, number> {
  const out: Record<string, number> = {}
  let fixed = 0
  for (const k of Object.keys(base)) {
    const s = shareOf(values[k])
    if (s !== undefined) {
      out[k] = s * total
      fixed += out[k]
    } else if (values[k] === 'exclure') out[k] = 0
  }
  const free = Object.keys(base).filter((k) => !(k in out))
  const freeBase = free.reduce((a, k) => a + base[k], 0)
  for (const k of free) out[k] = freeBase > 0 ? (Math.max(0, total - fixed) * base[k]) / freeBase : 0
  return out
}

function classWeights(id: PortfolioId, score: number, c: Constraints, notes: string[]) {
  const s = clamp(score + (id === 'prudent' ? -20 : id === 'conviction' ? 10 : 0), 0, 100)
  const eq = 0.15 + 0.7 * (s / 100)
  const w: Record<AssetClass, number> = {
    actions: eq,
    immobilier: 0.04,
    or: 0.03,
    crypto: 0,
    liquidites: Math.max(0.03, 0.12 - s * 0.001),
    obligations: 0,
  }
  w.obligations = Math.max(0, 1 - eq - w.immobilier - w.or - w.liquidites)

  // Hors FNB, il ne reste que les actions et la crypto.
  const shown: AssetClass[] = shownClasses(c.vehicles)
  if (c.vehicles === 'titres') for (const k of CLASSES) if (!shown.includes(k)) w[k] = 0
  // « Ton profil » ne garde que les exclusions : les pourcentages du client sont mis de côté.
  const values: Record<string, Share> = {}
  for (const k of shown) {
    const v = c.classes[k]
    if (v === undefined) continue
    if (id === 'prudent' && v !== 'exclure') {
      notes.push(`Ton pourcentage pour « ${CLASS_LABELS[k]} » a été mis de côté : ce portefeuille suit ton profil.`)
    } else values[k] = v
  }
  Object.assign(w, fill(w, values, 1))
  const total = CLASSES.reduce((a, k) => a + w[k], 0)
  if (total <= 0) {
    w.liquidites = 1
    return w
  }
  for (const k of CLASSES) w[k] /= total
  return w
}

function lineWeights(id: PortfolioId, c: Constraints, cw: Record<AssetClass, number>, notes: string[]): Holding[] {
  const out: Holding[] = []
  const push = (line: UniverseLine, weight: number) => {
    if (weight > 0.0005)
      out.push({ ticker: line.ticker, name: line.name, assetClass: line.assetClass, weight, instrument: line.instrument, detail: line.detail, sector: line.sector, region: line.home ?? line.region ?? 'mondial' })
  }
  const scale = { prudent: 0.5, equilibre: 1, conviction: 1.8 }[id]

  // Actions : les thématiques fixées en % prennent leur part, puis les actions détenues en direct, le reste se répartit
  // par région. « Ton profil » ignore les pourcentages de thématiques et de régions.
  const follows = id !== 'prudent'
  let eqLeft = cw.actions
  for (const line of UNIVERSE.filter((u) => u.theme)) {
    const wanted = follows ? shareOf(c.themes[line.theme!]) : undefined
    if (!wanted || c.vehicles === 'titres') continue
    const share = Math.min(eqLeft, cw.actions * wanted)
    push(line, share)
    eqLeft -= share
  }
  // Actions détenues en direct (sauf FNB seulement ; toute la part actions avec des titres seulement) : poids penchés
  // vers les facteurs demandés, comme l'optimiseur.
  const stocks = UNIVERSE.filter((u) => u.scores)
  if (c.vehicles !== 'fnb' && stocks.length) {
    const tilt = stocks.map((u) =>
      Math.exp(0.7 * scale * FACTOR_IDS.reduce((s, f) => s + factor(c, f) * (u.scores![f] ?? 0), 0)),
    )
    const tiltSum = tilt.reduce((a, b) => a + b, 0)
    const sleeve = eqLeft * (c.vehicles === 'titres' ? 1 : 0.35)
    stocks.forEach((u, i) => push(u, (sleeve * tilt[i]) / tiltSum))
    eqLeft -= sleeve
  }
  const baseRegion: Record<string, number> = { canada: 0.3, usa: 0.4, europe: 0.15, asie: 0.08, emergents: 0.07 }
  const regionValues = follows ? c.regions : Object.fromEntries(Object.entries(c.regions).filter(([, v]) => v === 'exclure'))
  const byRegion = fill(baseRegion, regionValues, 1)
  const regionSum = Object.values(byRegion).reduce((a, b) => a + b, 0) || 1
  for (const u of UNIVERSE.filter((u) => u.region)) push(u, (eqLeft * byRegion[u.region!]) / regionSum)

  const split: Partial<Record<AssetClass, Record<string, number>>> = {
    obligations: { 'OBL-GV': 0.6, 'OBL-SO': 0.4 },
    crypto: { 'CRY-BTC': 0.7, 'CRY-ETH': 0.3 },
  }
  for (const k of ['obligations', 'immobilier', 'or', 'crypto', 'liquidites'] as AssetClass[]) {
    for (const line of UNIVERSE.filter((u) => u.assetClass === k)) {
      push(line, cw[k] * (split[k]?.[line.ticker] ?? 1))
    }
  }

  const excluded = BLOCKS.themes.items.filter((t) => c.themes[t.id] === 'exclure').map((t) => t.label.toLowerCase())
  if (excluded.length) notes.push(`Filtre appliqué aux FNB : ${excluded.join(', ')} exclus.`)
  // L'univers d'exemple ne contient que des FNB : rien à retirer ici, l'univers réel écartera les titres individuels.
  if (c.vehicles === 'fnb') notes.push('FNB seulement : aucun titre individuel, chaque classe passe par un FNB.')
  if (c.vehicles === 'titres') notes.push('Titres individuels seulement : seules les actions et la crypto sont gardées.')

  // Limite réglementaire dure : aucune ligne au-delà de 40 %.
  let excess = 0
  for (const h of out) {
    if (h.weight > LINE_CAP) {
      excess += h.weight - LINE_CAP
      h.weight = LINE_CAP
    }
  }
  if (excess > 0) {
    const room = out.filter((h) => h.weight < LINE_CAP)
    const roomSum = room.reduce((a, h) => a + h.weight, 0)
    if (roomSum > 0) room.forEach((h) => (h.weight += (excess * h.weight) / roomSum))
    else out.push({ ticker: 'LIQ-MM', name: 'FNB marché monétaire', assetClass: 'liquidites', weight: excess })
    notes.push('Limite de sécurité : aucun placement ne dépasse 40 % du portefeuille.')
  }
  return out.sort((a, b) => b.weight - a.weight)
}

function allocationOf(holdings: Holding[]): Record<AssetClass, number> {
  const a = Object.fromEntries(CLASSES.map((k) => [k, 0])) as Record<AssetClass, number>
  for (const h of holdings) a[h.assetClass] += h.weight
  return a
}

function metricsOf(holdings: Holding[]): Metrics {
  const a = allocationOf(holdings)
  const mu = CLASSES.reduce((s, k) => s + a[k] * CLASS_ASSUMPTIONS[k].mu, 0)
  let variance = 0
  for (const i of CLASSES)
    for (const j of CLASSES) {
      const rho = i === j ? 1 : 0.3
      variance += a[i] * a[j] * CLASS_ASSUMPTIONS[i].sigma * CLASS_ASSUMPTIONS[j].sigma * rho
    }
  const sigma = Math.sqrt(variance)
  const fees = holdings.reduce((s, h) => s + h.weight * (UNIVERSE.find((u) => u.ticker === h.ticker)?.fee ?? 0.2), 0) / 100
  return {
    expectedReturn: mu,
    volatility: sigma,
    worstYear: mu - 2.33 * sigma,
    fees,
    sharpe: sigma > 0 ? (mu - 0.025) / sigma : 0,
    maxDrawdown: -Math.min(0.9, 2.2 * sigma),
    var95: -(mu - 1.645 * sigma),
    es95: -(mu - 2.063 * sigma),
  }
}

const EXAMPLE_SOURCE = 'Données d’exemple du moteur de démonstration (backend hors ligne)'

/** Preuves d'exemple, mêmes identifiants que portfolio_evidence() de backend/src/invest_agents/evidence.py. */
export function evidenceOf(p: Portfolio, profile: Profile): Record<string, Evidence> {
  const m = p.metrics
  const loss = { label: 'Baisse que tu acceptes', value: -LOSS_BY_REACTION[profile.lossReaction] }
  const top = p.holdings.reduce((a, b) => (b.weight > a.weight ? b : a))
  const hhi = p.holdings.reduce((s, h) => s + h.weight ** 2, 0)
  const item = (id: string, label: string, value: number, unit: Evidence['unit'], extra: Partial<Evidence> = {}): Evidence => ({ id, label, value, unit, source: EXAMPLE_SOURCE, ...extra })
  return Object.fromEntries(
    [
      item('pire_baisse', 'Pire baisse de ce portefeuille dans le passé', m.maxDrawdown, 'pct', { limit: loss }),
      item('mauvaise_annee', 'Une très mauvaise année (1 chance sur 100)', m.worstYear, 'pct', { limit: loss }),
      item('volatilite', 'Variation typique en un an, à la hausse comme à la baisse', m.volatility, 'pct'),
      item('ligne_max', `Plus grosse ligne : ${top.name}`, top.weight, 'pct', { limit: { label: 'Limite par ligne', value: LINE_CAP } }),
      item('diversification', 'Placements qui comptent vraiment (diversification)', hhi > 0 ? 1 / hhi : 0, 'nombre', { limit: { label: 'Lignes au total', value: p.holdings.length } }),
      item('actions', 'Part en actions', p.allocation.actions, 'pct'),
      item('obligations', 'Part en obligations', p.allocation.obligations, 'pct'),
      item('crypto', 'Part en crypto-actifs', p.allocation.crypto, 'pct'),
      item('horizon', 'Ton horizon de placement', profile.horizon, 'ans'),
    ].map((e) => [e.id, e]),
  )
}

// Mêmes valeurs que LOSS_BY_REACTION de monport.py (baisse de 20 % : je vends tout … j'investis plus).
const LOSS_BY_REACTION = [0.1, 0.15, 0.25, 0.35]

/** Alertes de cohérence profil ↔ contraintes (le backend les confie au responsable des risques). */
export function coherenceWarnings(score: number, c: Constraints): RiskNote[] {
  const w: RiskNote[] = []
  const crypto = shareOf(c.classes.crypto)
  const actions = shareOf(c.classes.actions)
  if (score < 40 && crypto)
    w.push({ title: 'Crypto et prudence font mauvais ménage', detail: 'Tu cherches de la stabilité, mais tu veux de la crypto. La crypto peut perdre la moitié de sa valeur en quelques mois.', severity: 'high', cites: ['crypto', 'pire_baisse'] })
  if (score < 40 && actions !== undefined && actions >= 0.7)
    w.push({ title: 'Beaucoup d’actions pour un profil prudent', detail: 'Avec autant d’actions, tu pourrais vivre des baisses difficiles à supporter.', severity: 'medium', cites: ['actions', 'mauvaise_annee'] })
  if (score > 65 && (c.classes.actions === 'exclure' || (actions !== undefined && actions <= 0.3)))
    w.push({ title: 'Peu d’actions pour ton horizon', detail: 'Ton profil est dynamique, mais tu limites les actions : ton argent risque de moins grandir.', severity: 'medium', cites: ['actions', 'horizon'] })
  // Sous « Très audacieux », le profil prévoit une part d'obligations, qui n'existent ici qu'en FNB.
  if (score < 77 && c.vehicles === 'titres')
    w.push({ title: 'Pas d’obligations sans FNB', detail: 'Avec des titres individuels seulement, ton portefeuille n’aura pas d’obligations : ton profil en prévoit pourtant une part pour amortir les baisses.', severity: 'medium', cites: ['obligations', 'pire_baisse'] })
  const kept = shownClasses(c.vehicles).filter((k) => c.classes[k] !== 'exclure' && c.classes[k] !== 0)
  if (kept.length === 1)
    w.push({ title: 'Un seul type de placement', detail: `Tu n’as gardé que les ${CLASS_LABELS[kept[0]].toLowerCase()} : ton portefeuille sera très peu diversifié.`, severity: 'medium', cites: ['diversification', 'ligne_max'] })
  return w
}

function buildPortfolio(id: PortfolioId, score: number, c: Constraints): Portfolio {
  const notes: string[] = []
  const cw = classWeights(id, score, c, notes)
  const holdings = lineWeights(id, c, cw, notes)
  const warnings = id === 'prudent' ? [] : coherenceWarnings(score, c)
  return {
    id,
    ...PORTFOLIO_META[id],
    riskScore: score,
    holdings,
    allocation: allocationOf(holdings),
    metrics: metricsOf(holdings),
    warnings,
    // Le moteur applique toujours la limite de 40 % : le juge n'a rien à redire.
    agentNotes: [...notes, 'Le juge confirme que ce portefeuille respecte tes limites.'],
  }
}

export function buildAll(score: number, c: Constraints): Record<PortfolioId, Portfolio> {
  return Object.fromEntries(PORTFOLIO_IDS.map((id) => [id, buildPortfolio(id, score, c)])) as Record<PortfolioId, Portfolio>
}
