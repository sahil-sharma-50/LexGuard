import { createAuthoredSeed, createRun, getFixture } from "./fixtures"
import type {
  AuditEvent,
  DemoAction,
  DemoEnvelope,
  DemoFixture,
  DemoRun,
  Lifecycle,
  ScenarioId,
} from "./types"

const MAX_AUDIT_EVENTS = 200
const MAX_RUN_HISTORY = 20

export interface TransitionResult {
  state: DemoEnvelope
  accepted: boolean
  event?: AuditEvent
  completedRunId?: string
}

export type ActivationResult =
  | { state: DemoEnvelope; runId: string; blocked: false }
  | { state: DemoEnvelope; runId: string; blocked: true; reason: string }

export interface RunTransitionResult {
  run: DemoRun
  accepted: boolean
  event?: AuditEvent
}

export function deterministicTimestamp(fixture: DemoFixture, sequence: number): string {
  return new Date(Date.parse(fixture.evaluationTime) + sequence * 1_000).toISOString()
}

/**
 * Applies one action to a run. The fixture-first argument order is the public
 * form; the action-first overload is retained for callers that use reducer
 * conventions (`run, action, fixture`).
 */
export function reduceRun(run: DemoRun, fixture: DemoFixture, action: DemoAction): RunTransitionResult
export function reduceRun(run: DemoRun, action: DemoAction, fixture: DemoFixture): RunTransitionResult
export function reduceRun(
  run: DemoRun,
  fixtureOrAction: DemoFixture | DemoAction,
  actionOrFixture: DemoAction | DemoFixture,
): RunTransitionResult {
  const fixture = isDemoAction(fixtureOrAction) ? actionOrFixture : fixtureOrAction
  const action = isDemoAction(fixtureOrAction) ? fixtureOrAction : actionOrFixture

  if (!isDemoAction(action) || !isDemoFixture(fixture)) {
    return rejectRun(run, isDemoFixture(fixture) ? fixture : getFixture(run.scenarioId), {
      type: "RESET_SCENARIO",
    }, "Invalid simulator reducer arguments")
  }

  const priorState = run.lifecycle
  let next = cloneRun(run)
  let resultingState: Lifecycle = priorState
  let summary = ""
  let details: Readonly<Record<string, string | number | boolean | null>> | undefined

  const reject = (reason: string): RunTransitionResult => rejectRun(run, fixture, action, reason)

  switch (action.type) {
    case "ADVANCE_EVIDENCE":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "observing") return reject("Evidence can only advance while observing")
      if (run.evidenceCursor >= fixture.evidence.length) return reject("All authored evidence is already present")
      next.evidenceCursor += 1
      summary = `Evidence item ${next.evidenceCursor} accepted`
      break

    case "COMPLETE_FORECAST":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "observing") return reject("Forecast requires the observing state")
      if (run.evidenceCursor !== fixture.evidence.length) return reject("All authored evidence is required")
      next.forecast = fixture.forecast
      resultingState = "forecasted"
      next.lifecycle = resultingState
      summary = "Authored forecast recorded"
      break

    case "COMPLETE_ARGUMENT":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "forecasted") return reject("Argument requires a completed forecast")
      next.argument = fixture.argument
      next.riskGate = fixture.riskGate
      if (fixture.argument === "VETO") {
        next.lifecycle = "vetoed"
        next.candidate = null
        next.certificate = null
        next.order = null
        next.fill = null
        next.reconciliation = null
        next.close = null
        resultingState = "vetoed"
        summary = "Bounded argument vetoed entry"
      } else {
        next.lifecycle = "argued"
        next.candidate = fixture.candidate
        resultingState = "argued"
        summary = "Bounded BASE argument recorded"
      }
      break

    case "REQUEST_SUPERVISION":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "argued") return reject("Supervision requires a valid argument")
      if (run.argument !== "BASE" || run.candidate === null || run.riskGate?.output !== "PASS") {
        return reject("Only a valid BASE proposal can request supervision")
      }
      next.lifecycle = "awaiting_supervision"
      resultingState = "awaiting_supervision"
      summary = "Proposal queued for explicit supervision"
      break

    case "APPROVE_PROPOSAL":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "awaiting_supervision") return reject("Approval requires awaiting supervision")
      if (run.argument !== "BASE" || run.candidate === null || run.riskGate?.output !== "PASS") {
        return reject("Deterministic policy did not pass")
      }
      next.certificate = fixture.certificate
        ? { ...fixture.certificate, issuedAtSequence: run.lastUpdatedSequence + 1 }
        : null
      resultingState = "certified"
      next.lifecycle = resultingState
      summary = "Proposal approved; deterministic certificate issued"
      details = { policy: fixture.certificate?.policy ?? null }
      break

    case "VETO_PROPOSAL":
      if (run.lifecycle !== "awaiting_supervision") return reject("Veto requires awaiting supervision")
      next.lifecycle = "vetoed"
      next.certificate = null
      next.order = null
      next.fill = null
      next.reconciliation = null
      next.close = null
      resultingState = "vetoed"
      summary = "Supervisor veto recorded; simulator abstains"
      break

    case "SIMULATE_SUBMIT":
      if (run.emergencyStop) return reject("Emergency stop is active")
      if (run.lifecycle !== "certified") return reject("Submission requires a current certificate")
      if (run.certificate === null || fixture.order === null) return reject("No current synthetic order is available")
      next.order = fixture.order
      next.lifecycle = "simulated_submitted"
      resultingState = "simulated_submitted"
      summary = "Synthetic order accepted locally"
      break

    case "SIMULATE_WORKING":
      if (run.lifecycle !== "simulated_submitted") return reject("Working state requires a submitted order")
      next.lifecycle = "simulated_working"
      resultingState = "simulated_working"
      summary = "Synthetic order marked working"
      break

    case "SIMULATE_FILL":
      if (run.lifecycle !== "simulated_working") return reject("Fill requires a working synthetic order")
      if (fixture.fill === null) return reject("No authored synthetic fill is available")
      next.fill = fixture.fill
      next.lifecycle = "simulated_filled"
      resultingState = "simulated_filled"
      summary = "Authored synthetic fill recorded"
      break

    case "PAUSE_SCHEDULER":
      if (run.schedulerStatus !== "running") return reject("Scheduler is already paused")
      next.schedulerStatus = "paused"
      summary = "Scheduler paused"
      break

    case "RESUME_SCHEDULER":
      if (run.schedulerStatus !== "paused") return reject("Scheduler is already running")
      next.schedulerStatus = "running"
      summary = "Scheduler resumed"
      break

    case "TRIGGER_RECONCILIATION":
      if (run.lifecycle !== "simulated_filled") return reject("Reconciliation requires a synthetic fill")
      if (fixture.reconciliation === null) return reject("No authored discrepancy is available")
      next.reconciliation = fixture.reconciliation
      next.lifecycle = "reconciliation_required"
      resultingState = "reconciliation_required"
      summary = "Synthetic broker discrepancy presented"
      break

    case "RESOLVE_RECONCILIATION":
      if (run.lifecycle !== "reconciliation_required") return reject("Resolution requires reconciliation")
      if (run.reconciliation === null || fixture.reconciliation === null) return reject("No authored correction is available")
      next.reconciliation = fixture.reconciliation
      next.lifecycle = "reconciled"
      resultingState = "reconciled"
      summary = "Synthetic broker state reconciled"
      details = { correctedQuantity: fixture.reconciliation.correctedLeg.quantity }
      break

    case "FAIL_RECONCILIATION":
      if (run.lifecycle !== "reconciliation_required") return reject("Failure requires reconciliation")
      next.lifecycle = "broker_unknown"
      resultingState = "broker_unknown"
      summary = "Reconciliation failed closed; broker state unknown"
      break

    case "CLOSE_POSITION":
      if (run.fill === null) return reject("No simulated position exists")
      if (run.lifecycle === "reconciled") {
        next.lifecycle = "closing"
        resultingState = "closing"
        summary = "Normal synthetic position close requested"
      } else if ((run.lifecycle === "simulated_filled" || run.lifecycle === "broker_unknown") && run.emergencyStop) {
        next.lifecycle = "closing"
        resultingState = "closing"
        summary = "Emergency safe-close requested"
        details = { emergencyStop: true }
      } else {
        return reject("Normal close requires reconciled state; emergency safe-close requires an active stop")
      }
      break

    case "COMPLETE_CLOSE":
      if (run.lifecycle !== "closing") return reject("Close completion requires a close request")
      if (fixture.close === null) return reject("No authored close result is available")
      next.close = fixture.close
      next.lifecycle = "closed"
      resultingState = "closed"
      summary = "Synthetic position closed with no P&L claim"
      break

    case "EMERGENCY_STOP":
      if (run.lifecycle === "closed") return reject("Closed runs cannot be stopped")
      if (run.emergencyStop) return reject("Emergency stop is already active")
      next.emergencyStop = true
      summary = "Emergency stop active; new entry disabled"
      details = { entryDisabled: true }
      break

    case "RESET_SCENARIO":
      return rejectRun(run, fixture, action, "Reset is handled at envelope level")

    default:
      return reject("Unsupported simulator action")
  }

  const appended = appendEvent(next, fixture, action, priorState, resultingState, summary, true, details)

  if (action.type === "COMPLETE_ARGUMENT" && fixture.argument === "BASE") {
    const supervisionAction: DemoAction = { type: "REQUEST_SUPERVISION", actor: "SIMULATOR" }
    const supervised = appendEvent(
      { ...appended.run, lifecycle: "awaiting_supervision" },
      fixture,
      supervisionAction,
      "argued",
      "awaiting_supervision",
      "Simulator requested explicit supervision",
      true,
    )
    return { run: supervised.run, accepted: true, event: appended.event }
  }

  return { run: appended.run, accepted: true, event: appended.event }
}

export function applyDemoAction(state: DemoEnvelope, action: DemoAction): TransitionResult {
  if (action.type === "RESET_SCENARIO") {
    return { state: createAuthoredSeed(), accepted: true }
  }

  if (state.activeRun === null) {
    return { state, accepted: false }
  }

  const fixture = getFixture(state.activeRun.scenarioId)
  const transition = reduceRun(state.activeRun, fixture, action)
  if (
    transition.accepted &&
    (transition.run.lifecycle === "vetoed" || transition.run.lifecycle === "closed")
  ) {
    return {
      state: {
        ...state,
        activeRun: null,
        runHistory: [...state.runHistory, transition.run].slice(-MAX_RUN_HISTORY),
      },
      accepted: true,
      event: transition.event,
      completedRunId: transition.run.runId,
    }
  }
  return {
    state: { ...state, activeRun: transition.run },
    accepted: transition.accepted,
    event: transition.event,
  }
}

export function activateScenario(state: DemoEnvelope, scenarioId: ScenarioId): ActivationResult {
  const fixture = getFixture(scenarioId)
  const activeRun = state.activeRun

  if (activeRun !== null && activeRun.scenarioId === scenarioId && activeRun.lifecycle !== "vetoed" && activeRun.lifecycle !== "closed") {
    return { state, runId: activeRun.runId, blocked: false }
  }

  const canReplacePristineSeed = activeRun !== null && isPristineSeedRun(activeRun)
  if (
    activeRun !== null &&
    !canReplacePristineSeed &&
    activeRun.lifecycle !== "vetoed" &&
    activeRun.lifecycle !== "closed"
  ) {
    return {
      state,
      runId: activeRun.runId,
      blocked: true,
      reason: "Finish or reset the active run before selecting another scenario",
    }
  }

  const archived = activeRun === null || canReplacePristineSeed
    ? [...state.runHistory]
    : [...state.runHistory, activeRun].slice(-MAX_RUN_HISTORY)
  const nextRunNumber = canReplacePristineSeed ? 1 : state.nextRunNumber
  const run = createRun(fixture, nextRunNumber)
  return {
    state: {
      schemaVersion: 1,
      nextRunNumber: nextRunNumber + 1,
      activeRun: run,
      runHistory: archived,
    },
    runId: run.runId,
    blocked: false,
  }
}

function isPristineSeedRun(run: DemoRun): boolean {
  return (
    run.runId === "run-0001" &&
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
    !run.emergencyStop &&
    run.auditEvents.length === 0 &&
    run.lastUpdatedSequence === 0
  )
}

function cloneRun(run: DemoRun): DemoRun {
  return {
    ...run,
    auditEvents: [...run.auditEvents],
  }
}

function appendEvent(
  run: DemoRun,
  fixture: DemoFixture,
  action: DemoAction,
  priorState: Lifecycle,
  resultingState: Lifecycle,
  summary: string,
  accepted: boolean,
  details?: Readonly<Record<string, string | number | boolean | null>>,
): { run: DemoRun; event: AuditEvent } {
  const sequence = run.lastUpdatedSequence + 1
  const event: AuditEvent = {
    sequence,
    timestamp: deterministicTimestamp(fixture, sequence),
    action: action.type,
    priorState,
    resultingState,
    actor: action.actor ?? "PUBLIC_DEMO_USER",
    summary,
    outcome: accepted ? "ACCEPTED" : "REJECTED",
    ...(details ? { details } : {}),
  }
  return {
    run: {
      ...run,
      lifecycle: resultingState,
      auditEvents: [...run.auditEvents, event].slice(-MAX_AUDIT_EVENTS),
      lastUpdatedSequence: sequence,
    },
    event,
  }
}

function rejectRun(run: DemoRun, fixture: DemoFixture, action: DemoAction, reason: string): RunTransitionResult {
  const appended = appendEvent(
    cloneRun(run),
    fixture,
    action,
    run.lifecycle,
    run.lifecycle,
    reason,
    false,
    { reason },
  )
  return { run: appended.run, accepted: false, event: appended.event }
}

function isDemoAction(value: DemoFixture | DemoAction): value is DemoAction {
  return "type" in value
}

function isDemoFixture(value: DemoFixture | DemoAction): value is DemoFixture {
  return "scenarioId" in value && "evaluationTime" in value
}
