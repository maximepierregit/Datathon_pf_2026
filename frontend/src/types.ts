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

/** Échelle unique des contraintes : Exclure (−2) … Imposer (+2). */
export type Level = -2 | -1 | 0 | 1 | 2

export type ConstraintBlock = 'classes' | 'regions' | 'themes' | 'factors'

/** « fnb » : FNB seulement. « tous » : FNB et titres individuels. */
export type Vehicles = 'fnb' | 'tous'

export type Constraints = Record<ConstraintBlock, Record<string, Level>> & {
  /** Indépendant des classes : un FNB peut détenir des actions, des obligations, de l'or… */
  vehicles: Vehicles
}

export type AssetClass = 'actions' | 'obligations' | 'immobilier' | 'or' | 'crypto' | 'liquidites'

export type PortfolioId = 'prudent' | 'equilibre' | 'conviction'

export type DashboardLevel = 'debutant' | 'intermediaire' | 'avance'

export interface Holding {
  ticker: string
  name: string
  assetClass: AssetClass
  weight: number
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

export interface Portfolio {
  id: PortfolioId
  name: string
  tagline: string
  riskScore: number
  holdings: Holding[]
  allocation: Record<AssetClass, number>
  metrics: Metrics
  warnings: string[]
  agentNotes: string[]
}

/** Portefeuille tel que l'envoie le backend ; sans nom ni accroche, on prend ceux de PORTFOLIO_META. */
export type BackendPortfolio = Omit<Portfolio, 'name' | 'tagline'> & Partial<Pick<Portfolio, 'name' | 'tagline'>>

/** Vérification du questionnaire par Pépite (`PepiteCheck` du backend), renvoyée telle quelle à la construction. */
export interface ProfileCheck {
  coherent: boolean
  summary: string
  issues: { title: string; detail: string }[]
  /** Questions de Pépite quand le profil est incohérent : les réponses du client lui reviennent à la construction. */
  questions?: string[]
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
  /** `final` : la réponse de Pépite à un message du chat. */
  | { type: 'pepite'; text: string; final?: boolean }
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
  reply: string
  changes: AdjustChange[]
  warning?: string
  /** Contraintes à appliquer si l'utilisateur accepte. */
  patch?: Partial<Constraints>
  riskShift?: number
}
