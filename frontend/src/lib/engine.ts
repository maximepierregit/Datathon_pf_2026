// Moteur d'exemple côté front : il imite ce que feront les agents Strands et l'optimiseur Python,
// pour que l'interface fonctionne avant le branchement du backend.
import { CLASS_ASSUMPTIONS, CLASS_LABELS, BLOCKS, UNIVERSE, type UniverseLine } from '../data/catalog'
import type { AssetClass, ConstraintBlock, Constraints, Holding, Level, Metrics, Portfolio, PortfolioId, Profile, RiskNote } from '../types'

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

/** S, de 0 (très prudent) à 1 (très audacieux) : capacité (horizon, âge) et tolérance (baisse, objectif, aisance). */
export function riskPosition(p: Profile): number {
  const capacity = 0.6 * clamp((Math.min(p.horizon, 20) - 1) / 19, 0, 1) + 0.4 * clamp((75 - p.age) / 50, 0, 1)
  const tolerance = 0.5 * clamp(p.lossReaction / 3, 0, 1) + 0.3 * OBJECTIVE_TOLERANCE[p.objective] + 0.2 * clamp((p.comfort - 1) / 4, 0, 1)
  // La tolérance ne dépasse pas la capacité de plus de 3 crans sur 24.
  return clamp(Math.min((capacity + tolerance) / 2, capacity + 0.125), 0, 1)
}

/** Score de risque 5–95 tiré du profil. */
export function riskScore(p: Profile): number {
  return Math.round(5 + 90 * riskPosition(p))
}

export function riskLabel(score: number): string {
  return RISK_LABELS[Math.min(4, Math.floor(clamp((score - 5) / 90, 0, 1) / 0.2))]
}

const level = (c: Constraints, block: ConstraintBlock, id: string): Level => c[block][id] ?? 0

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
  // L'univers d'exemple ne contient que des FNB : rien à retirer ici, l'univers réel écartera les titres individuels.
  if (c.vehicles === 'fnb') notes.push('FNB seulement : aucun titre individuel, chaque classe passe par un FNB.')

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

/** Alertes de cohérence profil ↔ contraintes (le backend les confie au responsable des risques). */
export function coherenceWarnings(score: number, c: Constraints): RiskNote[] {
  const w: RiskNote[] = []
  const crypto = level(c, 'classes', 'crypto')
  const actions = level(c, 'classes', 'actions')
  if (score < 40 && crypto >= 1)
    w.push({ title: 'Crypto et prudence font mauvais ménage', detail: 'Tu cherches de la stabilité, mais tu veux plus de crypto. La crypto peut perdre la moitié de sa valeur en quelques mois.', severity: 'high' })
  if (score < 40 && actions === 2)
    w.push({ title: 'Beaucoup d’actions pour un profil prudent', detail: 'Avec autant d’actions, tu pourrais vivre des baisses difficiles à supporter.', severity: 'medium' })
  if (score > 65 && actions <= -1)
    w.push({ title: 'Peu d’actions pour ton horizon', detail: 'Ton profil est dynamique, mais tu limites les actions : ton argent risque de moins grandir.', severity: 'medium' })
  const kept = CLASSES.filter((k) => level(c, 'classes', k) !== -2)
  if (kept.length === 1)
    w.push({ title: 'Un seul type de placement', detail: `Tu n’as gardé que les ${CLASS_LABELS[kept[0]].toLowerCase()} : ton portefeuille sera très peu diversifié.`, severity: 'medium' })
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
    // Le moteur applique toujours la limite de 40 % : le juge n'a rien à redire.
    agentNotes: [...notes, 'Le juge confirme que ce portefeuille respecte tes limites.'],
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
