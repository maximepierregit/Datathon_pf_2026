import type { AssetClass, ConstraintBlock, Holding, Level, Share, Vehicles } from '../types'

export interface CatalogItem {
  id: string
  label: string
  hint?: string
}

export const LEVELS: { value: Level; label: string }[] = [
  { value: -2, label: 'Exclure' },
  { value: -1, label: 'Moins' },
  { value: 0, label: 'Neutre' },
  { value: 1, label: 'Plus' },
  { value: 2, label: 'Imposer' },
]

export const CLASS_LABELS: Record<AssetClass, string> = {
  actions: 'Actions',
  obligations: 'Obligations',
  immobilier: 'Immobilier coté',
  or: 'Or et matières premières',
  crypto: 'Crypto-actifs',
  liquidites: 'Liquidités',
}

/** Couleurs de graphique : écarts de luminosité suffisants, pas seulement de teinte. */
export const CLASS_COLORS: Record<AssetClass, string> = {
  actions: '#00314D',
  obligations: '#1572C5',
  immobilier: '#7993A2',
  or: '#8A7B64',
  crypto: '#E41C23',
  liquidites: '#D2D2D2',
}

export const CLASS_EXPLAINERS: Record<AssetClass, string> = {
  actions: 'De petits morceaux de milliers d’entreprises. Ils font grandir ton argent avec le temps.',
  obligations: 'Des prêts à des gouvernements et à des entreprises. Plus stables, ils versent des intérêts.',
  immobilier: 'Des sociétés qui possèdent des immeubles. Elles versent souvent des revenus réguliers.',
  or: 'Une valeur refuge qui ne suit pas toujours les marchés.',
  crypto: 'Très volatil : ça peut beaucoup monter… ou beaucoup baisser.',
  liquidites: 'À l’abri et disponible en tout temps. Ton coussin pour les passages difficiles.',
}

/** Classes proposées au client : jamais les liquidités ; hors FNB, il ne reste que les actions et la crypto. */
export function shownClasses(vehicles: Vehicles): AssetClass[] {
  return vehicles === 'titres' ? ['actions', 'crypto'] : ['actions', 'obligations', 'immobilier', 'or', 'crypto']
}

export const BLOCKS: Record<ConstraintBlock, { title: string; hint: string; items: CatalogItem[] }> = {
  classes: {
    title: 'Quels types de placements veux-tu dans ton portefeuille?',
    hint: 'Exclus ce que tu ne veux pas, fixe un pourcentage du portefeuille, ou laisse « Neutre » : les agents choisiront pour toi.',
    items: shownClasses('tous').map((id) => ({ id, label: CLASS_LABELS[id] })),
  },
  regions: {
    title: 'Des régions du monde à privilégier ou à éviter?',
    hint: 'Les pourcentages visent la part actions de ton portefeuille. Ce que tu laisses « Neutre » reste libre.',
    items: [
      { id: 'canada', label: 'Canada' },
      { id: 'usa', label: 'États-Unis' },
      { id: 'europe', label: 'Europe' },
      { id: 'asie', label: 'Asie-Pacifique' },
      { id: 'emergents', label: 'Marchés émergents' },
    ],
  },
  themes: {
    title: 'Des thématiques qui te tiennent à cœur… ou pas?',
    hint: 'Pars d’un modèle, puis ajuste. Les pourcentages visent la part actions de ton portefeuille.',
    items: [
      { id: 'tech', label: 'Technologie' },
      { id: 'ia', label: 'Intelligence artificielle' },
      { id: 'sante', label: 'Santé' },
      { id: 'energie-propre', label: 'Énergie propre' },
      { id: 'fossiles', label: 'Énergies fossiles' },
      { id: 'finance', label: 'Banques et assurances' },
      { id: 'immobilier', label: 'Immobilier' },
      { id: 'consommation', label: 'Consommation' },
      { id: 'industrie', label: 'Industrie et infrastructures' },
      { id: 'armement', label: 'Armement' },
      { id: 'alcool-tabac', label: 'Alcool et tabac' },
    ],
  },
  factors: {
    title: 'Des styles d’investissement à favoriser?',
    hint: 'Pour les initiés : ces « facteurs » orientent le choix des actions.',
    items: [
      { id: 'taille', label: 'Petites capitalisations', hint: 'Des entreprises plus petites, plus de croissance possible.' },
      { id: 'qualite', label: 'Qualité', hint: 'Des entreprises rentables, peu endettées.' },
      { id: 'momentum', label: 'Momentum', hint: 'Des titres qui montent depuis plusieurs mois.' },
      { id: 'value', label: 'Value', hint: 'Des titres jugés bon marché par rapport à leurs résultats.' },
    ],
  },
}

/** Somme des pourcentages saisis, et s'il reste un élément neutre (libre) parmi `ids`. */
export function shareTotal(values: Record<string, Share>, ids: string[]) {
  const entered = ids.map((id) => values[id]).filter((v): v is number => typeof v === 'number')
  return { total: entered.reduce((a, b) => a + b, 0), entered: entered.length, free: ids.filter((id) => values[id] === undefined).length }
}

/** Les pourcentages d'un bloc font au plus 100 %, et exactement 100 % quand plus rien n'est libre. */
export function sharesValid(values: Record<string, Share>, ids: string[]): boolean {
  const { total, entered, free } = shareTotal(values, ids)
  return total <= 100 && (free > 0 || entered === 0 || total === 100)
}

/** Parts égales et entières qui font 100 : les premiers reçoivent le reste de la division. */
function equalShares(ids: string[]): Record<string, number> {
  const base = Math.floor(100 / ids.length)
  return Object.fromEntries(ids.map((id, i) => [id, base + (i < 100 - base * ids.length ? 1 : 0)]))
}

export interface ThemePreset {
  id: string
  label: string
  desc: string
  /** Les thématiques après le choix du modèle ; les exclusions déjà faites sont gardées. */
  apply: (current: Record<string, Share>) => Record<string, Share>
}

const exclusions = (current: Record<string, Share>) => Object.fromEntries(Object.entries(current).filter(([, v]) => v === 'exclure'))

const keep = (current: Record<string, Share>, values: Record<string, Share>) => ({
  ...Object.fromEntries(Object.entries(exclusions(current)).filter(([id]) => !(id in values))),
  ...values,
})

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'neutre',
    label: 'Neutre',
    desc: 'Toutes les thématiques que tu n’exclus pas, à parts égales.',
    apply: (current) => {
      const ids = BLOCKS.themes.items.map((t) => t.id).filter((id) => current[id] !== 'exclure')
      return { ...exclusions(current), ...(ids.length ? equalShares(ids) : {}) }
    },
  },
  {
    id: 'tech',
    label: 'Techno d’abord',
    desc: '45 % en technologie, le reste libre.',
    apply: (current) => keep(current, { tech: 45 }),
  },
  {
    id: 'esg',
    label: 'Responsable (ESG)',
    desc: 'Sans énergies fossiles, armement ni alcool et tabac.',
    apply: (current) => keep(current, { fossiles: 'exclure', armement: 'exclure', 'alcool-tabac': 'exclure' }),
  },
  {
    id: 'defensif',
    label: 'Défensif',
    desc: 'Santé et consommation, 25 % chacune : des secteurs qui résistent mieux aux crises.',
    apply: (current) => keep(current, { sante: 25, consommation: 25 }),
  },
  {
    id: 'revenus',
    label: 'Revenus',
    desc: 'Banques et assurances 30 %, immobilier 15 % : des entreprises qui versent souvent des dividendes.',
    apply: (current) => keep(current, { finance: 30, immobilier: 15 }),
  },
]

/** Univers d'exemple : à remplacer par l'univers réel de l'équipe. */
export interface UniverseLine extends Omit<Holding, 'weight'> {
  region?: string
  theme?: string
  factor?: string
  fee: number
}

export const UNIVERSE: UniverseLine[] = [
  { ticker: 'ACT-CA', name: 'FNB actions canadiennes', assetClass: 'actions', region: 'canada', fee: 0.06 },
  { ticker: 'ACT-US', name: 'FNB actions américaines', assetClass: 'actions', region: 'usa', fee: 0.08 },
  { ticker: 'ACT-EU', name: 'FNB actions européennes', assetClass: 'actions', region: 'europe', fee: 0.2 },
  { ticker: 'ACT-AP', name: 'FNB actions Asie-Pacifique', assetClass: 'actions', region: 'asie', fee: 0.22 },
  { ticker: 'ACT-EM', name: 'FNB marchés émergents', assetClass: 'actions', region: 'emergents', fee: 0.25 },
  { ticker: 'THM-TEC', name: 'FNB technologie', assetClass: 'actions', theme: 'tech', fee: 0.39 },
  { ticker: 'THM-IA', name: 'FNB intelligence artificielle', assetClass: 'actions', theme: 'ia', fee: 0.45 },
  { ticker: 'THM-SAN', name: 'FNB santé mondiale', assetClass: 'actions', theme: 'sante', fee: 0.4 },
  { ticker: 'THM-ENP', name: 'FNB énergie propre', assetClass: 'actions', theme: 'energie-propre', fee: 0.42 },
  { ticker: 'THM-ENR', name: 'FNB énergie traditionnelle', assetClass: 'actions', theme: 'fossiles', fee: 0.35 },
  { ticker: 'THM-FIN', name: 'FNB banques canadiennes', assetClass: 'actions', theme: 'finance', fee: 0.3 },
  { ticker: 'THM-CON', name: 'FNB consommation', assetClass: 'actions', theme: 'consommation', fee: 0.35 },
  { ticker: 'THM-IND', name: 'FNB infrastructures', assetClass: 'actions', theme: 'industrie', fee: 0.4 },
  { ticker: 'FAC-PC', name: 'FNB petites capitalisations', assetClass: 'actions', factor: 'taille', fee: 0.3 },
  { ticker: 'FAC-QL', name: 'FNB qualité', assetClass: 'actions', factor: 'qualite', fee: 0.25 },
  { ticker: 'FAC-MO', name: 'FNB momentum', assetClass: 'actions', factor: 'momentum', fee: 0.28 },
  { ticker: 'FAC-VA', name: 'FNB value', assetClass: 'actions', factor: 'value', fee: 0.25 },
  { ticker: 'OBL-GV', name: 'FNB obligations gouvernementales canadiennes', assetClass: 'obligations', fee: 0.09 },
  { ticker: 'OBL-SO', name: 'FNB obligations de sociétés', assetClass: 'obligations', fee: 0.15 },
  { ticker: 'IMM-CA', name: 'FNB fiducies immobilières (FPI)', assetClass: 'immobilier', fee: 0.3 },
  { ticker: 'OR-PHY', name: 'FNB or physique', assetClass: 'or', fee: 0.2 },
  { ticker: 'CRY-BTC', name: 'FNB bitcoin', assetClass: 'crypto', fee: 0.4 },
  { ticker: 'CRY-ETH', name: 'FNB ether', assetClass: 'crypto', fee: 0.4 },
  { ticker: 'LIQ-MM', name: 'FNB marché monétaire', assetClass: 'liquidites', fee: 0.1 },
]

/** Hypothèses par classe (rendement, volatilité annuels) pour les données d'exemple. */
export const CLASS_ASSUMPTIONS: Record<AssetClass, { mu: number; sigma: number }> = {
  actions: { mu: 0.07, sigma: 0.16 },
  obligations: { mu: 0.035, sigma: 0.06 },
  immobilier: { mu: 0.055, sigma: 0.18 },
  or: { mu: 0.04, sigma: 0.15 },
  crypto: { mu: 0.15, sigma: 0.7 },
  liquidites: { mu: 0.025, sigma: 0.01 },
}
