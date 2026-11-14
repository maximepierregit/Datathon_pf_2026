// Moteur d'exemple côté front : il imite ce que feront les agents Strands et l'optimiseur Python,
// pour que l'interface fonctionne avant le branchement du backend.
import { CLASS_ASSUMPTIONS, CLASS_LABELS, BLOCKS, UNIVERSE, type UniverseLine } from '../data/catalog'
import type { AssetClass, Constraints, Holding, Level, Metrics, Portfolio, PortfolioId, Profile } from '../types'

const CLASSES = Object.keys(CLASS_LABELS) as AssetClass[]
const LINE_CAP = 0.4

export const PORTFOLIO_META: Record<PortfolioId, { name: string; tagline: string }> = {
  prudent: {
    name: 'Prudent',
    tagline: 'Ton profil d’abord : on privilégie la stabilité, quitte à mettre de côté certaines préférences.',
  },
  equilibre: {
    name: 'Équilibré',
    tagline: 'Le juste milieu entre ton profil et tes préférences. Un bon point de départ.',
  },
  conviction: {
    name: 'Conviction',
    tagline: 'Tes préférences d’abord : on suit tes choix, dans les limites de sécurité.',
  },
}

export const PORTFOLIO_IDS: PortfolioId[] = ['prudent', 'equilibre', 'conviction']

export function emptyConstraints(): Constraints {
  return { classes: {}, regions: {}, themes: {}, factors: {} }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Score de risque 5–95 tiré du profil. */
export function riskScore(p: Profile): number {
  const age = p.age < 30 ? 20 : p.age < 45 ? 12 : p.age < 60 ? 4 : -10
  const horizon = Math.min(p.horizon, 25)
  const objective = { securiser: 0, fructifier: 15, 'viser-haut': 30 }[p.objective]
  return clamp(Math.round(age + horizon + objective + p.lossReaction * 10), 5, 95)
}

export function riskLabel(score: number): string {
  return score < 35 ? 'Prudent' : score < 65 ? 'Modéré' : 'Audacieux'
}

const level = (c: Constraints, block: keyof Constraints, id: string): Level => c[block][id] ?? 0

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

  const risky: AssetClass[] = ['actions', 'immobilier', 'or', 'crypto']
  const plus = { prudent: 0.05, equilibre: 0.05, conviction: 0.12 }[id]
  const impose = { prudent: 0.1, equilibre: 0.1, conviction: 0.25 }[id]
  for (const k of CLASSES) {
    const l = level(c, 'classes', k)
    if (l === 0) continue
    if (l === -2) w[k] = 0
    else if (l === -1) w[k] *= id === 'conviction' ? 0.4 : 0.6
    else if (id === 'prudent' && risky.includes(k)) {
      notes.push(`Ta préférence pour « ${CLASS_LABELS[k]} » a été mise de côté : ton profil demande de la stabilité.`)
    } else {
      const bump = k === 'crypto' ? (id === 'conviction' ? (l === 2 ? 0.3 : 0.1) : 0.03) : l === 2 ? 0 : plus
      w[k] = l === 2 ? Math.max(w[k] + bump, k === 'crypto' && id !== 'conviction' ? 0.05 : impose) : w[k] + bump
    }
  }
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
    if (weight > 0.0005) out.push({ ticker: line.ticker, name: line.name, assetClass: line.assetClass, weight })
  }
  const scale = { prudent: 0.5, equilibre: 1, conviction: 1.8 }[id]

  // Actions : thèmes et facteurs prennent une part, le reste se répartit par région.
  let eqLeft = cw.actions
  for (const line of UNIVERSE.filter((u) => u.theme || u.factor)) {
    const l = line.theme ? level(c, 'themes', line.theme) : level(c, 'factors', line.factor!)
    if (l <= 0) continue
    const share = Math.min(eqLeft, cw.actions * (l === 2 ? 0.16 : 0.08) * scale)
    push(line, share)
    eqLeft -= share
  }
  const baseRegion: Record<string, number> = { canada: 0.3, usa: 0.4, europe: 0.15, asie: 0.08, emergents: 0.07 }
  const mult: Record<Level, number> = { [-2]: 0, [-1]: 0.5, 0: 1, 1: 1.6, 2: 2.2 }
  const regions = UNIVERSE.filter((u) => u.region)
  const raw = regions.map((u) => baseRegion[u.region!] * mult[level(c, 'regions', u.region!)])
  const rawSum = raw.reduce((a, b) => a + b, 0) || 1
  regions.forEach((u, i) => push(u, (eqLeft * raw[i]) / rawSum))

  const split: Partial<Record<AssetClass, Record<string, number>>> = {
    obligations: { 'OBL-GV': 0.6, 'OBL-SO': 0.4 },
    crypto: { 'CRY-BTC': 0.7, 'CRY-ETH': 0.3 },
  }
  for (const k of ['obligations', 'immobilier', 'or', 'crypto', 'liquidites'] as AssetClass[]) {
    for (const line of UNIVERSE.filter((u) => u.assetClass === k)) {
      push(line, cw[k] * (split[k]?.[line.ticker] ?? 1))
    }
  }

  const excluded = BLOCKS.themes.items.filter((t) => level(c, 'themes', t.id) === -2).map((t) => t.label.toLowerCase())
  if (excluded.length) notes.push(`Filtre appliqué aux FNB : ${excluded.join(', ')} exclus.`)

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

export function allocationOf(holdings: Holding[]): Record<AssetClass, number> {
  const a = Object.fromEntries(CLASSES.map((k) => [k, 0])) as Record<AssetClass, number>
  for (const h of holdings) a[h.assetClass] += h.weight
  return a
}

export function metricsOf(holdings: Holding[]): Metrics {
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

/** Alertes de cohérence profil ↔ contraintes (rôle futur du Vérificateur). */
export function coherenceWarnings(score: number, c: Constraints): string[] {
  const w: string[] = []
  const crypto = level(c, 'classes', 'crypto')
  const actions = level(c, 'classes', 'actions')
  if (score < 40 && crypto >= 1)
    w.push('Tu cherches plutôt de la stabilité, mais tu demandes plus de crypto-actifs. Les deux se marient mal : la crypto peut perdre la moitié de sa valeur en quelques mois.')
  if (score < 40 && actions === 2)
    w.push('Imposer beaucoup d’actions avec un profil prudent peut te faire vivre des baisses difficiles à supporter.')
  if (score > 65 && actions <= -1)
    w.push('Ton profil est dynamique, mais tu limites les actions : le rendement attendu sera plus faible que ce que ton horizon permet.')
  const kept = CLASSES.filter((k) => level(c, 'classes', k) !== -2)
  if (kept.length === 1) w.push(`Tu n’as gardé qu’un seul type de placement (${CLASS_LABELS[kept[0]].toLowerCase()}) : ton portefeuille sera très peu diversifié.`)
  return w
}

export function buildPortfolio(id: PortfolioId, score: number, c: Constraints): Portfolio {
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
    agentNotes: notes,
  }
}

export function buildAll(score: number, c: Constraints): Record<PortfolioId, Portfolio> {
  return Object.fromEntries(PORTFOLIO_IDS.map((id) => [id, buildPortfolio(id, score, c)])) as Record<PortfolioId, Portfolio>
}

// ---- Séries d'exemple pour les graphiques ----

function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 2 ** 32
  }
}

function gaussian(r: () => number) {
  const u = Math.max(r(), 1e-9)
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r())
}

/** Backtest mensuel simulé sur 60 mois, comparé à un 60/40. */
export function backtest(p: Portfolio, months = 60) {
  const r = rng(42)
  let value = 100
  let bench = 100
  let peak = 100
  const rows = []
  const benchW: Partial<Record<AssetClass, number>> = { actions: 0.6, obligations: 0.4 }
  for (let m = 0; m <= months; m++) {
    if (m > 0) {
      const market = gaussian(r)
      let ret = 0
      let bret = 0
      for (const k of CLASSES) {
        const { mu, sigma } = CLASS_ASSUMPTIONS[k]
        const shock = 0.6 * market + 0.8 * gaussian(r)
        const cr = mu / 12 + (sigma / Math.sqrt(12)) * shock
        ret += p.allocation[k] * cr
        bret += (benchW[k] ?? 0) * cr
      }
      value *= 1 + ret
      bench *= 1 + bret
      peak = Math.max(peak, value)
    }
    rows.push({ month: m, value: +value.toFixed(2), bench: +bench.toFixed(2), drawdown: +((value / peak - 1) * 100).toFixed(2) })
  }
  return rows
}

/** Projection sur 10 ans de 100 $ : médiane et fourchettes 50 % / 90 %. */
export function projection(m: Metrics, years = 10) {
  const { expectedReturn: mu, volatility: s } = m
  return Array.from({ length: years + 1 }, (_, t) => {
    const drift = (mu - (s * s) / 2) * t
    const spread = s * Math.sqrt(t)
    const at = (z: number) => +(100 * Math.exp(drift + z * spread)).toFixed(1)
    return { year: t, median: at(0), p25: at(-0.674), p75: at(0.674), p05: at(-1.645), p95: at(1.645) }
  })
}

/** Histogramme des rendements à 1 an (loi normale). */
export function returnDistribution(m: Metrics) {
  const rows = []
  for (let x = -40; x <= 50; x += 5) {
    const z = (x / 100 - m.expectedReturn) / m.volatility
    rows.push({ bucket: x, density: +Math.exp(-0.5 * z * z).toFixed(4), tail: x / 100 <= -m.var95 })
  }
  return rows
}

/** Contribution au risque par classe (approximation). */
export function riskContribution(p: Portfolio) {
  const parts = CLASSES.map((k) => ({ k, v: p.allocation[k] * CLASS_ASSUMPTIONS[k].sigma }))
  const sum = parts.reduce((a, b) => a + b.v, 0) || 1
  return parts.filter((x) => p.allocation[x.k] > 0).map((x) => ({ assetClass: x.k, weight: p.allocation[x.k], risk: x.v / sum }))
}
