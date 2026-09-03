import { describe, expect, it } from "vitest"
import { createAuthoredSeed, createRun, getFixture } from "../src/lib/simulator/fixtures"
import {
  activateScenario,
  applyDemoAction,
  deterministicTimestamp,
  reduceRun,
} from "../src/lib/simulator/reducer"
import type { DemoAction, DemoEnvelope, DemoRun, Lifecycle, ScenarioId } from "../src/lib/simulator/types"

const CERTIFIABLE_PATH: DemoAction[] = [
  ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
  { type: "COMPLETE_FORECAST" },
  { type: "COMPLETE_ARGUMENT" },
  { type: "APPROVE_PROPOSAL" },
]

function activate(scenarioId: ScenarioId): DemoEnvelope {
  const result = activateScenario(createAuthoredSeed(), scenarioId)
  expect(result.blocked).toBe(false)
  return result.state
}

function replay(scenarioId: ScenarioId, actions: readonly DemoAction[]): DemoEnvelope {
  let state = activate(scenarioId)
  for (const action of actions) {
    state = applyDemoAction(state, action).state
  }
  return state
}

function certifiableToAwaiting(): DemoEnvelope {
  return replay("guided-certifiable-v1", CERTIFIABLE_PATH.slice(0, 7))
}

function certifiableToFilled(): DemoEnvelope {
  return replay("guided-certifiable-v1", [
    ...CERTIFIABLE_PATH,
    { type: "SIMULATE_SUBMIT" },
    { type: "SIMULATE_WORKING" },
    { type: "SIMULATE_FILL" },
  ])
}

function envelopeWithRun(run: DemoRun): DemoEnvelope {
  return { schemaVersion: 1, nextRunNumber: 2, activeRun: run, runHistory: [] }
}

function runAt(lifecycle: Lifecycle, scenarioId: ScenarioId = "guided-certifiable-v1"): DemoRun {
  return { ...createRun(getFixture(scenarioId), 1), lifecycle }
}

function certifiableToReconciliationRequired(): DemoEnvelope {
  return replay("guided-certifiable-v1", [
    ...CERTIFIABLE_PATH,
    { type: "SIMULATE_SUBMIT" },
    { type: "SIMULATE_WORKING" },
    { type: "SIMULATE_FILL" },
    { type: "TRIGGER_RECONCILIATION" },
  ])
}

function certifiableToReconciled(): DemoEnvelope {
  return replay("guided-certifiable-v1", [
    ...CERTIFIABLE_PATH,
    { type: "SIMULATE_SUBMIT" },
    { type: "SIMULATE_WORKING" },
    { type: "SIMULATE_FILL" },
    { type: "TRIGGER_RECONCILIATION" },
    { type: "RESOLVE_RECONCILIATION" },
  ])
}

function certifiableToBrokerUnknown(): DemoEnvelope {
  return replay("guided-certifiable-v1", [
    ...CERTIFIABLE_PATH,
    { type: "SIMULATE_SUBMIT" },
    { type: "SIMULATE_WORKING" },
    { type: "SIMULATE_FILL" },
    { type: "TRIGGER_RECONCILIATION" },
    { type: "FAIL_RECONCILIATION" },
  ])
}

describe("deterministic simulator reducer", () => {
  it("derives timestamps only from the authored fixture time and sequence", () => {
    const state = activate("guided-certifiable-v1")
    const evaluationTime = state.activeRun
      ? "2026-08-31T14:00:00Z"
      : "2026-08-31T14:00:00Z"
    expect(deterministicTimestamp({ evaluationTime } as never, 9)).toBe("2026-08-31T14:00:09.000Z")
  })

  it("issues the certificate at deterministic sequence nine", () => {
    const state = replay("guided-certifiable-v1", CERTIFIABLE_PATH)
    expect(state.activeRun?.certificate?.issuedAtSequence).toBe(9)
    expect(state.activeRun?.auditEvents[7]).toMatchObject({
      action: "REQUEST_SUPERVISION",
      actor: "SIMULATOR",
      sequence: 8,
      resultingState: "awaiting_supervision",
    })
    expect(state.activeRun?.auditEvents).toHaveLength(9)
  })

  it("replays the same fixture and action sequence byte-for-byte", () => {
    expect(replay("guided-certifiable-v1", CERTIFIABLE_PATH)).toEqual(
      replay("guided-certifiable-v1", CERTIFIABLE_PATH),
    )
  })

  it("audits a rejected action without mutating domain state", () => {
    const before = activate("guided-certifiable-v1")
    const result = applyDemoAction(before, { type: "APPROVE_PROPOSAL" })
    expect(result.accepted).toBe(false)
    expect(result.state.activeRun).toMatchObject({
      lifecycle: "observing",
      evidenceCursor: 0,
      schedulerStatus: "running",
      emergencyStop: false,
      certificate: null,
      order: null,
      fill: null,
    })
    expect(result.state.activeRun?.auditEvents.at(-1)).toMatchObject({
      action: "APPROVE_PROPOSAL",
      outcome: "REJECTED",
      priorState: "observing",
      resultingState: "observing",
      actor: "PUBLIC_DEMO_USER",
    })
  })

  it.each([
    {
      name: "observing / ADVANCE_EVIDENCE",
      state: () => activate("guided-certifiable-v1"),
      action: { type: "ADVANCE_EVIDENCE" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "observing", evidenceCursor: 1 })
      },
    },
    {
      name: "observing / COMPLETE_FORECAST after all evidence",
      state: () => replay("guided-certifiable-v1", [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      ]),
      action: { type: "COMPLETE_FORECAST" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("forecasted")
      },
    },
    {
      name: "forecasted / COMPLETE_ARGUMENT on certifiable fixture",
      state: () => replay("guided-certifiable-v1", [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
        { type: "COMPLETE_FORECAST" },
      ]),
      action: { type: "COMPLETE_ARGUMENT" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.event).toMatchObject({ resultingState: "argued" })
        expect(result.state.activeRun?.lifecycle).toBe("awaiting_supervision")
      },
    },
    {
      name: "forecasted / COMPLETE_ARGUMENT on veto fixture",
      state: () => replay("guided-catalyst-veto-v1", [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
        { type: "COMPLETE_FORECAST" },
      ]),
      action: { type: "COMPLETE_ARGUMENT" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.completedRunId).toBe("run-0001")
        expect(result.state.activeRun).toBeNull()
        expect(result.state.runHistory.at(-1)).toMatchObject({ lifecycle: "vetoed" })
      },
    },
    {
      name: "argued / REQUEST_SUPERVISION",
      state: () => envelopeWithRun({
        ...runAt("argued"),
        argument: "BASE",
        candidate: getFixture("guided-certifiable-v1").candidate,
        riskGate: getFixture("guided-certifiable-v1").riskGate,
      }),
      action: { type: "REQUEST_SUPERVISION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("awaiting_supervision")
      },
    },
    {
      name: "awaiting_supervision / APPROVE_PROPOSAL",
      state: certifiableToAwaiting,
      action: { type: "APPROVE_PROPOSAL" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "certified", certificate: expect.any(Object) })
      },
    },
    {
      name: "awaiting_supervision / VETO_PROPOSAL",
      state: certifiableToAwaiting,
      action: { type: "VETO_PROPOSAL" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.completedRunId).toBe("run-0001")
        expect(result.state.activeRun).toBeNull()
        expect(result.state.runHistory.at(-1)?.lifecycle).toBe("vetoed")
      },
    },
    {
      name: "certified / SIMULATE_SUBMIT",
      state: () => replay("guided-certifiable-v1", CERTIFIABLE_PATH),
      action: { type: "SIMULATE_SUBMIT" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("simulated_submitted")
      },
    },
    {
      name: "simulated_submitted / SIMULATE_WORKING",
      state: () => replay("guided-certifiable-v1", [
        ...CERTIFIABLE_PATH,
        { type: "SIMULATE_SUBMIT" },
      ]),
      action: { type: "SIMULATE_WORKING" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("simulated_working")
      },
    },
    {
      name: "simulated_working / SIMULATE_FILL",
      state: () => replay("guided-certifiable-v1", [
        ...CERTIFIABLE_PATH,
        { type: "SIMULATE_SUBMIT" },
        { type: "SIMULATE_WORKING" },
      ]),
      action: { type: "SIMULATE_FILL" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("simulated_filled")
      },
    },
    {
      name: "simulated_filled / TRIGGER_RECONCILIATION",
      state: certifiableToFilled,
      action: { type: "TRIGGER_RECONCILIATION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("reconciliation_required")
      },
    },
    {
      name: "reconciliation_required / RESOLVE_RECONCILIATION",
      state: certifiableToReconciliationRequired,
      action: { type: "RESOLVE_RECONCILIATION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("reconciled")
      },
    },
    {
      name: "reconciliation_required / FAIL_RECONCILIATION",
      state: certifiableToReconciliationRequired,
      action: { type: "FAIL_RECONCILIATION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("broker_unknown")
      },
    },
    {
      name: "reconciled / CLOSE_POSITION",
      state: certifiableToReconciled,
      action: { type: "CLOSE_POSITION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun?.lifecycle).toBe("closing")
      },
    },
    {
      name: "simulated_filled / CLOSE_POSITION with emergency stop",
      state: () => applyDemoAction(
        certifiableToFilled(),
        { type: "EMERGENCY_STOP" },
      ).state,
      action: { type: "CLOSE_POSITION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "closing", emergencyStop: true })
      },
    },
    {
      name: "broker_unknown / EMERGENCY_STOP then safe CLOSE_POSITION",
      state: () => applyDemoAction(
        certifiableToBrokerUnknown(),
        { type: "EMERGENCY_STOP" },
      ).state,
      action: { type: "CLOSE_POSITION" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "closing", emergencyStop: true })
      },
    },
    {
      name: "closing / COMPLETE_CLOSE",
      state: () => applyDemoAction(certifiableToReconciled(), { type: "CLOSE_POSITION" }).state,
      action: { type: "COMPLETE_CLOSE" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.completedRunId).toBe("run-0001")
        expect(result.state.activeRun).toBeNull()
        expect(result.state.runHistory.at(-1)?.lifecycle).toBe("closed")
      },
    },
    {
      name: "any lifecycle / PAUSE_SCHEDULER",
      state: () => activate("guided-certifiable-v1"),
      action: { type: "PAUSE_SCHEDULER" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "observing", schedulerStatus: "paused" })
      },
    },
    {
      name: "any lifecycle / RESUME_SCHEDULER",
      state: () => applyDemoAction(activate("guided-certifiable-v1"), { type: "PAUSE_SCHEDULER" }).state,
      action: { type: "RESUME_SCHEDULER" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "observing", schedulerStatus: "running" })
      },
    },
    {
      name: "any non-closed lifecycle / EMERGENCY_STOP",
      state: () => activate("guided-certifiable-v1"),
      action: { type: "EMERGENCY_STOP" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state.activeRun).toMatchObject({ lifecycle: "observing", emergencyStop: true })
      },
    },
    {
      name: "any lifecycle / RESET_SCENARIO",
      state: () => replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }]),
      action: { type: "RESET_SCENARIO" } as const,
      assert: (result: ReturnType<typeof applyDemoAction>) => {
        expect(result.accepted).toBe(true)
        expect(result.state).toEqual(createAuthoredSeed())
      },
    },
  ] as const)("transition matrix: $name", ({ state, action, assert }) => {
    assert(applyDemoAction(state(), action))
  })

  it.each([
    "COMPLETE_FORECAST",
    "COMPLETE_ARGUMENT",
    "REQUEST_SUPERVISION",
    "APPROVE_PROPOSAL",
    "VETO_PROPOSAL",
    "SIMULATE_SUBMIT",
    "SIMULATE_WORKING",
    "SIMULATE_FILL",
    "RESUME_SCHEDULER",
    "TRIGGER_RECONCILIATION",
    "RESOLVE_RECONCILIATION",
    "FAIL_RECONCILIATION",
    "CLOSE_POSITION",
    "COMPLETE_CLOSE",
  ] as const)("rejected observing action %s appends only an audit event", (type) => {
    const before = activate("guided-certifiable-v1")
    const domainBefore = before.activeRun
      ? { ...before.activeRun, auditEvents: undefined, lastUpdatedSequence: undefined }
      : null
    const result = applyDemoAction(before, { type })
    const after = result.state.activeRun
      ? { ...result.state.activeRun, auditEvents: undefined, lastUpdatedSequence: undefined }
      : null
    expect(result.accepted).toBe(false)
    expect(after).toEqual(domainBefore)
    expect(result.state.activeRun?.auditEvents.at(-1)).toMatchObject({
      action: type,
      outcome: "REJECTED",
      priorState: "observing",
      resultingState: "observing",
    })
  })

  it("tests the pure reducer directly for a valid action", () => {
    const fixture = getFixture("guided-certifiable-v1")
    const initial = createRun(fixture, 1)
    const result = reduceRun(initial, fixture, { type: "ADVANCE_EVIDENCE" })
    expect(result.accepted).toBe(true)
    expect(result.run).toMatchObject({ lifecycle: "observing", evidenceCursor: 1, lastUpdatedSequence: 1 })
    expect(result.event).toMatchObject({ action: "ADVANCE_EVIDENCE", outcome: "ACCEPTED" })
  })

  it("tests the pure reducer rejection without domain mutation", () => {
    const fixture = getFixture("guided-certifiable-v1")
    const initial = createRun(fixture, 1)
    const result = reduceRun(initial, fixture, { type: "APPROVE_PROPOSAL" })
    const domainBefore = { ...initial, auditEvents: undefined, lastUpdatedSequence: undefined }
    const domainAfter = { ...result.run, auditEvents: undefined, lastUpdatedSequence: undefined }
    expect(result.accepted).toBe(false)
    expect(domainAfter).toEqual(domainBefore)
    expect(result.event).toMatchObject({ outcome: "REJECTED", action: "APPROVE_PROPOSAL" })
  })

  it("supports the action-first pure reducer overload", () => {
    const fixture = getFixture("guided-certifiable-v1")
    const initial = createRun(fixture, 1)
    const result = reduceRun(initial, { type: "ADVANCE_EVIDENCE" }, fixture)
    expect(result.accepted).toBe(true)
    expect(result.run.evidenceCursor).toBe(1)
  })

  it.each([
    ["observing", [{ type: "ADVANCE_EVIDENCE" }], "observing"],
    ["observing", [{ type: "COMPLETE_FORECAST" }], "observing"],
  ] as const)("applies the observing transition row (%s/%s)", (_source, actions, expected) => {
    const result = applyDemoAction(activate("guided-certifiable-v1"), actions[0])
    expect(result.state.activeRun?.lifecycle).toBe(expected)
    expect(result.accepted).toBe(actions[0].type === "ADVANCE_EVIDENCE")
  })

  it("requires all authored evidence before recording the forecast", () => {
    const state = replay("guided-certifiable-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" },
    ])
    expect(state.activeRun?.lifecycle).toBe("forecasted")
    expect(state.activeRun?.evidenceCursor).toBe(5)
    expect(state.activeRun?.forecast).toEqual(expect.objectContaining({ rationale: expect.objectContaining({ recommendation: "BASE" }) }))
  })

  it("records a BASE argument and immediately dispatches supervision", () => {
    const state = certifiableToAwaiting()
    expect(state.activeRun?.lifecycle).toBe("awaiting_supervision")
    expect(state.activeRun?.argument).toBe("BASE")
    expect(state.activeRun?.candidate?.symbol).toBe("SPY")
    expect(state.activeRun?.riskGate?.output).toBe("PASS")
    expect(state.activeRun?.auditEvents.slice(-2)).toMatchObject([
      { action: "COMPLETE_ARGUMENT", resultingState: "argued", actor: "PUBLIC_DEMO_USER" },
      { action: "REQUEST_SUPERVISION", resultingState: "awaiting_supervision", actor: "SIMULATOR" },
    ])
  })

  it("takes the authored veto branch with no candidate or order", () => {
    const state = replay("guided-catalyst-veto-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" },
      { type: "COMPLETE_ARGUMENT" },
    ])
    expect(state.activeRun).toBeNull()
    expect(state.runHistory.at(-1)).toMatchObject({
      lifecycle: "vetoed",
      argument: "VETO",
      candidate: null,
      certificate: null,
      order: null,
      fill: null,
      reconciliation: null,
      close: null,
    })
    expect(state.runHistory.at(-1)?.auditEvents.at(-1)).toMatchObject({
      action: "COMPLETE_ARGUMENT",
      outcome: "ACCEPTED",
      resultingState: "vetoed",
    })
  })

  it.each([
    ["awaiting_supervision", "APPROVE_PROPOSAL", "certified"],
    ["awaiting_supervision", "VETO_PROPOSAL", "vetoed"],
  ] as const)("handles the supervision row %s/%s", (_source, action, expected) => {
    const state = certifiableToAwaiting()
    const result = applyDemoAction(state, { type: action })
    expect(result.accepted).toBe(true)
    expect(action === "VETO_PROPOSAL" ? result.state.activeRun : result.state.activeRun?.lifecycle).toBe(
      action === "VETO_PROPOSAL" ? null : expected,
    )
    if (action === "APPROVE_PROPOSAL") {
      expect(result.state.activeRun?.certificate).not.toBeNull()
    } else {
      expect(result.state.runHistory.at(-1)?.certificate).toBeNull()
      expect(result.state.runHistory.at(-1)?.order).toBeNull()
      expect(result.completedRunId).toBe("run-0001")
    }
  })

  it("runs the approval, submission, fill, reconciliation, and normal close rows", () => {
    const state = replay("guided-certifiable-v1", [
      ...CERTIFIABLE_PATH,
      { type: "SIMULATE_SUBMIT" },
      { type: "SIMULATE_WORKING" },
      { type: "SIMULATE_FILL" },
      { type: "TRIGGER_RECONCILIATION" },
      { type: "RESOLVE_RECONCILIATION" },
      { type: "CLOSE_POSITION" },
      { type: "COMPLETE_CLOSE" },
    ])
    expect(state.activeRun).toBeNull()
    expect(state.runHistory.at(-1)).toMatchObject({
      lifecycle: "closed",
      order: expect.objectContaining({ quantity: 1 }),
      fill: expect.objectContaining({ credit: 1.9 }),
      reconciliation: expect.objectContaining({ result: "RECONCILED" }),
      close: expect.objectContaining({ lifecycle: "CLOSED", pnl: null }),
    })
  })

  it("supports both reconciliation outcomes and fails closed", () => {
    const resolved = replay("guided-certifiable-v1", [
      ...CERTIFIABLE_PATH,
      { type: "SIMULATE_SUBMIT" },
      { type: "SIMULATE_WORKING" },
      { type: "SIMULATE_FILL" },
      { type: "TRIGGER_RECONCILIATION" },
      { type: "RESOLVE_RECONCILIATION" },
    ])
    expect(resolved.activeRun?.lifecycle).toBe("reconciled")
    expect(resolved.activeRun?.reconciliation?.correctedLeg.quantity).toBe(1)

    const failed = replay("guided-certifiable-v1", [
      ...CERTIFIABLE_PATH,
      { type: "SIMULATE_SUBMIT" },
      { type: "SIMULATE_WORKING" },
      { type: "SIMULATE_FILL" },
      { type: "TRIGGER_RECONCILIATION" },
      { type: "FAIL_RECONCILIATION" },
    ])
    expect(failed.activeRun?.lifecycle).toBe("broker_unknown")
    expect(applyDemoAction(failed, { type: "CLOSE_POSITION" }).accepted).toBe(false)
  })

  it("pauses and resumes without changing lifecycle or losing evidence", () => {
    const observed = replay("guided-certifiable-v1", [
      { type: "ADVANCE_EVIDENCE" },
      { type: "PAUSE_SCHEDULER" },
    ])
    expect(observed.activeRun).toMatchObject({ lifecycle: "observing", evidenceCursor: 1, schedulerStatus: "paused" })
    const resumed = applyDemoAction(observed, { type: "RESUME_SCHEDULER" })
    expect(resumed.state.activeRun).toMatchObject({ lifecycle: "observing", evidenceCursor: 1, schedulerStatus: "running" })
  })

  it("keeps emergency stop orthogonal and permits only safe close from filled or unknown", () => {
    const stopped = applyDemoAction(certifiableToFilled(), { type: "EMERGENCY_STOP" }).state
    expect(stopped.activeRun).toMatchObject({ lifecycle: "simulated_filled", emergencyStop: true })
    expect(applyDemoAction(stopped, { type: "SIMULATE_SUBMIT" }).accepted).toBe(false)
    expect(applyDemoAction(stopped, { type: "TRIGGER_RECONCILIATION" }).accepted).toBe(true)

    const safeClosed = replay("guided-certifiable-v1", [
      ...CERTIFIABLE_PATH,
      { type: "SIMULATE_SUBMIT" },
      { type: "SIMULATE_WORKING" },
      { type: "SIMULATE_FILL" },
      { type: "EMERGENCY_STOP" },
      { type: "CLOSE_POSITION" },
      { type: "COMPLETE_CLOSE" },
    ])
    expect(safeClosed.activeRun).toBeNull()
    expect(safeClosed.runHistory.at(-1)).toMatchObject({ lifecycle: "closed", emergencyStop: true, close: expect.any(Object) })
  })

  it("archives only terminal runs when activating another scenario", () => {
    const vetoed = replay("guided-catalyst-veto-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" },
      { type: "COMPLETE_ARGUMENT" },
    ])
    const activated = activateScenario(vetoed, "guided-certifiable-v1")
    expect(activated.blocked).toBe(false)
    expect(activated.state).toMatchObject({
      nextRunNumber: 3,
      activeRun: { runId: "run-0002", lifecycle: "observing", scenarioId: "guided-certifiable-v1" },
      runHistory: [expect.objectContaining({ runId: "run-0001", lifecycle: "vetoed" })],
    })

    const blocked = activateScenario(activated.state, "guided-catalyst-veto-v1")
    expect(blocked).toMatchObject({ blocked: true, runId: "run-0002" })
  })

  it("selects an already-active scenario without creating another run", () => {
    const state = replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }])
    const selected = activateScenario(state, "guided-certifiable-v1")
    expect(selected).toEqual({ state, runId: "run-0001", blocked: false })
  })

  it("caps each run at 200 audit events while retaining deterministic sequence numbers", () => {
    let state = activate("guided-certifiable-v1")
    for (let index = 0; index < 201; index += 1) {
      state = applyDemoAction(state, {
        type: index % 2 === 0 ? "PAUSE_SCHEDULER" : "RESUME_SCHEDULER",
      }).state
    }
    expect(state.activeRun?.auditEvents).toHaveLength(200)
    expect(state.activeRun?.auditEvents[0]?.sequence).toBe(2)
    expect(state.activeRun?.auditEvents.at(-1)?.sequence).toBe(201)
    expect(state.activeRun?.lastUpdatedSequence).toBe(201)
  })

  it("caps immutable history at the 20 most recent completed runs", () => {
    let state = replay("guided-catalyst-veto-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" },
      { type: "COMPLETE_ARGUMENT" },
    ])
    for (let index = 0; index < 21; index += 1) {
      const next = activateScenario(state, index % 2 === 0 ? "guided-certifiable-v1" : "guided-catalyst-veto-v1")
      expect(next.blocked).toBe(false)
      state = next.state
      const scenarioId = state.activeRun?.scenarioId
      if (scenarioId === "guided-certifiable-v1") {
        state = replayFrom(state, [
          ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
          { type: "COMPLETE_FORECAST" },
          { type: "COMPLETE_ARGUMENT" },
          { type: "APPROVE_PROPOSAL" },
          { type: "SIMULATE_SUBMIT" },
          { type: "SIMULATE_WORKING" },
          { type: "SIMULATE_FILL" },
          { type: "TRIGGER_RECONCILIATION" },
          { type: "RESOLVE_RECONCILIATION" },
          { type: "CLOSE_POSITION" },
          { type: "COMPLETE_CLOSE" },
        ])
      } else {
        state = replayFrom(state, [
          ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
          { type: "COMPLETE_FORECAST" },
          { type: "COMPLETE_ARGUMENT" },
        ])
      }
    }
    const finalActivation = activateScenario(state, "guided-certifiable-v1")
    expect(finalActivation.blocked).toBe(false)
    expect(finalActivation.state.runHistory).toHaveLength(20)
    expect(finalActivation.state.runHistory[0]?.runId).toBe("run-0003")
    expect(finalActivation.state.runHistory.at(-1)?.runId).toBe("run-0022")
  })

  it("resets to the authored certifiable run and clears history", () => {
    const progressed = replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }])
    const result = applyDemoAction(progressed, { type: "RESET_SCENARIO" })
    expect(result.accepted).toBe(true)
    expect(result.state).toEqual(createAuthoredSeed())
  })
})

function replayFrom(state: DemoEnvelope, actions: readonly DemoAction[]): DemoEnvelope {
  let next = state
  for (const action of actions) {
    next = applyDemoAction(next, action).state
  }
  return next
}
