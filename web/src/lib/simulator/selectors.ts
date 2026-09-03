import { getFixture } from "./fixtures"
import type {
  DemoActionType,
  DemoArgument,
  DemoCertificate,
  DemoEnvelope,
  DemoEvidenceItem,
  DemoFill,
  DemoForecast,
  DemoOrder,
  DemoRationale,
  DemoReconciliation,
  DemoRiskGate,
  DemoRun,
  ScenarioId,
} from "./types"

export interface ActionAvailability {
  enabled: boolean
  reason?: string
}

export type ActionAvailabilityMap = Record<DemoActionType, ActionAvailability>

export type SimulatedBoundaryStatus =
  | "NOT_STARTED"
  | "SUBMITTED"
  | "WORKING"
  | "FILLED"
  | "RECONCILIATION_REQUIRED"
  | "RECONCILED"
  | "UNKNOWN"
  | "CLOSED"

export interface SimulatedBoundaryState {
  status: SimulatedBoundaryStatus
  order: DemoOrder | null
  fill: DemoFill | null
  reconciliation: DemoReconciliation | null
}

export const DEMO_ACTION_TYPES: readonly DemoActionType[] = [
  "ADVANCE_EVIDENCE",
  "COMPLETE_FORECAST",
  "COMPLETE_ARGUMENT",
  "REQUEST_SUPERVISION",
  "APPROVE_PROPOSAL",
  "VETO_PROPOSAL",
  "SIMULATE_SUBMIT",
  "SIMULATE_WORKING",
  "SIMULATE_FILL",
  "PAUSE_SCHEDULER",
  "RESUME_SCHEDULER",
  "TRIGGER_RECONCILIATION",
  "RESOLVE_RECONCILIATION",
  "FAIL_RECONCILIATION",
  "CLOSE_POSITION",
  "COMPLETE_CLOSE",
  "EMERGENCY_STOP",
  "RESET_SCENARIO",
]

export function selectActiveRun(state: DemoEnvelope): DemoRun | null {
  return state.activeRun
}

export function selectRunHistory(state: DemoEnvelope): readonly DemoRun[] {
  return state.runHistory
}

export function selectScenarioId(run: DemoRun | null): ScenarioId | null {
  return run?.scenarioId ?? null
}

export function selectEvidence(runOrState: DemoRun | DemoEnvelope | null): readonly DemoEvidenceItem[] {
  const run = asRun(runOrState)
  if (run === null) return []
  return getFixture(run.scenarioId).evidence.slice(0, run.evidenceCursor)
}

export function selectForecast(runOrState: DemoRun | DemoEnvelope | null): DemoForecast | null {
  return asRun(runOrState)?.forecast ?? null
}

export function selectRationale(runOrState: DemoRun | DemoEnvelope | null): DemoRationale | null {
  const run = asRun(runOrState)
  if (run === null) return null
  return run.forecast?.rationale ?? getFixture(run.scenarioId).forecast.rationale
}

export function selectRiskGate(runOrState: DemoRun | DemoEnvelope | null): DemoRiskGate | null {
  return asRun(runOrState)?.riskGate ?? null
}

export function selectArgument(runOrState: DemoRun | DemoEnvelope | null): DemoArgument | null {
  return asRun(runOrState)?.argument ?? null
}

export function selectCertificate(runOrState: DemoRun | DemoEnvelope | null): DemoCertificate | null {
  return asRun(runOrState)?.certificate ?? null
}

export function selectAuditEvents(runOrState: DemoRun | DemoEnvelope | null) {
  return asRun(runOrState)?.auditEvents ?? []
}

export function selectBrokerState(runOrState: DemoRun | DemoEnvelope | null): SimulatedBoundaryState {
  const run = asRun(runOrState)
  if (run === null) return { status: "NOT_STARTED", order: null, fill: null, reconciliation: null }

  const status: SimulatedBoundaryStatus =
    run.lifecycle === "simulated_submitted" ? "SUBMITTED" :
      run.lifecycle === "simulated_working" ? "WORKING" :
        run.lifecycle === "simulated_filled" ? "FILLED" :
          run.lifecycle === "reconciliation_required" ? "RECONCILIATION_REQUIRED" :
            run.lifecycle === "reconciled" ? "RECONCILED" :
              run.lifecycle === "broker_unknown" ? "UNKNOWN" :
                run.lifecycle === "closing" || run.lifecycle === "closed" ? "CLOSED" :
                  "NOT_STARTED"

  return {
    status,
    order: run.order,
    fill: run.fill,
    reconciliation: run.reconciliation,
  }
}

export function selectActionAvailability(run: DemoRun | null, action: DemoActionType): ActionAvailability {
  if (action === "RESET_SCENARIO") return { enabled: true }
  if (run === null) return disabled("Start a guided scenario before taking simulator actions.")

  const fixture = getFixture(run.scenarioId)
  const stopBlocksEntry = run.emergencyStop && [
    "ADVANCE_EVIDENCE",
    "COMPLETE_FORECAST",
    "COMPLETE_ARGUMENT",
    "REQUEST_SUPERVISION",
    "APPROVE_PROPOSAL",
    "SIMULATE_SUBMIT",
  ].includes(action)
  if (stopBlocksEntry) return disabled("Emergency stop is active; new entry is disabled.")

  switch (action) {
    case "ADVANCE_EVIDENCE":
      return run.lifecycle === "observing" && run.evidenceCursor < fixture.evidence.length
        ? enabled()
        : disabled(run.lifecycle !== "observing" ? "Evidence can only advance while observing." : "All authored evidence is already present.")
    case "COMPLETE_FORECAST":
      return run.lifecycle === "observing" && run.evidenceCursor === fixture.evidence.length
        ? enabled()
        : disabled("Complete all authored evidence before recording the forecast.")
    case "COMPLETE_ARGUMENT":
      return run.lifecycle === "forecasted"
        ? enabled()
        : disabled("Complete the forecast before recording an argument.")
    case "REQUEST_SUPERVISION":
      return run.lifecycle === "argued" && run.argument === "BASE" && run.candidate !== null && run.riskGate?.output === "PASS"
        ? enabled()
        : disabled("Complete a valid BASE argument before requesting supervision.")
    case "APPROVE_PROPOSAL":
      return run.lifecycle === "awaiting_supervision" && run.argument === "BASE" && run.candidate !== null && run.riskGate?.output === "PASS"
        ? enabled()
        : disabled("Complete evidence, forecast, and argument before approval.")
    case "VETO_PROPOSAL":
      return run.lifecycle === "awaiting_supervision" ? enabled() : disabled("Veto requires awaiting supervision.")
    case "SIMULATE_SUBMIT":
      return run.lifecycle === "certified" && run.certificate !== null && fixture.order !== null
        ? enabled()
        : disabled("Submission requires a current certificate.")
    case "SIMULATE_WORKING":
      return run.lifecycle === "simulated_submitted"
        ? enabled()
        : disabled("Working state requires a submitted order.")
    case "SIMULATE_FILL":
      return run.lifecycle === "simulated_working" && fixture.fill !== null
        ? enabled()
        : disabled("Fill requires a working synthetic order.")
    case "PAUSE_SCHEDULER":
      return run.schedulerStatus === "running" ? enabled() : disabled("Scheduler is already paused.")
    case "RESUME_SCHEDULER":
      return run.schedulerStatus === "paused" ? enabled() : disabled("Scheduler is already running.")
    case "TRIGGER_RECONCILIATION":
      return run.lifecycle === "simulated_filled" && fixture.reconciliation !== null
        ? enabled()
        : disabled("Reconciliation requires a synthetic fill.")
    case "RESOLVE_RECONCILIATION":
      return run.lifecycle === "reconciliation_required" && run.reconciliation !== null && fixture.reconciliation !== null
        ? enabled()
        : disabled("Resolution requires reconciliation.")
    case "FAIL_RECONCILIATION":
      return run.lifecycle === "reconciliation_required"
        ? enabled()
        : disabled("Failure requires reconciliation.")
    case "CLOSE_POSITION":
      return run.fill !== null && (
        run.lifecycle === "reconciled" ||
        (run.emergencyStop && (run.lifecycle === "simulated_filled" || run.lifecycle === "broker_unknown"))
      )
        ? enabled()
        : disabled("Normal close requires reconciled state; emergency safe-close requires an active stop.")
    case "COMPLETE_CLOSE":
      return run.lifecycle === "closing" && fixture.close !== null
        ? enabled()
        : disabled("Close completion requires a close request.")
    case "EMERGENCY_STOP":
      return run.lifecycle !== "closed" && !run.emergencyStop
        ? enabled()
        : disabled(run.emergencyStop ? "Emergency stop is already active." : "Closed runs cannot be stopped.")
  }
}

export function selectActionAvailabilities(run: DemoRun | null): ActionAvailabilityMap {
  return Object.fromEntries(DEMO_ACTION_TYPES.map((action) => [action, selectActionAvailability(run, action)])) as ActionAvailabilityMap
}

function enabled(): ActionAvailability {
  return { enabled: true }
}

function disabled(reason: string): ActionAvailability {
  return { enabled: false, reason }
}

function asRun(value: DemoRun | DemoEnvelope | null): DemoRun | null {
  if (value === null) return null
  return "activeRun" in value ? value.activeRun : value
}
