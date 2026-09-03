export type Environment = "development" | "competition"
export type RunMode = "BACKTEST" | "DEVELOPMENT_PAPER" | "COMPETITION_PAPER"

export interface EvidenceItem {
  label: string
  value: string
  provenance: string
  state: "verified" | "warning" | "missing"
}

export interface ForecastNode {
  returnValue: string
  probability: number
}

export interface CaseData {
  caseId: string
  /** Raw ledger state retained so safety UI can fail closed on unknown values. */
  caseState?: string
  tradingDate: string
  decisionWindow: "10:05" | "13:05"
  underlying: string
  verdict: "PENDING" | "ABSTAIN" | "CERTIFIED" | "HALTED" | "WORKING" | "PARTIAL" | "MANAGING" | "CLOSED" | "UNKNOWN"
  verdictReason: string
  reasonCodes: string[]
  environment: Environment
  mode: RunMode
  asOf: string
  evidence: EvidenceItem[]
  forecast: { nodes: ForecastNode[]; artifactHash: string }
  certificate?: {
    status: "issued" | "not-issued"
    policyVersion: string
    proposalHash?: string
    expiresAt?: string
    maxLoss?: string
    robustEv?: string
  }
  orderLifecycle: Array<{
    label: string
    state: "complete" | "current" | "pending" | "blocked"
    detail: string
  }>
  performance: {
    realizedPnl: string
    totalReturn: string
    drawdown: string
    provenance: string
  }
}

export interface PerformanceData {
  environment: Environment
  mode: RunMode
  asOf: string
  provenance: string
  metrics: Record<string, string>
}

export interface CaseProjection {
  case_id: string
  trading_date: string
  decision_window: "10:05" | "13:05"
  state: string
  underlying: string | null
  reason_codes: string[]
  artifacts: Record<string, unknown>
  as_of: string | null
  environment: Environment
  mode: RunMode
}

export interface ResearchSummaryData { environment: Environment; asOf: string; provenance: string; gate: string; metrics: Record<string, unknown> }
export interface ReadResult<T> { data: T; source: "public_api" | "archived_fixture"; notice?: string }

/**
 * Live account/positions/orders reads have no archived fixture: when the API
 * is down the UI must say "unavailable" instead of showing invented numbers.
 */
export type LiveReadResult<T> =
  | { status: "ok"; data: T }
  | { status: "unavailable"; reason: string }
  | { status: "unconfigured"; reason: string }

export interface AccountData {
  status: string
  equity: string
  lastEquity: string
  dailyPnl: string
  competitionDrawdown: string
  buyingPower: string
  optionsLevel: number | null
  paperEndpoint: boolean
}

export interface PositionRow {
  symbol: string
  quantity: number
  side: string
  unrealizedPnl: string | null
}

export interface OrderRow {
  orderId: string
  status: string
  filledQuantity: number
  averageFillPrice: string | null
  clientOrderId: string | null
}

export interface EquityPoint {
  recordedAt: string
  equity: number
  dailyPnl: number
  competitionDrawdown: number
}

export type ControlAction = "pause" | "resume" | "emergency-stop"

export type ControlResult =
  | { ok: true; message: string }
  | { ok: false; kind: "unauthorized" | "unconfigured" | "failed"; message: string }
