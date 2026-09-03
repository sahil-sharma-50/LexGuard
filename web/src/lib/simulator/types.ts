export type ScenarioId = "guided-certifiable-v1" | "guided-catalyst-veto-v1"

export type Lifecycle =
  | "observing"
  | "forecasted"
  | "argued"
  | "awaiting_supervision"
  | "vetoed"
  | "certified"
  | "simulated_submitted"
  | "simulated_working"
  | "simulated_filled"
  | "reconciliation_required"
  | "reconciled"
  | "closing"
  | "closed"
  | "broker_unknown"

export type DemoActor = "PUBLIC_DEMO_USER" | "SIMULATOR"

export type DemoActionType =
  | "ADVANCE_EVIDENCE"
  | "COMPLETE_FORECAST"
  | "COMPLETE_ARGUMENT"
  | "REQUEST_SUPERVISION"
  | "APPROVE_PROPOSAL"
  | "VETO_PROPOSAL"
  | "SIMULATE_SUBMIT"
  | "SIMULATE_WORKING"
  | "SIMULATE_FILL"
  | "PAUSE_SCHEDULER"
  | "RESUME_SCHEDULER"
  | "TRIGGER_RECONCILIATION"
  | "RESOLVE_RECONCILIATION"
  | "FAIL_RECONCILIATION"
  | "CLOSE_POSITION"
  | "COMPLETE_CLOSE"
  | "EMERGENCY_STOP"
  | "RESET_SCENARIO"

export interface DemoAction {
  type: DemoActionType
  actor?: DemoActor
  confirmed?: boolean
}

export type OptionRight = "PUT" | "CALL"
export type LegSide = "LONG" | "SHORT"

export interface DemoLeg {
  symbol: string
  side: LegSide
  quantity: number
  strike: number
  right: OptionRight
  expiration: string
}

export interface DemoStructure {
  ratio: number
  quantity: number
  netCredit: number
  netCreditDollars: number
  wingWidth: number
  legs: readonly DemoLeg[]
}

export type EvidenceLabel =
  | "MARKET_CLOCK"
  | "QUOTE_PROVENANCE"
  | "UNDERLYING_REFERENCE"
  | "EVENT_WINDOW"
  | "RISK_BUDGET"

export interface DemoEvidenceItem {
  label: EvidenceLabel
  value: string | number
  freshness?: "FRESH"
  ageSeconds?: number
}

export interface ForecastNode {
  returnValue: string
  probability: number
}

export interface DemoRationale {
  thesis: string
  supportingEvidence: string
  counterevidence: string
  uncertainty: string
  recommendation: "BASE" | "VETO"
}

export interface DemoForecast {
  nodes: readonly ForecastNode[]
  rationale: DemoRationale
}

export type DemoArgument = "BASE" | "VETO"

export interface DemoRiskGate {
  equalRatio: boolean
  sameExpiration: boolean
  coveredLegs: boolean
  quoteProvenance: "SYNTHETIC_OPRA_PRESENT"
  evidenceFreshness: "FRESH"
  maxLoss: number
  lossCap: number
  output: "PASS" | "NOT_EVALUATED"
}

export interface DemoCandidate extends DemoStructure {
  symbol: string
  referencePrice: number
  expiration: string
  dte: number
  maxLoss: number
}

export interface DemoCertificate {
  idTemplate: string
  policy: "risk-constitution.v1"
  issuedAtSequence: number
  verdict: "CERTIFIED"
  maxLoss: number
  candidateDigest: string
}

export interface DemoOrder {
  idTemplate: string
  limitCredit: number
  quantity: number
  timeInForce: "DAY"
}

export interface DemoFill {
  credit: number
  legs: readonly DemoLeg[]
}

export interface DemoBrokerSnapshot {
  legs: readonly DemoLeg[]
}

export interface DemoReconciliation {
  localOrderState: "SIMULATED_FILLED"
  brokerSnapshot: DemoBrokerSnapshot
  correctedLeg: DemoLeg
  result: "RECONCILED"
}

export interface DemoClose {
  idTemplate: string
  legs: readonly DemoLeg[]
  lifecycle: "CLOSED"
  pnl: null
}

export interface DemoFixture {
  scenarioId: ScenarioId
  seed: string
  evaluationTime: string
  symbol: string
  referencePrice: number
  expiration: string
  dte: number
  structure: DemoStructure
  evidence: readonly DemoEvidenceItem[]
  forecast: DemoForecast
  argument: DemoArgument
  riskGate: DemoRiskGate
  candidate: DemoCandidate | null
  certificate: DemoCertificate | null
  order: DemoOrder | null
  fill: DemoFill | null
  reconciliation: DemoReconciliation | null
  close: DemoClose | null
}

export type SchedulerStatus = "running" | "paused"

export interface AuditEvent {
  sequence: number
  timestamp: string
  action: DemoActionType
  priorState: Lifecycle
  resultingState: Lifecycle
  actor: DemoActor
  summary: string
  outcome: "ACCEPTED" | "REJECTED"
  details?: Readonly<Record<string, string | number | boolean | null>>
}

export interface DemoRun {
  runId: string
  scenarioId: ScenarioId
  seed: string
  lifecycle: Lifecycle
  evidenceCursor: number
  forecast: DemoForecast | null
  argument: DemoArgument | null
  riskGate: DemoRiskGate | null
  candidate: DemoCandidate | null
  certificate: DemoCertificate | null
  order: DemoOrder | null
  fill: DemoFill | null
  reconciliation: DemoReconciliation | null
  close: DemoClose | null
  schedulerStatus: SchedulerStatus
  emergencyStop: boolean
  auditEvents: readonly AuditEvent[]
  lastUpdatedSequence: number
}

export interface DemoEnvelope {
  schemaVersion: 1
  nextRunNumber: number
  activeRun: DemoRun | null
  runHistory: readonly DemoRun[]
}
