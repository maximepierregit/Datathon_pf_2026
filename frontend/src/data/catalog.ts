import type { AssetClass, ConstraintBlock, ContributionFrequency, FactorId, Holding, Level, RegionId, Share, Vehicles } from '../types'

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
      { id: 'alcool-tabac', label: 'Alcool, tabac, jeux et cannabis' },
    ],
  },
  factors: {
    title: 'Des styles d’investissement à favoriser?',
    hint: 'Pour les initiés : ces « facteurs » orientent le choix des actions.',
    items: [
      { id: 'taille', label: 'Petites capitalisations', hint: 'Des entreprises plus petites, plus de croissance possible.' },
      { id: 'qualite', label: 'Qualité', hint: 'Des entreprises rentables, peu endettées.' },
      { id: 'momentum', label: 'Momentum', hint: 'Des titres qui montent depuis plusieurs mois.' },
      { id: 'value', label: 'Valeur', hint: 'Des titres jugés bon marché par rapport à leurs résultats.' },
      { id: 'croissance', label: 'Croissance', hint: 'Des entreprises dont les ventes et les profits augmentent vite.' },
    ],
  },
}

/**
 * Lecture des facteurs au tableau de bord. `low` décrit une exposition négative : « Valeur » négatif veut dire des
 * titres plutôt chers, pas un mauvais portefeuille.
 */
export const FACTOR_VIEW: Record<FactorId, { label: string; high: string; low: string; ends: [string, string] }> = {
  qualite: { label: 'Qualité', high: 'plus rentables, moins endettées', low: 'moins rentables ou plus endettées', ends: ['Fragiles', 'Solides'] },
  value: { label: 'Valeur', high: 'plutôt bon marché', low: 'plutôt chères', ends: ['Chères', 'Bon marché'] },
  momentum: { label: 'Momentum', high: 'en hausse depuis des mois', low: 'en retard sur leur groupe', ends: ['En retard', 'En hausse'] },
  croissance: { label: 'Croissance', high: 'ventes et profits en forte hausse', low: 'croissance plus lente', ends: ['Lente', 'Rapide'] },
  taille: { label: 'Petites capitalisations', high: 'plus petites entreprises', low: 'plus grandes entreprises', ends: ['Grandes', 'Petites'] },
}
export const FACTOR_IDS = Object.keys(FACTOR_VIEW) as FactorId[]

/**
 * Modèle des scores, tel que data-prep/factors_model.ipynb le calcule (voir data-prep/FACTORS.md) : chaque sous-mesure
 * est orientée « plus haut = mieux », puis les sous-mesures disponibles sont moyennées à poids égaux.
 */
export const FACTOR_MODEL: Record<FactorId, { idea: string; group: 'marche-secteur' | 'marche'; metrics: { label: string }[] }> = {
  qualite: {
    idea: 'Une entreprise rentable, peu endettée, qui transforme ses ventes en argent comptant.',
    group: 'marche-secteur',
    metrics: [
      { label: 'Rendement des actifs' },
      { label: 'Marge d’exploitation' },
      { label: 'Faible endettement' },
      { label: 'Marge de flux de trésorerie' },
    ],
  },
  value: {
    idea: 'Ce qu’on paie pour chaque dollar de bénéfices, de ventes ou d’actifs.',
    group: 'marche-secteur',
    metrics: [
      { label: 'Bénéfice prévu / prix' },
      { label: 'Valeur comptable / prix' },
      { label: 'Ventes / prix' },
      { label: 'BAIIA / valeur d’entreprise' },
    ],
  },
  momentum: {
    idea: 'Les titres qui montent ont tendance à continuer de monter quelque temps.',
    group: 'marche-secteur',
    metrics: [
      { label: 'Variation sur 12 mois' },
      { label: 'Écart à la moyenne 200 jours' },
    ],
  },
  croissance: {
    idea: 'Des ventes et des profits qui augmentent plus vite que ceux des concurrents.',
    group: 'marche-secteur',
    metrics: [
      { label: 'Croissance des revenus' },
      { label: 'Croissance des bénéfices' },
      { label: 'Croissance prévue du BPA' },
    ],
  },
  taille: {
    idea: 'Les plus petites entreprises de leur marché, souvent plus agiles et plus risquées.',
    group: 'marche',
    metrics: [{ label: 'Capitalisation boursière' }],
  },
}

/** Seuil visé par niveau (mêmes valeurs que FACTOR_LEVELS de backend/src/invest_agents/monport.py). */
export const FACTOR_TARGETS: Record<Exclude<Level, 0>, number> = { 2: 0.5, 1: 0.2, [-1]: -0.2, [-2]: -0.5 }

/** Somme des pourcentages saisis, et s'il reste un élément neutre (libre) parmi `ids`. */
export function shareTotal(values: Record<string, Share>, ids: string[]) {
  const entered = ids.map((id) => values[id]).filter((v): v is number => typeof v === 'number')
  return { total: Math.round(entered.reduce((a, b) => a + b, 0) * 10) / 10, entered: entered.length, free: ids.filter((id) => values[id] === undefined).length }
}

/** Les pourcentages d'un bloc font au plus 100 %, et exactement 100 % quand plus rien n'est libre. */
export function sharesValid(values: Record<string, Share>, ids: string[]): boolean {
  const { total, entered, free } = shareTotal(values, ids)
  return total <= 100 && (free > 0 || entered === 0 || total === 100)
}

/**
 * Un modèle de thématiques remplace tous les réglages de la page : ce qu'il ne nomme pas revient à « Neutre ».
 * IA et technologie se recoupent (NVIDIA est dans les deux) : chaque action compte dans toutes ses thématiques.
 */
export interface ThemePreset {
  id: string
  label: string
  desc: string
  values: Record<string, Share>
}

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'neutre',
    label: 'Neutre',
    desc: 'Aucune thématique imposée : les gestionnaires répartissent librement.',
    values: {},
  },
  {
    id: 'tech',
    label: 'Techno d’abord',
    desc: 'Technologie 35 % et intelligence artificielle 25 % de tes actions. Une action comme NVIDIA compte dans les deux.',
    values: { tech: 35, ia: 25 },
  },
  {
    id: 'esg',
    label: 'Responsable (ESG)',
    desc: 'Énergie propre 20 % de tes actions, sans énergies fossiles, armement, alcool, tabac ni jeux.',
    values: { 'energie-propre': 20, fossiles: 'exclure', armement: 'exclure', 'alcool-tabac': 'exclure' },
  },
  {
    id: 'defensif',
    label: 'Défensif',
    desc: 'Santé 30 % et consommation 20 % de tes actions : on en a besoin même pendant une crise.',
    values: { sante: 30, consommation: 20 },
  },
  {
    id: 'revenus',
    label: 'Revenus',
    desc: 'Banques et assurances 30 %, immobilier 15 % et énergie 10 % de tes actions (pipelines compris) : des entreprises qui versent souvent des dividendes.',
    values: { finance: 30, immobilier: 15, fossiles: 10 },
  },
]

/** Univers d'exemple : à remplacer par l'univers réel de l'équipe. */
export interface UniverseLine extends Omit<Holding, 'weight' | 'region'> {
  /** Région ciblée par la préférence du client (FNB régionaux du moteur d'exemple). */
  region?: RegionId
  /** Région affichée au tableau de bord, si elle diffère de `region`. */
  home?: RegionId
  theme?: string
  /** Seulement pour une action détenue en direct (les FNB n'ont pas de score). */
  scores?: Partial<Record<FactorId, number>>
  fee: number
}

export const UNIVERSE: UniverseLine[] = [
  { ticker: 'ACT-CA', name: 'FNB actions canadiennes', assetClass: 'actions', instrument: 'fnb', detail: 'Marchés développés', region: 'canada', fee: 0.06 },
  { ticker: 'ACT-US', name: 'FNB actions américaines', assetClass: 'actions', instrument: 'fnb', detail: 'Grandes capitalisations', region: 'usa', fee: 0.08 },
  { ticker: 'ACT-EU', name: 'FNB actions européennes', assetClass: 'actions', instrument: 'fnb', detail: 'Marchés développés', region: 'europe', fee: 0.2 },
  { ticker: 'ACT-AP', name: 'FNB actions Asie-Pacifique', assetClass: 'actions', instrument: 'fnb', detail: 'Marchés développés', region: 'asie', fee: 0.22 },
  { ticker: 'ACT-EM', name: 'FNB marchés émergents', assetClass: 'actions', instrument: 'fnb', detail: 'Marchés émergents', region: 'emergents', fee: 0.25 },
  { ticker: 'THM-TEC', name: 'FNB technologie', assetClass: 'actions', instrument: 'fnb', sector: 'Technologie', detail: 'Marchés développés · Technologie', home: 'usa', theme: 'tech', fee: 0.39 },
  { ticker: 'THM-IA', name: 'FNB intelligence artificielle', assetClass: 'actions', instrument: 'fnb', sector: 'Technologie', detail: 'Marchés développés · Technologie', home: 'mondial', theme: 'ia', fee: 0.45 },
  { ticker: 'THM-SAN', name: 'FNB santé mondiale', assetClass: 'actions', instrument: 'fnb', sector: 'Santé', detail: 'Marchés développés · Santé', home: 'mondial', theme: 'sante', fee: 0.4 },
  { ticker: 'THM-ENP', name: 'FNB énergie propre', assetClass: 'actions', instrument: 'fnb', sector: 'Énergie', detail: 'Marchés développés · Énergie', home: 'mondial', theme: 'energie-propre', fee: 0.42 },
  { ticker: 'THM-ENR', name: 'FNB énergie traditionnelle', assetClass: 'actions', instrument: 'fnb', sector: 'Énergie', detail: 'Marchés développés · Énergie', home: 'canada', theme: 'fossiles', fee: 0.35 },
  { ticker: 'THM-FIN', name: 'FNB banques canadiennes', assetClass: 'actions', instrument: 'fnb', sector: 'Services financiers', detail: 'Marchés développés · Services financiers', home: 'canada', theme: 'finance', fee: 0.3 },
  { ticker: 'THM-CON', name: 'FNB consommation', assetClass: 'actions', instrument: 'fnb', sector: 'Consommation discrétionnaire', detail: 'Marchés développés · Consommation discrétionnaire', home: 'usa', theme: 'consommation', fee: 0.35 },
  { ticker: 'THM-IND', name: 'FNB infrastructures', assetClass: 'actions', instrument: 'fnb', sector: 'Industries', detail: 'Marchés développés · Industries', home: 'mondial', theme: 'industrie', fee: 0.4 },
  // Actions détenues en direct (fictives), avec leurs scores de facteurs : seules elles en ont, comme dans l'univers réel.
  { ticker: 'TIT-BNQ', name: 'Banque Laurentides (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Services financiers', detail: 'Services financiers', home: 'canada', fee: 0, scores: { qualite: 0.6, value: 0.9, momentum: 0.2, croissance: -0.3, taille: -1.1 } },
  { ticker: 'TIT-RAI', name: 'Rail Boréal (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Industries', detail: 'Industries', home: 'canada', fee: 0, scores: { qualite: 1.2, value: -0.4, momentum: 0.5, croissance: 0.3, taille: -0.9 } },
  { ticker: 'TIT-LOG', name: 'Logiciels Nordik (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Technologie', detail: 'Technologie', home: 'canada', fee: 0, scores: { qualite: 0.9, value: -1.3, momentum: 1.1, croissance: 1.6, taille: -0.4 } },
  { ticker: 'TIT-EPI', name: 'Épiceries du Fleuve (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Consommation de base', detail: 'Consommation de base', home: 'canada', fee: 0, scores: { qualite: 0.7, value: 0.1, momentum: -0.3, croissance: -0.2, taille: 0.2 } },
  { ticker: 'TIT-MIN', name: 'Mines Abitibi (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Matériaux', detail: 'Matériaux', home: 'canada', fee: 0, scores: { qualite: -0.8, value: 1.4, momentum: -0.6, croissance: 0.4, taille: 0.9 } },
  { ticker: 'TIT-SAN', name: 'Biotech Saint-Laurent (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Santé', detail: 'Santé', home: 'canada', fee: 0, scores: { qualite: -1.1, value: -0.7, momentum: 0.8, croissance: 1.2, taille: 1.3 } },
  { ticker: 'TIT-ENE', name: 'Hydro Laurentie (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Services publics', detail: 'Services publics', home: 'canada', fee: 0, scores: { qualite: 0.4, value: 0.5, momentum: -0.1, croissance: -0.5, taille: -0.2 } },
  { ticker: 'TIT-DET', name: 'Détail Prairie (exemple)', assetClass: 'actions', instrument: 'action', sector: 'Consommation discrétionnaire', detail: 'Consommation discrétionnaire', home: 'canada', fee: 0, scores: { qualite: -0.3, value: 0.8, momentum: -0.9, croissance: -0.6, taille: 1.0 } },
  { ticker: 'OBL-GV', name: 'FNB obligations gouvernementales canadiennes', assetClass: 'obligations', instrument: 'fnb', detail: 'Obligations gouvernementales', home: 'canada', fee: 0.09 },
  { ticker: 'OBL-SO', name: 'FNB obligations de sociétés', assetClass: 'obligations', instrument: 'fnb', detail: 'Obligations de sociétés', home: 'canada', fee: 0.15 },
  { ticker: 'IMM-CA', name: 'FNB fiducies immobilières (FPI)', assetClass: 'immobilier', instrument: 'fnb', sector: 'Immobilier', detail: 'Fiducies immobilières (FPI) · Immobilier', home: 'canada', fee: 0.3 },
  { ticker: 'OR-PHY', name: 'FNB or physique', assetClass: 'or', instrument: 'fnb', detail: 'Matières premières', home: 'autres', fee: 0.2 },
  { ticker: 'CRY-BTC', name: 'FNB bitcoin', assetClass: 'crypto', instrument: 'fnb', detail: 'Actifs numériques', home: 'autres', fee: 0.4 },
  { ticker: 'CRY-ETH', name: 'FNB ether', assetClass: 'crypto', instrument: 'fnb', detail: 'Actifs numériques', home: 'autres', fee: 0.4 },
  { ticker: 'LIQ-MM', name: 'FNB marché monétaire', assetClass: 'liquidites', instrument: 'fnb', detail: 'Marché monétaire', home: 'canada', fee: 0.1 },
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

/** Régions du tableau de bord (mêmes identifiants que REGION_COUNTRIES et ETF_REGION de monport.py). */
export const REGION_LABELS: Record<RegionId, string> = {
  canada: 'Canada',
  usa: 'États-Unis',
  europe: 'Europe',
  asie: 'Asie-Pacifique',
  emergents: 'Marchés émergents',
  mondial: 'Mondial (plusieurs pays)',
  autres: 'Sans pays (or, crypto…)',
}
export const REGION_COLORS: Record<RegionId, string> = {
  canada: '#00314D',
  usa: '#1572C5',
  europe: '#7993A2',
  asie: '#8A7B64',
  emergents: '#E41C23',
  mondial: '#B9D4E9',
  autres: '#D2D2D2',
}

/** Fréquences de rééquilibrage du backtest : celles des ajouts prévus du questionnaire. */
export const REBALANCE_LABELS: Record<ContributionFrequency, string> = {
  'deux-semaines': 'Aux deux semaines',
  mensuelle: 'Chaque mois',
  annuelle: 'Chaque année',
  aucune: 'Jamais (acheter et conserver)',
}
