export type Objective = 'securiser' | 'fructifier' | 'viser-haut'

export interface Profile {
  age: number
  amount: number
  objective: Objective
  horizon: number
  /** 0 = je vends tout … 3 = j'investis plus */
  lossReaction: number
  /** Aisance déclarée, 1 à 5 */
  comfort: number
}

export type ContributionFrequency = 'aucune' | 'deux-semaines' | 'mensuelle' | 'annuelle'

/** Ajouts prévus. Jamais envoyé aux agents : sert seulement aux projections du tableau de bord. */
export interface Contribution {
  frequency: ContributionFrequency
  /** Montant par versement, ignoré si la fréquence est « aucune ». */
  amount: number
}

/** Échelle des facteurs : Exclure (−2) … Imposer (+2). */
export type Level = -2 | -1 | 0 | 1 | 2

/**
 * Classes, régions, thématiques : « exclure » ou un pourcentage imposé (0 à 100, à ± 2 points). Une clé absente vaut
 * neutre : libre pour les gestionnaires. Classes : % du portefeuille. Régions et thématiques : % de la part actions.
 */
export type Share = 'exclure' | number

export type ShareBlock = 'classes' | 'regions' | 'themes'

export type ConstraintBlock = ShareBlock | 'factors'

/** « fnb » : FNB seulement. « titres » : titres individuels seulement (actions et crypto). « tous » : les deux. */
export type Vehicles = 'fnb' | 'titres' | 'tous'

export type Constraints = Record<ShareBlock, Record<string, Share>> & {
  factors: Record<string, Level>
  /** Indépendant des classes : un FNB peut détenir des actions, des obligations, de l'or… */
  vehicles: Vehicles
}

export type AssetClass = 'actions' | 'obligations' | 'immobilier' | 'or' | 'crypto' | 'liquidites'

export type PortfolioId = 'prudent' | 'equilibre' | 'conviction'

export type DashboardLevel = 'debutant' | 'intermediaire' | 'avance'

/** Région d'un placement : son pays pour une action, son marché principal pour un FNB. */
export type RegionId = 'canada' | 'usa' | 'europe' | 'asie' | 'emergents' | 'mondial' | 'autres'

export interface Holding {
  ticker: string
  name: string
  assetClass: AssetClass
  weight: number
  /** Les champs suivants viennent de `holding_meta()` du backend (absents d'un ancien backend). */
  instrument?: 'action' | 'fnb' | 'crypto'
  /** Secteur d'une action, catégorie d'un FNB. */
  detail?: string
  /** Secteur GICS (en français) d'une action ou d'un FNB sectoriel ; absent pour un FNB diversifié. */
  sector?: string | null
  region?: RegionId
}

/** Indicateurs d'un backtest (`backtest.summarize()` du backend). VaR/ES : sur 12 mois glissants, en perte positive. */
export interface BacktestStats {
  annualReturn: number
  volatility: number
  sharpe: number
  maxDrawdown: number
  finalValue: number
  var95: number | null
  es95: number | null
  worst12m: number | null
  best12m: number | null
}

export interface BacktestRun {
  stats: BacktestStats
  /** Base 100 et recul depuis le dernier sommet (0 à −1, calculé jour par jour), un point par semaine. */
  series: { date: string; value: number; drawdown: number }[]
  /** Rendements sur 12 mois glissants, par tranches de 5 points (−40 … +40). `share` de 0 à 1. */
  distribution: { bucket: number; share: number; tail: boolean }[]
}

/** Backtest sur l'historique du dataset, une simulation par fréquence de rééquilibrage. */
export interface Backtest {
  start: string
  end: string
  runs: Record<ContributionFrequency, BacktestRun>
  /** Vrai pour le moteur d'exemple (rendements simulés), absent pour le backend. */
  simulated?: boolean
}

export interface Metrics {
  expectedReturn: number
  volatility: number
  worstYear: number
  fees: number
  sharpe: number
  maxDrawdown: number
  var95: number
  es95: number
}

/**
 * Une preuve chiffrée, calculée par le code et jamais par un modèle (`evidence.py` du backend). Le responsable des
 * risques en cite une à trois sous chaque mise en garde.
 */
export interface Evidence {
  /** Identifiant stable : `pire_baisse`, `crypto`, `inflation_ca`… */
  id: string
  label: string
  value: number
  unit: 'pct' | 'nombre' | 'ans'
  source: string
  /** Le repère auquel on compare : la baisse que tu acceptes, la limite par ligne, la moyenne sur 5 ans… */
  limit?: { label: string; value: number }
  /** Début et fin des données (AAAA-MM-JJ). */
  period?: [string, string]
  /** `pire_baisse` : valeur du portefeuille (base 100), par semaine. Macro : même unité que `value`, par mois. */
  series?: { date: string; value: number }[]
  /** `pire_baisse` : le sommet et le creux. */
  span?: [string, string]
}

/** Mise en garde du responsable des risques : un titre court, une ou deux phrases simples, et ses preuves. */
export interface RiskNote {
  title: string
  detail: string
  severity: 'medium' | 'high'
  /** Absent d'un ancien backend. */
  sources?: Evidence[]
  /** Moteur d'exemple : identifiants des preuves, résolus par evidenceOf() à l'affichage. */
  cites?: string[]
}

/** Identifiants des facteurs (préférences et tableau de bord). */
export type FactorId = 'taille' | 'qualite' | 'momentum' | 'value' | 'croissance'

/** Une action détenue en direct et ses scores (z-score dans son secteur : 0 = moyenne, +1 = un écart-type mieux). */
export interface ScoredStock {
  ticker: string
  name: string
  weight: number
  scores: Partial<Record<FactorId, number>>
}

/**
 * Exposition aux facteurs : moyenne des scores des actions détenues en direct, pondérée par leur poids
 * (`factors.exposures()` du backend). Les FNB et les cryptos n'ont pas de score et ne comptent pas.
 */
export interface FactorView {
  /** Part du portefeuille en actions notées, de 0 à 1. */
  coverage: number
  exposure: Partial<Record<FactorId, number>>
  /** Poids décroissant. Contribution d'une action à un facteur = poids × score / coverage. */
  stocks: ScoredStock[]
}

export interface Portfolio {
  id: PortfolioId
  name: string
  tagline: string
  riskScore: number
  holdings: Holding[]
  allocation: Record<AssetClass, number>
  metrics: Metrics
  warnings: RiskNote[]
  agentNotes: string[]
  /** Absent d'un ancien backend. */
  factors?: FactorView
  backtest?: Backtest | null
  /** Part du risque (variance) par classe : contributions d'Euler, poids × covariance avec le portefeuille ÷ variance. */
  riskContribution?: { assetClass: AssetClass; weight: number; risk: number }[] | null
}

/** Portefeuille tel que l'envoie le backend ; sans nom ni accroche, on prend ceux de PORTFOLIO_META. */
export type BackendPortfolio = Omit<Portfolio, 'name' | 'tagline' | 'warnings'> &
  Partial<Pick<Portfolio, 'name' | 'tagline'>> & {
    /** Un ancien backend envoie encore des chaînes « Titre. Détail ». */
    warnings: (RiskNote | string)[]
  }

/** Vérification du questionnaire par Pépite (`PepiteCheck` du backend), renvoyée telle quelle à la construction. */
export interface ProfileCheck {
  coherent: boolean
  summary: string
  issues: { title: string; detail: string }[]
  /** Questions de Pépite quand le profil est incohérent : les réponses du client lui reviennent à la construction. */
  questions?: string[]
  /** Pépite : ce qui a le plus pesé sur ton niveau de risque. */
  risk_explanation?: string
  /** Calculés par le code (`assess`) : S de 0 à 1 et l'aversion A donnée aux gestionnaires. */
  risk_position?: number
  risk_aversion?: number
  [field: string]: unknown
}

/** Une carte par agent : Pépite, un gestionnaire et un juge par portefeuille, le juge final (profil cohérent), le responsable des risques. */
export type AgentId = 'pepite' | `gestionnaire-${PortfolioId}` | `juge-${PortfolioId}` | 'juge-final' | 'risques'

export type AgentStatus = 'pending' | 'running' | 'done'

/**
 * Même forme que les événements SSE du backend (`backend/src/invest_agents/workflow/flow.py`).
 * `session` identifie la conversation avec Pépite : elle garde la mémoire de ses agents pour répondre ensuite.
 */
export type PipelineEvent =
  | { type: 'check'; check: ProfileCheck; session?: string }
  | { type: 'agent_status'; agent: AgentId; status: AgentStatus; message: string }
  /**
   * `final` : la réponse de Pépite à un message du chat. `ready` : elle a récapitulé un changement et demande si on
   * relance ses agents ; `request` résume ce changement.
   */
  | { type: 'pepite'; text: string; final?: boolean; ready?: boolean; request?: string }
  | { type: 'universe'; before: number; after: number }
  | { type: 'rerun'; portfolio: PortfolioId; reason: string }
  | { type: 'warning'; text: string }
  /** Profil cohérent : un seul portefeuille, le gagnant. Profil incohérent : les trois. */
  | { type: 'portfolios'; portfolios: Partial<Record<PortfolioId, BackendPortfolio>>; session?: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export interface AdjustChange {
  label: string
  before: number
  after: number
}

export interface AdjustProposal {
  /** HTML simple, rendu par RichText. */
  reply: string
  changes: AdjustChange[]
  warning?: string
  /** Contraintes à appliquer si l'utilisateur accepte. */
  patch?: Partial<Constraints>
  riskShift?: number
}

/** Ce que Pépite a fait pour répondre dans le chat : ses propres étapes et celles des agents qu'elle a sollicités. */
export interface ChatStep {
  agent: AgentId
  text: string
  done: boolean
}

export interface ChatMsg {
  from: 'user' | 'pepite' | 'info'
  text: string
  steps?: ChatStep[]
  proposal?: AdjustProposal
  request?: string
  status?: 'open' | 'applied' | 'dismissed'
  /** Pépite demande si on relance ses agents avec les changements convenus. `stale` : la conversation a continué. */
  confirm?: 'open' | 'accepted' | 'dismissed' | 'stale'
}
