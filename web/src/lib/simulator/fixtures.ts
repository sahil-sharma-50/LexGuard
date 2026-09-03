import type {
  DemoEnvelope,
  DemoFixture,
  DemoLeg,
  DemoRun,
  ScenarioId,
} from "./types"

const CERTIFIABLE_LEGS = [
  { symbol: "SPY", side: "LONG", quantity: 1, strike: 640, right: "PUT", expiration: "2026-09-02" },
  { symbol: "SPY", side: "SHORT", quantity: 1, strike: 645, right: "PUT", expiration: "2026-09-02" },
  { symbol: "SPY", side: "SHORT", quantity: 1, strike: 655, right: "CALL", expiration: "2026-09-02" },
  { symbol: "SPY", side: "LONG", quantity: 1, strike: 660, right: "CALL", expiration: "2026-09-02" },
] as const satisfies readonly DemoLeg[]

const CERTIFIABLE_STRUCTURE = {
  ratio: 1,
  quantity: 1,
  netCredit: 1.9,
  netCreditDollars: 190,
  wingWidth: 5,
  legs: CERTIFIABLE_LEGS,
} as const

const CERTIFIABLE_EVIDENCE = [
  { label: "MARKET_CLOCK", value: "2026-08-31T14:00:00Z", freshness: "FRESH" },
  { label: "QUOTE_PROVENANCE", value: "SYNTHETIC_OPRA_PRESENT", ageSeconds: 0 },
  { label: "UNDERLYING_REFERENCE", value: 650 },
  { label: "EVENT_WINDOW", value: "CLEAR" },
  { label: "RISK_BUDGET", value: 1000 },
] as const

const CERTIFIABLE_FORECAST = {
  nodes: [
    { returnValue: "-2.0%", probability: 0.06 },
    { returnValue: "-1.0%", probability: 0.16 },
    { returnValue: "-0.4%", probability: 0.2 },
    { returnValue: "0.0%", probability: 0.18 },
    { returnValue: "+0.4%", probability: 0.18 },
    { returnValue: "+1.0%", probability: 0.15 },
    { returnValue: "+2.0%", probability: 0.07 },
  ],
  rationale: {
    thesis: "Range probability dominates the synthetic two-day window",
    supportingEvidence: "87% authored mass lies between -1.0% and +1.0% inclusive",
    counterevidence: "13% authored tail mass lies at ±2.0%",
    uncertainty: "This is a fixed teaching distribution, not a forecast of a real market",
    recommendation: "BASE",
  },
} as const

const CERTIFIABLE_RISK_GATE = {
  equalRatio: true,
  sameExpiration: true,
  coveredLegs: true,
  quoteProvenance: "SYNTHETIC_OPRA_PRESENT",
  evidenceFreshness: "FRESH",
  maxLoss: 310,
  lossCap: 1000,
  output: "PASS",
} as const

const CERTIFIABLE_CANDIDATE = {
  symbol: "SPY",
  referencePrice: 650,
  expiration: "2026-09-02",
  dte: 2,
  ratio: 1,
  quantity: 1,
  netCredit: 1.9,
  netCreditDollars: 190,
  wingWidth: 5,
  maxLoss: 310,
  legs: CERTIFIABLE_LEGS,
} as const

const CERTIFIABLE_CERTIFICATE = {
  idTemplate: "cert-<run-id>-001",
  policy: "risk-constitution.v1",
  issuedAtSequence: 9,
  verdict: "CERTIFIED",
  maxLoss: 310,
  candidateDigest: "sha256:93c52a7a0e0fc2f61dab37924e47bf4084b902011d00930215e8fdc20389a601",
} as const

const CERTIFIABLE_ORDER = {
  idTemplate: "sim-<run-id>-ord-001",
  limitCredit: 1.9,
  quantity: 1,
  timeInForce: "DAY",
} as const

const CERTIFIABLE_FILL = {
  credit: 1.9,
  legs: CERTIFIABLE_LEGS,
} as const

const CERTIFIABLE_BROKER_LEGS = [
  { symbol: "SPY", side: "LONG", quantity: 1, strike: 640, right: "PUT", expiration: "2026-09-02" },
  { symbol: "SPY", side: "SHORT", quantity: 1, strike: 645, right: "PUT", expiration: "2026-09-02" },
  { symbol: "SPY", side: "SHORT", quantity: 0, strike: 655, right: "CALL", expiration: "2026-09-02" },
  { symbol: "SPY", side: "LONG", quantity: 1, strike: 660, right: "CALL", expiration: "2026-09-02" },
] as const satisfies readonly DemoLeg[]

const CERTIFIABLE_RECONCILIATION = {
  localOrderState: "SIMULATED_FILLED",
  brokerSnapshot: { legs: CERTIFIABLE_BROKER_LEGS },
  correctedLeg: { symbol: "SPY", side: "SHORT", quantity: 1, strike: 655, right: "CALL", expiration: "2026-09-02" },
  result: "RECONCILED",
} as const

const CERTIFIABLE_CLOSE = {
  idTemplate: "sim-<run-id>-close-001",
  legs: [
    { symbol: "SPY", side: "LONG", quantity: 0, strike: 640, right: "PUT", expiration: "2026-09-02" },
    { symbol: "SPY", side: "SHORT", quantity: 0, strike: 645, right: "PUT", expiration: "2026-09-02" },
    { symbol: "SPY", side: "SHORT", quantity: 0, strike: 655, right: "CALL", expiration: "2026-09-02" },
    { symbol: "SPY", side: "LONG", quantity: 0, strike: 660, right: "CALL", expiration: "2026-09-02" },
  ],
  lifecycle: "CLOSED",
  pnl: null,
} as const

export const CERTIFIABLE_FIXTURE = {
  scenarioId: "guided-certifiable-v1",
  seed: "vc-guided-certifiable-v1-seed",
  evaluationTime: "2026-08-31T14:00:00Z",
  symbol: "SPY",
  referencePrice: 650,
  expiration: "2026-09-02",
  dte: 2,
  structure: CERTIFIABLE_STRUCTURE,
  evidence: CERTIFIABLE_EVIDENCE,
  forecast: CERTIFIABLE_FORECAST,
  argument: "BASE",
  riskGate: CERTIFIABLE_RISK_GATE,
  candidate: CERTIFIABLE_CANDIDATE,
  certificate: CERTIFIABLE_CERTIFICATE,
  order: CERTIFIABLE_ORDER,
  fill: CERTIFIABLE_FILL,
  reconciliation: CERTIFIABLE_RECONCILIATION,
  close: CERTIFIABLE_CLOSE,
} as const satisfies DemoFixture

export const CATALYST_VETO_FIXTURE = {
  scenarioId: "guided-catalyst-veto-v1",
  seed: "vc-guided-catalyst-veto-v1-seed",
  evaluationTime: "2026-08-31T14:00:00Z",
  symbol: "SPY",
  referencePrice: 650,
  expiration: "2026-09-02",
  dte: 2,
  structure: CERTIFIABLE_STRUCTURE,
  evidence: [
    { label: "MARKET_CLOCK", value: "2026-08-31T14:00:00Z", freshness: "FRESH" },
    { label: "QUOTE_PROVENANCE", value: "SYNTHETIC_OPRA_PRESENT", ageSeconds: 0 },
    { label: "UNDERLYING_REFERENCE", value: 650 },
    { label: "EVENT_WINDOW", value: "SYNTHETIC_HIGH_IMPACT_EVENT_IN_45_MINUTES" },
    { label: "RISK_BUDGET", value: 1000 },
  ],
  forecast: {
    nodes: CERTIFIABLE_FORECAST.nodes,
    rationale: {
      thesis: "The authored event window makes entry indefensible",
      supportingEvidence: "Synthetic high-impact event occurs in 45 minutes",
      counterevidence: "The fixed distribution otherwise supports BASE",
      uncertainty: "Event direction and repricing are intentionally unknown",
      recommendation: "VETO",
    },
  },
  argument: "VETO",
  riskGate: {
    ...CERTIFIABLE_RISK_GATE,
    output: "NOT_EVALUATED",
  },
  candidate: null,
  certificate: null,
  order: null,
  fill: null,
  reconciliation: null,
  close: null,
} as const satisfies DemoFixture

export const SIMULATOR_FIXTURES = {
  "guided-certifiable-v1": CERTIFIABLE_FIXTURE,
  "guided-catalyst-veto-v1": CATALYST_VETO_FIXTURE,
} as const satisfies Record<ScenarioId, DemoFixture>

export function getFixture(scenarioId: ScenarioId): DemoFixture {
  return SIMULATOR_FIXTURES[scenarioId]
}

export function createRun(fixture: DemoFixture, runNumber: number): DemoRun {
  return {
    runId: `run-${String(runNumber).padStart(4, "0")}`,
    scenarioId: fixture.scenarioId,
    seed: fixture.seed,
    lifecycle: "observing",
    evidenceCursor: 0,
    forecast: null,
    argument: null,
    riskGate: null,
    candidate: null,
    certificate: null,
    order: null,
    fill: null,
    reconciliation: null,
    close: null,
    schedulerStatus: "running",
    emergencyStop: false,
    auditEvents: [],
    lastUpdatedSequence: 0,
  }
}

export function createAuthoredSeed(): DemoEnvelope {
  return {
    schemaVersion: 1,
    nextRunNumber: 2,
    activeRun: createRun(CERTIFIABLE_FIXTURE, 1),
    runHistory: [],
  }
}
