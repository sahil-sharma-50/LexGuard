import { createAuthoredSeed, getFixture } from "./fixtures"
import type {
  AuditEvent,
  DemoArgument,
  DemoCertificate,
  DemoClose,
  DemoEnvelope,
  DemoEvidenceItem,
  DemoFill,
  DemoForecast,
  DemoLeg,
  DemoOrder,
  DemoRationale,
  DemoReconciliation,
  DemoRiskGate,
  DemoRun,
  DemoStructure,
  Lifecycle,
  ScenarioId,
} from "./types"

export const DEMO_STORAGE_KEY = "lexguard:demo:v1"
export const DEMO_SCHEMA_VERSION = 1 as const

export const PERSISTENCE_UNAVAILABLE_NOTICE = "Persistence unavailable: progress lasts only in this tab."
export const PERSISTENCE_RESET_NOTICE = "Saved demo data was invalid or unsupported and has been reset to the authored seed. Continue with the guided scenario."

export interface DemoPersistence {
  load(): { state: DemoEnvelope; notice?: string; persistent: boolean }
  save(state: DemoEnvelope): { persistent: boolean; notice?: string }
  clear(): void
  getNotice?(): string | undefined
}

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export interface DeserializedEnvelope {
  state: DemoEnvelope
  notice?: string
  persistent: boolean
}

export function serializeEnvelope(state: DemoEnvelope): string {
  if (!isDemoEnvelope(state)) {
    throw new TypeError("Cannot serialize an invalid simulator envelope")
  }
  return JSON.stringify(state)
}

export function deserializeEnvelope(raw: string | null | undefined): DeserializedEnvelope {
  if (raw === null || raw === undefined || raw.trim() === "") {
    return { state: createAuthoredSeed(), persistent: true }
  }

  try {
    const parsed: unknown = JSON.parse(raw)
    if (isDemoEnvelope(parsed)) {
      return { state: parsed, persistent: true }
    }
  } catch {
    // Invalid JSON is handled by the authored reset below.
  }

  return {
    state: createAuthoredSeed(),
    persistent: true,
    notice: PERSISTENCE_RESET_NOTICE,
  }
}

export function createPersistence(storage?: StorageLike | null): DemoPersistence {
  let activeStorage: StorageLike | null = storage === undefined ? detectStorage() : storage
  let memoryValue: string | null = null
  let persistent = activeStorage !== null
  let persistenceNotice: string | undefined

  const switchToMemory = (): void => {
    activeStorage = null
    persistent = false
  }

  return {
    load(): DeserializedEnvelope {
      if (activeStorage === null) {
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
        const result = deserializeEnvelope(memoryValue)
        return { ...result, persistent: false, notice: PERSISTENCE_UNAVAILABLE_NOTICE }
      }

      try {
        const result = deserializeEnvelope(activeStorage.getItem(DEMO_STORAGE_KEY))
        persistenceNotice = result.notice
        return { ...result, persistent }
      } catch {
        switchToMemory()
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
        return {
          state: createAuthoredSeed(),
          persistent: false,
          notice: PERSISTENCE_UNAVAILABLE_NOTICE,
        }
      }
    },

    save(state: DemoEnvelope): { persistent: boolean; notice?: string } {
      let serialized: string
      try {
        serialized = serializeEnvelope(state)
      } catch {
        persistenceNotice = PERSISTENCE_RESET_NOTICE
        return { persistent, notice: PERSISTENCE_RESET_NOTICE }
      }

      if (activeStorage === null) {
        memoryValue = serialized
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
        return { persistent: false, notice: PERSISTENCE_UNAVAILABLE_NOTICE }
      }

      try {
        activeStorage.setItem(DEMO_STORAGE_KEY, serialized)
        persistenceNotice = undefined
        return { persistent: true }
      } catch {
        switchToMemory()
        memoryValue = serialized
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
        return { persistent: false, notice: PERSISTENCE_UNAVAILABLE_NOTICE }
      }
    },

    clear(): void {
      memoryValue = null
      if (activeStorage === null) {
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
        return
      }
      try {
        activeStorage.removeItem(DEMO_STORAGE_KEY)
        persistenceNotice = undefined
      } catch {
        switchToMemory()
        persistenceNotice = PERSISTENCE_UNAVAILABLE_NOTICE
      }
    },

    getNotice(): string | undefined {
      return persistenceNotice
    },
  }
}

function detectStorage(): StorageLike | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function isDemoEnvelope(value: unknown): value is DemoEnvelope {
  if (!isRecord(value)) return false
  if (
    value.schemaVersion === DEMO_SCHEMA_VERSION &&
    isIntegerAtLeast(value.nextRunNumber, 1) &&
    (value.activeRun === null || isDemoRun(value.activeRun)) &&
    isArray(value.runHistory) &&
    value.runHistory.length <= 20 &&
    value.runHistory.every(isDemoRun)
  ) {
    const activeRun = value.activeRun as DemoRun | null
    const runHistory = value.runHistory as readonly DemoRun[]
    return (
      (activeRun === null || !isTerminalLifecycle(activeRun.lifecycle)) &&
      runHistory.every((run) => isTerminalLifecycle(run.lifecycle)) &&
      isRunNumberingConsistent(activeRun, runHistory, value.nextRunNumber)
    )
  }
  return false
}

function isDemoRun(value: unknown): value is DemoRun {
  if (!isRecord(value)) return false
  if (!(
    isNonEmptyString(value.runId) &&
    isScenarioId(value.scenarioId) &&
    isNonEmptyString(value.seed) &&
    isLifecycle(value.lifecycle) &&
    isIntegerAtLeast(value.evidenceCursor, 0) &&
    value.evidenceCursor <= getFixture(value.scenarioId).evidence.length &&
    (value.forecast === null || isDemoForecast(value.forecast)) &&
    (value.argument === null || isDemoArgument(value.argument)) &&
    (value.riskGate === null || isDemoRiskGate(value.riskGate)) &&
    (value.candidate === null || isDemoCandidate(value.candidate)) &&
    (value.certificate === null || isDemoCertificate(value.certificate)) &&
    (value.order === null || isDemoOrder(value.order)) &&
    (value.fill === null || isDemoFill(value.fill)) &&
    (value.reconciliation === null || isDemoReconciliation(value.reconciliation)) &&
    (value.close === null || isDemoClose(value.close)) &&
    (value.schedulerStatus === "running" || value.schedulerStatus === "paused") &&
    typeof value.emergencyStop === "boolean" &&
    isArray(value.auditEvents) &&
    value.auditEvents.length <= 200 &&
    value.auditEvents.every(isAuditEvent) &&
    isIntegerAtLeast(value.lastUpdatedSequence, 0)
  )) return false

  const fixture = getFixture(value.scenarioId)
  return (
    value.seed === fixture.seed &&
    isRunStateConsistent(value as unknown as DemoRun, fixture) &&
    isAuditStreamConsistent(value as unknown as DemoRun, fixture)
  )
}

function isRunNumberingConsistent(
  activeRun: DemoRun | null,
  runHistory: readonly DemoRun[],
  nextRunNumber: number,
): boolean {
  if (activeRun === null && runHistory.length === 0) return false

  const historyNumbers = runHistory.map((run) => getRunNumber(run.runId))
  if (historyNumbers.some((number) => number === null)) return false
  for (let index = 1; index < historyNumbers.length; index += 1) {
    if (historyNumbers[index] !== historyNumbers[index - 1]! + 1) return false
  }

  const activeNumber = activeRun === null ? null : getRunNumber(activeRun.runId)
  if (activeRun !== null && activeNumber === null) return false
  if (activeRun !== null) {
    const expectedActiveNumber = historyNumbers.length === 0
      ? 1
      : historyNumbers.at(-1)! + 1
    if (activeNumber !== expectedActiveNumber) return false
  }

  const expectedNextRunNumber = activeNumber !== null
    ? activeNumber + 1
    : historyNumbers.at(-1)! + 1
  return nextRunNumber === expectedNextRunNumber
}

function getRunNumber(runId: string): number | null {
  const match = /^run-(\d+)$/.exec(runId)
  if (!match) return null
  const number = Number(match[1])
  return isIntegerAtLeast(number, 1) && `run-${String(number).padStart(4, "0")}` === runId
    ? number
    : null
}

function isRunStateConsistent(run: DemoRun, fixture: ReturnType<typeof getFixture>): boolean {
  const postForecast = run.lifecycle !== "observing"
  const postArgument = [
    "argued", "awaiting_supervision", "vetoed", "certified", "simulated_submitted",
    "simulated_working", "simulated_filled", "reconciliation_required", "reconciled",
    "closing", "closed", "broker_unknown",
  ].includes(run.lifecycle)
  const hasCandidate = postArgument && run.argument === "BASE"
  const hasCertificate = [
    "certified", "simulated_submitted", "simulated_working", "simulated_filled",
    "reconciliation_required", "reconciled", "closing", "closed", "broker_unknown",
  ].includes(run.lifecycle)
  const hasOrder = [
    "simulated_submitted", "simulated_working", "simulated_filled", "reconciliation_required",
    "reconciled", "closing", "closed", "broker_unknown",
  ].includes(run.lifecycle)
  const hasFill = [
    "simulated_filled", "reconciliation_required", "reconciled", "closing", "closed", "broker_unknown",
  ].includes(run.lifecycle)
  const requiresReconciliation = ["reconciliation_required", "reconciled", "broker_unknown"].includes(run.lifecycle)
  const mayHaveReconciliation = requiresReconciliation || run.lifecycle === "closing" || run.lifecycle === "closed"
  const hasClose = run.lifecycle === "closed"

  if (postForecast !== (run.forecast !== null)) return false
  if (postForecast && !deepEqual(run.forecast, fixture.forecast)) return false
  if (postForecast && run.evidenceCursor !== fixture.evidence.length) return false

  if (postArgument !== (run.argument !== null)) return false
  if (postArgument && run.argument !== fixture.argument) return false
  if (postArgument !== (run.riskGate !== null)) return false
  if (postArgument && !deepEqual(run.riskGate, fixture.riskGate)) return false

  if (hasCandidate !== (run.candidate !== null)) return false
  if (hasCandidate && !deepEqual(run.candidate, fixture.candidate)) return false

  if (hasCertificate !== (run.certificate !== null)) return false
  if (
    hasCertificate &&
    (!isCertificateForFixture(run.certificate, fixture.certificate) || run.certificate!.issuedAtSequence > run.lastUpdatedSequence)
  ) return false
  if (hasCertificate) {
    const issuanceEvent = run.auditEvents.find((event) => event.sequence === run.certificate!.issuedAtSequence)
    if (
      issuanceEvent !== undefined &&
      (issuanceEvent.action !== "APPROVE_PROPOSAL" || issuanceEvent.outcome !== "ACCEPTED" || issuanceEvent.resultingState !== "certified")
    ) return false
  }

  if (hasOrder !== (run.order !== null)) return false
  if (hasOrder && !deepEqual(run.order, fixture.order)) return false

  if (hasFill !== (run.fill !== null)) return false
  if (hasFill && !deepEqual(run.fill, fixture.fill)) return false

  if (requiresReconciliation !== (run.reconciliation !== null)) return false
  if (!mayHaveReconciliation && run.reconciliation !== null) return false
  if ((run.lifecycle === "closing" || run.lifecycle === "closed") && run.reconciliation === null && !run.emergencyStop) return false
  if (run.reconciliation !== null && !deepEqual(run.reconciliation, fixture.reconciliation)) return false

  if (hasClose !== (run.close !== null)) return false
  if (hasClose && !deepEqual(run.close, fixture.close)) return false

  return true
}

function isCertificateForFixture(
  certificate: DemoCertificate | null,
  fixtureCertificate: DemoCertificate | null,
): boolean {
  if (certificate === null || fixtureCertificate === null) return false
  return (
    deepEqual(
      { ...certificate, issuedAtSequence: fixtureCertificate.issuedAtSequence },
      fixtureCertificate,
    ) &&
    isIntegerAtLeast(certificate.issuedAtSequence, 1)
  )
}

function isAuditStreamConsistent(run: DemoRun, fixture: ReturnType<typeof getFixture>): boolean {
  const events = run.auditEvents
  if (events.length === 0) {
    return run.lastUpdatedSequence === 0 && isPristineRun(run)
  }

  const firstSequence = events[0]!.sequence
  const lastSequence = events.at(-1)!.sequence
  if (events.length < 200 && firstSequence !== 1) return false
  if (events.length === 200 && firstSequence !== lastSequence - 199) return false

  for (let index = 0; index < events.length; index += 1) {
    const event = events[index]!
    if (index > 0) {
      const previous = events[index - 1]!
      if (event.sequence !== previous.sequence + 1 || event.priorState !== previous.resultingState) return false
    }
    if (event.timestamp !== deterministicTimestamp(fixture.evaluationTime, event.sequence)) return false
  }

  return run.lastUpdatedSequence === lastSequence && events.at(-1)!.resultingState === run.lifecycle
}

function isPristineRun(run: DemoRun): boolean {
  return (
    run.lifecycle === "observing" &&
    run.evidenceCursor === 0 &&
    run.forecast === null &&
    run.argument === null &&
    run.riskGate === null &&
    run.candidate === null &&
    run.certificate === null &&
    run.order === null &&
    run.fill === null &&
    run.reconciliation === null &&
    run.close === null &&
    run.schedulerStatus === "running" &&
    !run.emergencyStop
  )
}

function deterministicTimestamp(evaluationTime: string, sequence: number): string {
  return new Date(Date.parse(evaluationTime) + sequence * 1_000).toISOString()
}

function isTerminalLifecycle(value: Lifecycle): boolean {
  return value === "vetoed" || value === "closed"
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (isArray(left) && isArray(right)) {
    return left.length === right.length && left.every((entry, index) => deepEqual(entry, right[index]))
  }
  if (!isRecord(left) || !isRecord(right)) return false
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every((key) => Object.prototype.hasOwnProperty.call(right, key) && deepEqual(left[key], right[key]))
  )
}

function isDemoForecast(value: unknown): value is DemoForecast {
  return isRecord(value) && isArray(value.nodes) && value.nodes.length > 0 && value.nodes.every(isForecastNode) && isDemoRationale(value.rationale)
}

function isForecastNode(value: unknown): boolean {
  return isRecord(value) && isNonEmptyString(value.returnValue) && isNumberBetween(value.probability, 0, 1)
}

function isDemoRationale(value: unknown): value is DemoRationale {
  return isRecord(value) && isNonEmptyString(value.thesis) && isNonEmptyString(value.supportingEvidence) && isNonEmptyString(value.counterevidence) && isNonEmptyString(value.uncertainty) && isDemoArgument(value.recommendation)
}

function isDemoRiskGate(value: unknown): value is DemoRiskGate {
  return isRecord(value) &&
    typeof value.equalRatio === "boolean" &&
    typeof value.sameExpiration === "boolean" &&
    typeof value.coveredLegs === "boolean" &&
    value.quoteProvenance === "SYNTHETIC_OPRA_PRESENT" &&
    value.evidenceFreshness === "FRESH" &&
    isFiniteNumber(value.maxLoss) &&
    isFiniteNumber(value.lossCap) &&
    (value.output === "PASS" || value.output === "NOT_EVALUATED")
}

function isDemoCandidate(value: unknown): boolean {
  return isRecord(value) && isNonEmptyString(value.symbol) && isFiniteNumber(value.referencePrice) && isNonEmptyString(value.expiration) && isIntegerAtLeast(value.dte, 0) && isDemoStructure(value) && isFiniteNumber(value.maxLoss)
}

function isDemoStructure(value: unknown): value is DemoStructure {
  return isRecord(value) &&
    isFiniteNumber(value.ratio) &&
    isIntegerAtLeast(value.quantity, 0) &&
    isFiniteNumber(value.netCredit) &&
    isFiniteNumber(value.netCreditDollars) &&
    isFiniteNumber(value.wingWidth) &&
    isArray(value.legs) &&
    value.legs.length > 0 &&
    value.legs.every(isDemoLeg)
}

function isDemoLeg(value: unknown): value is DemoLeg {
  return isRecord(value) && isNonEmptyString(value.symbol) && (value.side === "LONG" || value.side === "SHORT") && isIntegerAtLeast(value.quantity, 0) && isFiniteNumber(value.strike) && (value.right === "PUT" || value.right === "CALL") && isNonEmptyString(value.expiration)
}

function isDemoCertificate(value: unknown): value is DemoCertificate {
  return isRecord(value) && isNonEmptyString(value.idTemplate) && value.policy === "risk-constitution.v1" && isIntegerAtLeast(value.issuedAtSequence, 1) && value.verdict === "CERTIFIED" && isFiniteNumber(value.maxLoss) && isNonEmptyString(value.candidateDigest)
}

function isDemoOrder(value: unknown): value is DemoOrder {
  return isRecord(value) && isNonEmptyString(value.idTemplate) && isFiniteNumber(value.limitCredit) && isIntegerAtLeast(value.quantity, 0) && value.timeInForce === "DAY"
}

function isDemoFill(value: unknown): value is DemoFill {
  return isRecord(value) && isFiniteNumber(value.credit) && isArray(value.legs) && value.legs.length > 0 && value.legs.every(isDemoLeg)
}

function isDemoReconciliation(value: unknown): value is DemoReconciliation {
  return isRecord(value) && value.localOrderState === "SIMULATED_FILLED" && isRecord(value.brokerSnapshot) && isArray(value.brokerSnapshot.legs) && value.brokerSnapshot.legs.length > 0 && value.brokerSnapshot.legs.every(isDemoLeg) && isDemoLeg(value.correctedLeg) && value.result === "RECONCILED"
}

function isDemoClose(value: unknown): value is DemoClose {
  return isRecord(value) && isNonEmptyString(value.idTemplate) && isArray(value.legs) && value.legs.length > 0 && value.legs.every(isDemoLeg) && value.lifecycle === "CLOSED" && value.pnl === null
}

function isAuditEvent(value: unknown): value is AuditEvent {
  return isRecord(value) &&
    isIntegerAtLeast(value.sequence, 1) &&
    isNonEmptyString(value.timestamp) &&
    isDemoActionType(value.action) &&
    value.action !== "RESET_SCENARIO" &&
    isLifecycle(value.priorState) &&
    isLifecycle(value.resultingState) &&
    (value.actor === "PUBLIC_DEMO_USER" || value.actor === "SIMULATOR") &&
    isNonEmptyString(value.summary) &&
    (value.outcome === "ACCEPTED" || value.outcome === "REJECTED") &&
    (value.details === undefined || isDetails(value.details))
}

function isDetails(value: unknown): boolean {
  return isRecord(value) && Object.values(value).every((entry) => entry === null || typeof entry === "string" || typeof entry === "boolean" || isFiniteNumber(entry))
}

function isDemoActionType(value: unknown): boolean {
  return [
    "ADVANCE_EVIDENCE", "COMPLETE_FORECAST", "COMPLETE_ARGUMENT", "REQUEST_SUPERVISION", "APPROVE_PROPOSAL", "VETO_PROPOSAL", "SIMULATE_SUBMIT", "SIMULATE_WORKING", "SIMULATE_FILL", "PAUSE_SCHEDULER", "RESUME_SCHEDULER", "TRIGGER_RECONCILIATION", "RESOLVE_RECONCILIATION", "FAIL_RECONCILIATION", "CLOSE_POSITION", "COMPLETE_CLOSE", "EMERGENCY_STOP", "RESET_SCENARIO",
  ].includes(value as string)
}

function isScenarioId(value: unknown): value is ScenarioId {
  return value === "guided-certifiable-v1" || value === "guided-catalyst-veto-v1"
}

function isDemoArgument(value: unknown): value is DemoArgument {
  return value === "BASE" || value === "VETO"
}

function isLifecycle(value: unknown): value is Lifecycle {
  return [
    "observing", "forecasted", "argued", "awaiting_supervision", "vetoed", "certified", "simulated_submitted", "simulated_working", "simulated_filled", "reconciliation_required", "reconciled", "closing", "closed", "broker_unknown",
  ].includes(value as string)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isArray(value: unknown): value is readonly unknown[] {
  return Array.isArray(value)
}

function isString(value: unknown): value is string {
  return typeof value === "string"
}

function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.length > 0
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isNumberBetween(value: unknown, minimum: number, maximum: number): value is number {
  return isFiniteNumber(value) && value >= minimum && value <= maximum
}

function isIntegerAtLeast(value: unknown, minimum: number): value is number {
  return isFiniteNumber(value) && Number.isInteger(value) && value >= minimum
}
