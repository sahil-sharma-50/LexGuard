import { describe, expect, it } from "vitest"
import { createAuthoredSeed, getFixture } from "../src/lib/simulator/fixtures"
import {
  DEMO_SCHEMA_VERSION,
  DEMO_STORAGE_KEY,
  createPersistence,
  deserializeEnvelope,
  serializeEnvelope,
} from "../src/lib/simulator/persistence"
import { activateScenario, applyDemoAction } from "../src/lib/simulator/reducer"
import { createDemoStore } from "../src/lib/simulator/store"
import type { DemoAction, DemoEnvelope } from "../src/lib/simulator/types"

function memoryStorage(initial: string | null = null) {
  let value = initial
  return {
    getItem: () => value,
    setItem: (_key: string, next: string) => { value = next },
    removeItem: () => { value = null },
    read: () => value,
  }
}

const throwingStorage = {
  getItem: () => { throw new Error("blocked") },
  setItem: () => { throw new Error("quota") },
  removeItem: () => { throw new Error("blocked") },
}

function replay(scenarioId: "guided-certifiable-v1" | "guided-catalyst-veto-v1", actions: readonly DemoAction[]): DemoEnvelope {
  let state = activateScenario(createAuthoredSeed(), scenarioId).state
  for (const action of actions) state = applyDemoAction(state, action).state
  return state
}

describe("simulator persistence", () => {
  it("uses the exact key and schema version", () => {
    expect(DEMO_STORAGE_KEY).toBe("lexguard:demo:v1")
    expect(DEMO_SCHEMA_VERSION).toBe(1)
  })

  it("round-trips the authored envelope", () => {
    const seed = createAuthoredSeed()
    expect(deserializeEnvelope(serializeEnvelope(seed))).toMatchObject({ state: seed, persistent: true })
  })

  it("resets malformed JSON to the authored seed with a visible notice", () => {
    expect(deserializeEnvelope("not-json")).toMatchObject({
      state: createAuthoredSeed(),
      persistent: true,
      notice: expect.stringMatching(/reset/i),
    })
  })

  it.each([
    ["unsupported schema", { ...createAuthoredSeed(), schemaVersion: 2 }],
    ["missing nested run field", { ...createAuthoredSeed(), activeRun: { ...createAuthoredSeed().activeRun!, evidenceCursor: "0" } }],
    ["evidence cursor outside the selected fixture", { ...createAuthoredSeed(), activeRun: { ...createAuthoredSeed().activeRun!, evidenceCursor: 999 } }],
    ["malformed nested leg", {
      ...createAuthoredSeed(),
      activeRun: {
        ...createAuthoredSeed().activeRun!,
        forecast: null,
        candidate: { ...createAuthoredSeed().activeRun!, candidate: null },
      },
    }],
  ])("rejects %s before hydration", (_name, input) => {
    const result = deserializeEnvelope(JSON.stringify(input))
    expect(result.state).toEqual(createAuthoredSeed())
    expect(result.notice).toMatch(/reset/i)
  })

  it("persists and loads using browser-local storage", () => {
    const storage = memoryStorage()
    const persistence = createPersistence(storage)
    expect(persistence.save(createAuthoredSeed())).toEqual({ persistent: true })
    expect(storage.read()).toContain('"schemaVersion":1')
    expect(persistence.load()).toMatchObject({ state: createAuthoredSeed(), persistent: true })
  })

  it("falls back to memory when storage is unavailable", () => {
    const persistence = createPersistence(throwingStorage)
    expect(persistence.save(createAuthoredSeed())).toEqual({
      persistent: false,
      notice: "Persistence unavailable: progress lasts only in this tab.",
    })
    expect(persistence.load()).toMatchObject({ state: createAuthoredSeed(), persistent: false })
  })

  it("keeps a stable server snapshot and hydrates a client snapshot", () => {
    const storage = memoryStorage()
    const persistence = createPersistence(storage)
    const store = createDemoStore(persistence)
    expect(store.getServerSnapshot()).toBe(store.getServerSnapshot())
    const before = store.getSnapshot()
    expect(store.dispatch({ type: "ADVANCE_EVIDENCE" }).accepted).toBe(true)
    expect(store.getSnapshot()).not.toBe(before)
    const hydrated = createDemoStore(createPersistence(storage))
    expect(hydrated.getSnapshot().activeRun?.evidenceCursor).toBe(1)
  })

  it("notifies subscribers only after a state transition and resets storage", () => {
    const storage = memoryStorage()
    const store = createDemoStore(createPersistence(storage))
    let calls = 0
    const unsubscribe = store.subscribe(() => { calls += 1 })
    store.activateScenario("guided-certifiable-v1")
    expect(calls).toBe(0)
    store.dispatch({ type: "ADVANCE_EVIDENCE" })
    expect(calls).toBe(1)
    store.reset()
    expect(calls).toBe(2)
    expect(storage.read()).toBeNull()
    unsubscribe()
  })

  it("accepts only a valid envelope shape from storage", () => {
    const invalid: DemoEnvelope = { ...createAuthoredSeed(), runHistory: [null as never] }
    const result = deserializeEnvelope(JSON.stringify(invalid))
    expect(result.state).toEqual(createAuthoredSeed())
  })

  it.each([
    {
      name: "nonterminal history entry",
      state: () => {
        const progressed = replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }])
        return { ...progressed, activeRun: null, runHistory: [progressed.activeRun!] }
      },
    },
    {
      name: "terminal active run",
      state: () => {
        const completed = replay("guided-catalyst-veto-v1", [
          ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
          { type: "COMPLETE_FORECAST" as const },
          { type: "COMPLETE_ARGUMENT" as const },
        ]).runHistory.at(-1)!
        return { ...createAuthoredSeed(), activeRun: completed }
      },
    },
  ])("rejects a $name before hydration", ({ state }) => {
    const result = deserializeEnvelope(JSON.stringify(state()))
    expect(result.state).toEqual(createAuthoredSeed())
    expect(result.notice).toMatch(/reset/i)
  })

  it.each([
    {
      name: "an audit sequence gap",
      state: () => {
        const progressed = replay("guided-certifiable-v1", [
          { type: "ADVANCE_EVIDENCE" },
          { type: "PAUSE_SCHEDULER" },
        ])
        const activeRun = progressed.activeRun!
        return {
          ...progressed,
          activeRun: {
            ...activeRun,
            auditEvents: activeRun.auditEvents.map((event, index) => index === 1 ? { ...event, sequence: 3 } : event),
          },
        }
      },
    },
    {
      name: "a stale last-updated sequence",
      state: () => {
        const progressed = replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }])
        return {
          ...progressed,
          activeRun: { ...progressed.activeRun!, lastUpdatedSequence: 0 },
        }
      },
    },
    {
      name: "a reset event in a persisted run",
      state: () => {
        const progressed = replay("guided-certifiable-v1", [{ type: "ADVANCE_EVIDENCE" }])
        return {
          ...progressed,
          activeRun: {
            ...progressed.activeRun!,
            auditEvents: progressed.activeRun!.auditEvents.map((event) => ({ ...event, action: "RESET_SCENARIO" as const })),
          },
        }
      },
    },
  ])("rejects $name before hydration", ({ state }) => {
    const result = deserializeEnvelope(JSON.stringify(state()))
    expect(result.state).toEqual(createAuthoredSeed())
    expect(result.notice).toMatch(/reset/i)
  })

  it("rejects an envelope whose next run number does not follow its runs", () => {
    const completed = replay("guided-catalyst-veto-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" as const },
      { type: "COMPLETE_ARGUMENT" as const },
    ])
    const state = activateScenario(completed, "guided-certifiable-v1").state
    const result = deserializeEnvelope(JSON.stringify({ ...state, nextRunNumber: 99 }))

    expect(result.state).toEqual(createAuthoredSeed())
    expect(result.notice).toMatch(/reset/i)
  })

  it.each([
    {
      name: "an observing run with a forecast",
      state: () => {
        const seed = createAuthoredSeed()
        return {
          ...seed,
          activeRun: { ...seed.activeRun!, forecast: getFixture("guided-certifiable-v1").forecast },
        }
      },
    },
    {
      name: "a normal closing run without reconciliation",
      state: () => {
        const closing = replay("guided-certifiable-v1", [
          ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
          { type: "COMPLETE_FORECAST" as const },
          { type: "COMPLETE_ARGUMENT" as const },
          { type: "APPROVE_PROPOSAL" as const },
          { type: "SIMULATE_SUBMIT" as const },
          { type: "SIMULATE_WORKING" as const },
          { type: "SIMULATE_FILL" as const },
          { type: "TRIGGER_RECONCILIATION" as const },
          { type: "RESOLVE_RECONCILIATION" as const },
          { type: "CLOSE_POSITION" as const },
        ])
        return {
          ...closing,
          activeRun: { ...closing.activeRun!, reconciliation: null, emergencyStop: false },
        }
      },
    },
    {
      name: "a certificate issued after the run's last event",
      state: () => {
        const certified = replay("guided-certifiable-v1", [
          ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
          { type: "COMPLETE_FORECAST" as const },
          { type: "COMPLETE_ARGUMENT" as const },
          { type: "APPROVE_PROPOSAL" as const },
        ])
        const activeRun = certified.activeRun!
        return {
          ...certified,
          activeRun: {
            ...activeRun,
            certificate: { ...activeRun.certificate!, issuedAtSequence: activeRun.lastUpdatedSequence + 1 },
          },
        }
      },
    },
  ])("rejects $name", ({ state }) => {
    const result = deserializeEnvelope(JSON.stringify(state()))

    expect(result.state).toEqual(createAuthoredSeed())
    expect(result.notice).toMatch(/reset/i)
  })

  it("accepts a valid terminal history and active progressed run", () => {
    const completed = replay("guided-catalyst-veto-v1", [
      ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
      { type: "COMPLETE_FORECAST" as const },
      { type: "COMPLETE_ARGUMENT" as const },
    ])
    const state = activateScenario(completed, "guided-certifiable-v1").state
    const result = deserializeEnvelope(JSON.stringify(state))

    expect(result.state).toEqual(state)
    expect(result.notice).toBeUndefined()
  })

  it("rejects persisted history and audit streams beyond their retention caps", () => {
    const seed = createAuthoredSeed()
    const oversizedHistory = {
      ...seed,
      runHistory: Array.from({ length: 21 }, () => seed.activeRun!),
    }
    expect(deserializeEnvelope(JSON.stringify(oversizedHistory)).state).toEqual(seed)

    const event = {
      sequence: 1,
      timestamp: "2026-08-31T14:00:01.000Z",
      action: "ADVANCE_EVIDENCE",
      priorState: "observing",
      resultingState: "observing",
      actor: "PUBLIC_DEMO_USER",
      summary: "Evidence item 1 accepted",
      outcome: "ACCEPTED",
    }
    const oversizedAudit = {
      ...seed,
      activeRun: {
        ...seed.activeRun!,
        auditEvents: Array.from({ length: 201 }, (_, index) => ({ ...event, sequence: index + 1 })),
      },
    }
    expect(deserializeEnvelope(JSON.stringify(oversizedAudit)).state).toEqual(seed)
  })

  it("surfaces remove failures and keeps reset state in memory", () => {
    let value: string | null = null
    const storage = {
      getItem: () => value,
      setItem: (_key: string, next: string) => { value = next },
      removeItem: () => { throw new Error("blocked") },
      read: () => value,
    }
    const persistence = createPersistence(storage)
    const store = createDemoStore(persistence)
    store.dispatch({ type: "ADVANCE_EVIDENCE" })
    store.reset()

    expect(store.getPersistenceNotice()).toBe("Persistence unavailable: progress lasts only in this tab.")
    expect(store.getSnapshot()).toEqual(createAuthoredSeed())
    expect(storage.read()).not.toBeNull()
    expect(createDemoStore(persistence).getSnapshot()).toEqual(createAuthoredSeed())
  })

  it("clears exactly the demo key while retaining unrelated storage", () => {
    const values = new Map<string, string>()
    const removed: string[] = []
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, next: string) => { values.set(key, next) },
      removeItem: (key: string) => { removed.push(key); values.delete(key) },
    }
    values.set("unrelated", "keep")
    const store = createDemoStore(createPersistence(storage))
    store.dispatch({ type: "ADVANCE_EVIDENCE" })
    store.reset()

    expect(removed).toEqual([DEMO_STORAGE_KEY])
    expect(values.get("unrelated")).toBe("keep")
    expect(values.has(DEMO_STORAGE_KEY)).toBe(false)
  })
})
