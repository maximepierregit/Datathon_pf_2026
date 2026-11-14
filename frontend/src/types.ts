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

/** Échelle unique des contraintes : Exclure (−2) … Imposer (+2). */
export type Level = -2 | -1 | 0 | 1 | 2

export type ConstraintBlock = 'classes' | 'regions' | 'themes' | 'factors'

export type Constraints = Record<ConstraintBlock, Record<string, Level>>

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

export type AgentId = 'eclaireur' | 'compositeur' | 'verificateur'

export type AgentStatus = 'pending' | 'running' | 'done'

/** Même forme que les futurs événements SSE du backend Strands. */
export type PipelineEvent =
  | { type: 'agent_status'; agent: AgentId; status: AgentStatus; message: string }
  | { type: 'pepite'; text: string }
  | { type: 'universe'; before: number; after: number }
  | { type: 'rerun'; portfolio: PortfolioId; reason: string }
  | { type: 'warning'; text: string }
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
