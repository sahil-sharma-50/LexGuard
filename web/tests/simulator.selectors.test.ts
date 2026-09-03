import { describe, expect, it } from "vitest"
import { createAuthoredSeed, createRun, getFixture } from "../src/lib/simulator/fixtures"
import { reduceRun } from "../src/lib/simulator/reducer"
import {
  selectActionAvailability,
  selectActionAvailabilities,
  selectBrokerState,
  selectRationale,
  selectRiskGate,
} from "../src/lib/simulator/selectors"
import type { DemoActionType, DemoRun } from "../src/lib/simulator/types"

function runAt(lifecycle: DemoRun["lifecycle"]): DemoRun {
  return { ...createRun(getFixture("guided-certifiable-v1"), 1), lifecycle }
}

describe("simulator selectors", () => {
  it("explains why approval is unavailable before the evidence path is complete", () => {
    expect(selectActionAvailability(runAt("observing"), "APPROVE_PROPOSAL")).toEqual({
      enabled: false,
      reason: "Complete evidence, forecast, and argument before approval.",
    })
  })

  it("enables actions only at their deterministic lifecycle boundary", () => {
    const observing = runAt("observing")
    const fixture = getFixture("guided-certifiable-v1")
    const awaiting = {
      ...runAt("awaiting_supervision"),
      argument: "BASE" as const,
      candidate: fixture.candidate,
      riskGate: fixture.riskGate,
    }
    const certified = {
      ...awaiting,
      lifecycle: "certified" as const,
      certificate: fixture.certificate,
    }

    expect(selectActionAvailability(observing, "ADVANCE_EVIDENCE")).toEqual({ enabled: true })
    expect(selectActionAvailability(observing, "COMPLETE_FORECAST").enabled).toBe(false)
    expect(selectActionAvailability(awaiting, "APPROVE_PROPOSAL")).toEqual({ enabled: true })
    expect(selectActionAvailability(awaiting, "VETO_PROPOSAL")).toEqual({ enabled: true })
    expect(selectActionAvailability(certified, "SIMULATE_SUBMIT")).toEqual({ enabled: true })
  })

  it("disables entry actions while an emergency stop is active", () => {
    const stopped = { ...runAt("certified"), emergencyStop: true }
    const availability = selectActionAvailability(stopped, "SIMULATE_SUBMIT")
    expect(availability.enabled).toBe(false)
    expect(availability.reason).toMatch(/emergency stop/i)
  })

  it("returns typed availability for every simulator action", () => {
    const actions: DemoActionType[] = [
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
    const result = selectActionAvailabilities(runAt("observing"))
    for (const action of actions) {
      expect(result[action]).toEqual(expect.objectContaining({ enabled: expect.any(Boolean) }))
    }
  })

  it("selects structured rationale and risk-gate state from the authored fixture", () => {
    const state = createAuthoredSeed()
    expect(selectRationale(state.activeRun!)).toMatchObject({ recommendation: "BASE" })
    expect(selectRiskGate(state.activeRun!)).toBeNull()

    const argued = {
      ...state.activeRun!,
      lifecycle: "argued" as const,
      forecast: getFixture("guided-certifiable-v1").forecast,
      argument: "BASE" as const,
      riskGate: getFixture("guided-certifiable-v1").riskGate,
    }
    expect(selectRationale(argued)).toMatchObject({ thesis: expect.any(String), recommendation: "BASE" })
    expect(selectRiskGate(argued)).toMatchObject({ output: "PASS", maxLoss: 310 })
  })

  it("summarizes the simulated broker boundary without inventing live state", () => {
    expect(selectBrokerState(runAt("observing"))).toEqual({ status: "NOT_STARTED", order: null, fill: null, reconciliation: null })
    expect(selectBrokerState(runAt("broker_unknown"))).toEqual({
      status: "UNKNOWN",
      order: null,
      fill: null,
      reconciliation: null,
    })
  })

  it("matches reducer semantics for incomplete persisted payloads", () => {
    const fixture = getFixture("guided-certifiable-v1")
    const submittedWithoutOrder = { ...runAt("simulated_submitted"), order: null }
    const workingAction = { type: "SIMULATE_WORKING" as const }
    expect(reduceRun(submittedWithoutOrder, fixture, workingAction).accepted).toBe(true)
    expect(selectActionAvailability(submittedWithoutOrder, workingAction.type).enabled).toBe(true)

    const forecastedWithoutForecast = { ...runAt("forecasted"), forecast: null }
    const argumentAction = { type: "COMPLETE_ARGUMENT" as const }
    expect(reduceRun(forecastedWithoutForecast, fixture, argumentAction).accepted).toBe(true)
    expect(selectActionAvailability(forecastedWithoutForecast, argumentAction.type).enabled).toBe(true)

    const reconciliationWithoutPayload = { ...runAt("reconciliation_required"), reconciliation: null }
    const failAction = { type: "FAIL_RECONCILIATION" as const }
    expect(reduceRun(reconciliationWithoutPayload, fixture, failAction).accepted).toBe(true)
    expect(selectActionAvailability(reconciliationWithoutPayload, failAction.type).enabled).toBe(true)

    const vetoFixture = getFixture("guided-catalyst-veto-v1")
    const reconciliationWithoutAuthoredCorrection = {
      ...createRun(vetoFixture, 1),
      lifecycle: "reconciliation_required" as const,
      reconciliation: fixture.reconciliation,
    }
    const resolveAction = { type: "RESOLVE_RECONCILIATION" as const }
    expect(reduceRun(reconciliationWithoutAuthoredCorrection, vetoFixture, resolveAction).accepted).toBe(false)
    expect(selectActionAvailability(reconciliationWithoutAuthoredCorrection, resolveAction.type).enabled).toBe(false)

    const fillWithoutAuthoredResult = { ...createRun(vetoFixture, 1), lifecycle: "simulated_working" as const }
    const fillAction = { type: "SIMULATE_FILL" as const }
    expect(reduceRun(fillWithoutAuthoredResult, vetoFixture, fillAction).accepted).toBe(false)
    expect(selectActionAvailability(fillWithoutAuthoredResult, fillAction.type).enabled).toBe(false)

    const closeWithoutAuthoredResult = { ...createRun(vetoFixture, 1), lifecycle: "closing" as const }
    const closeAction = { type: "COMPLETE_CLOSE" as const }
    expect(reduceRun(closeWithoutAuthoredResult, vetoFixture, closeAction).accepted).toBe(false)
    expect(selectActionAvailability(closeWithoutAuthoredResult, closeAction.type).enabled).toBe(false)
  })
})
