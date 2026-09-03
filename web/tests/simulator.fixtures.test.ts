import { describe, expect, it } from "vitest"
import { createAuthoredSeed, SIMULATOR_FIXTURES } from "../src/lib/simulator/fixtures"

describe("simulator authored fixtures", () => {
  it("encodes the exact certifiable fixture", () => {
    const fixture = SIMULATOR_FIXTURES["guided-certifiable-v1"]
    expect(fixture.forecast.nodes.reduce((sum, node) => sum + node.probability, 0)).toBe(1)
    expect(fixture.candidate?.maxLoss).toBe(310)
    expect(fixture.riskGate.output).toBe("PASS")
    expect(fixture.certificate?.issuedAtSequence).toBe(9)
  })

  it("keeps the veto branch empty beyond argument", () => {
    const fixture = SIMULATOR_FIXTURES["guided-catalyst-veto-v1"]
    expect(fixture.argument).toBe("VETO")
    expect(fixture.candidate).toBeNull()
    expect(fixture.certificate).toBeNull()
  })

  it("creates the authored browser seed", () => {
    expect(createAuthoredSeed()).toMatchObject({
      schemaVersion: 1,
      nextRunNumber: 2,
      activeRun: { runId: "run-0001", scenarioId: "guided-certifiable-v1", lifecycle: "observing" },
      runHistory: [],
    })
  })
})
