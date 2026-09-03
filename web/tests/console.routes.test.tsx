import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CaseQueue } from "../src/components/CaseQueue"
import { ConsoleNavigation } from "../src/components/ConsoleNavigation"
import { ConsoleShell } from "../src/components/ConsoleShell"
import { DecisionRoom } from "../src/components/DecisionRoom"
import { OperationsOverview } from "../src/components/OperationsOverview"
import { SimulatorProvider } from "../src/components/SimulatorProvider"
import { createRun, getFixture } from "../src/lib/simulator/fixtures"
import { createPersistence } from "../src/lib/simulator/persistence"
import { createDemoStore } from "../src/lib/simulator/store"
import type { DemoRun } from "../src/lib/simulator/types"

const testRouter = vi.hoisted(() => ({ replace: vi.fn() }))
vi.mock("next/navigation", () => ({ useRouter: () => testRouter, usePathname: () => "/console" }))

function createStore() {
  return createDemoStore(createPersistence(null))
}

function createUnavailableStore() {
  return createDemoStore(createPersistence({
    getItem: () => { throw new Error("blocked") },
    setItem: () => { throw new Error("blocked") },
    removeItem: () => { throw new Error("blocked") },
  }))
}

function completedRun(): DemoRun {
  const fixture = getFixture("guided-certifiable-v1")
  return {
    ...createRun(fixture, 2),
    lifecycle: "vetoed",
    argument: "VETO",
    lastUpdatedSequence: 1,
    auditEvents: [{
      sequence: 1,
      timestamp: "2026-08-31T14:00:01.000Z",
      action: "VETO_PROPOSAL",
      priorState: "awaiting_supervision",
      resultingState: "vetoed",
      actor: "PUBLIC_DEMO_USER",
      summary: "Proposal vetoed",
      outcome: "ACCEPTED",
    }],
  }
}

describe("console route composition", () => {
  beforeEach(() => {
    testRouter.replace.mockReset()
  })

  it("exposes console navigation and the operations overview", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <ConsoleShell>
          <OperationsOverview />
        </ConsoleShell>
      </SimulatorProvider>,
    )

    expect(screen.getByRole("navigation", { name: /console/i })).toBeVisible()
    expect(screen.getByRole("heading", { name: /operations overview/i })).toBeVisible()
    expect(within(document.querySelector(".case-queue-list") as HTMLElement).getByRole("link", { name: /guided certifiable/i })).toHaveAttribute(
      "href", "/console/decision-room?scenario=guided-certifiable-v1",
    )
  })

  it("renders one shared persistence notice while keeping the overview status truthful", () => {
    const store = createUnavailableStore()
    const { container } = render(
      <SimulatorProvider store={store}>
        <ConsoleShell>
          <OperationsOverview />
        </ConsoleShell>
      </SimulatorProvider>,
    )

    expect(container.querySelector(".console-persistence-notice")).toHaveTextContent(/Persistence unavailable/i)
    expect(screen.getAllByText(/Persistence unavailable/i)).toHaveLength(1)
    expect(screen.getByText(/UNAVAILABLE .* SESSION-ONLY/i)).toBeVisible()
  })

  it.each([
    { name: "decision room", child: <DecisionRoom /> },
    { name: "case queue", child: <CaseQueue /> },
  ])("surfaces the shared persistence notice on the $name deep link", ({ child }) => {
    const store = createUnavailableStore()
    const { container } = render(
      <SimulatorProvider store={store}>
        <ConsoleShell>{child}</ConsoleShell>
      </SimulatorProvider>,
    )

    expect(container.querySelector(".console-persistence-notice")).toHaveTextContent(/Persistence unavailable/i)
    expect(screen.getAllByText(/Persistence unavailable/i)).toHaveLength(1)
  })

  it("keeps structured rationale before the technical event log", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <DecisionRoom />
      </SimulatorProvider>,
    )

    const rationale = screen.getByRole("heading", { name: /structured rationale/i })
    const audit = screen.getByText(/technical event log/i)
    expect(rationale.compareDocumentPosition(audit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("heading", { name: /decision room/i })).toBeVisible()
    for (const label of ["EVIDENCE", "ARGUMENT", "RISK GATE", "BROKER", "VERDICT"]) {
      expect(screen.getByText(label, { exact: true })).toBeVisible()
    }
  })

  it("shows an explicit state for an unknown scenario or run", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <DecisionRoom requestedScenario="not-a-scenario" />
      </SimulatorProvider>,
    )

    expect(screen.getByRole("heading", { name: /scenario not found/i })).toBeVisible()
    expect(screen.getByRole("link", { name: /guided certifiable/i })).toHaveAttribute(
      "href", "/console/decision-room?scenario=guided-certifiable-v1",
    )
  })

  it("does not silently replace a conflicting active scenario", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <DecisionRoom requestedScenario="guided-catalyst-veto-v1" />
      </SimulatorProvider>,
    )

    expect(screen.getByText(/finish or reset the active run first/i)).toBeVisible()
    expect(screen.getByRole("link", { name: /active run run-0001/i })).toHaveAttribute(
      "href", "/console/decision-room?run=run-0001",
    )
  })

  it("renders completed runs as read-only and keeps controls active-run-only", () => {
    const completed = completedRun()
    const historyStore = createStore()
    const historyState = { ...historyStore.getSnapshot(), activeRun: null, runHistory: [completed] }
    // The queue accepts a snapshot so the completed fixture can be exercised
    // without making terminal-history mutation part of this composition test.
    const { container } = render(
      <SimulatorProvider store={historyStore}>
        <CaseQueue state={historyState} />
      </SimulatorProvider>,
    )

    const mobileQueue = within(container.querySelector(".case-queue-list") as HTMLElement)
    expect(mobileQueue.getByRole("link", { name: /run-0002/i })).toHaveAttribute(
      "href", "/console/decision-room?run=run-0002",
    )
    expect(mobileQueue.getByText(/completed.*read-only/i)).toBeVisible()
    expect(screen.queryByRole("button", { name: /advance evidence/i })).not.toBeInTheDocument()
  })

  it("projects every fixture and run row into a captioned table with lifecycle and last action columns", () => {
    const store = createStore()
    const { container } = render(
      <SimulatorProvider store={store}>
        <CaseQueue />
      </SimulatorProvider>,
    )

    const table = container.querySelector(".case-queue-table") as HTMLTableElement
    expect(table).toBeInTheDocument()
    expect(table.querySelector("caption")).toHaveTextContent("Case queue")
    expect(within(table).getByRole("columnheader", { name: "Case" })).toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: "Lifecycle state" })).toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: "Last action" })).toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: "Verdict" })).toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: "Access" })).toBeInTheDocument()

    expect(within(table).getByRole("row", { name: /Guided certifiable observing No action recorded BASE Current active run/i })).toBeInTheDocument()
    expect(within(table).getByRole("row", { name: /Guided catalyst veto not started No action recorded ABSTAIN Authored fixture/i })).toBeInTheDocument()
    expect(within(table).getByRole("row", { name: /Current run run-0001 observing No action recorded PENDING Current · active/i })).toBeInTheDocument()
  })

  it("keeps completed rows read-only while exposing their terminal lifecycle and last action", () => {
    const completed = completedRun()
    const historyStore = createStore()
    const historyState = { ...historyStore.getSnapshot(), activeRun: null, runHistory: [completed] }
    const { container } = render(
      <SimulatorProvider store={historyStore}>
        <CaseQueue state={historyState} />
      </SimulatorProvider>,
    )

    const table = container.querySelector(".case-queue-table") as HTMLTableElement
    expect(within(table).getByRole("row", { name: /Completed run run-0002 vetoed Proposal vetoed ABSTAIN Completed · read-only/i })).toBeInTheDocument()
    expect(within(table).getByRole("link", { name: /run-0002/i })).toHaveAttribute(
      "href", "/console/decision-room?run=run-0002",
    )
  })

  it("keeps authored fixture links and active-run links in the queue", () => {
    const store = createStore()
    const { container } = render(
      <SimulatorProvider store={store}>
        <CaseQueue />
      </SimulatorProvider>,
    )

    const mobileQueue = within(container.querySelector(".case-queue-list") as HTMLElement)
    expect(mobileQueue.getByRole("link", { name: /guided certifiable/i })).toHaveAttribute(
      "href", "/console/decision-room?scenario=guided-certifiable-v1",
    )
    expect(mobileQueue.getByRole("link", { name: /run-0001/i })).toHaveAttribute(
      "href", "/console/decision-room?run=run-0001",
    )
  })

  it("renders controls only when an active run exists", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <ConsoleNavigation />
        <DecisionRoom readOnlyRun={completedRun()} />
      </SimulatorProvider>,
    )

    expect(screen.queryByRole("heading", { name: /supervised demo actions/i })).not.toBeInTheDocument()
    expect(screen.getByText("Read-only completed run; no supervised demo actions are available.")).toBeVisible()
  })

  it("moves focus to the stable decision room landmark after a terminal confirmation", () => {
    const store = createStore()
    render(
      <SimulatorProvider store={store}>
        <DecisionRoom requestedScenario="guided-certifiable-v1" />
      </SimulatorProvider>,
    )

    act(() => {
      for (const action of [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
        { type: "COMPLETE_FORECAST" as const },
        { type: "COMPLETE_ARGUMENT" as const },
      ]) store.dispatch(action)
    })

    const veto = screen.getByRole("button", { name: "Veto proposal" })
    veto.focus()
    fireEvent.click(veto)
    fireEvent.click(screen.getByRole("button", { name: "Confirm Veto proposal" }))

    expect(screen.getByRole("main", { name: "Decision room" })).toHaveFocus()
  })

  it.each([
    {
      name: "vetoed",
      actions: [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
        { type: "COMPLETE_FORECAST" as const },
        { type: "COMPLETE_ARGUMENT" as const },
        { type: "VETO_PROPOSAL" as const },
      ],
    },
    {
      name: "closed",
      actions: [
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
        { type: "COMPLETE_CLOSE" as const },
      ],
    },
  ])("replaces a terminal $name scenario URL with its read-only run URL", ({ actions }) => {
    const store = createStore()
    const replaceState = vi.spyOn(window.history, "replaceState")
    render(
      <SimulatorProvider store={store}>
        <DecisionRoom requestedScenario="guided-certifiable-v1" />
      </SimulatorProvider>,
    )

    act(() => {
      for (const action of actions) store.dispatch(action)
    })
    const completedRunId = store.getSnapshot().runHistory.at(-1)?.runId
    expect(store.getSnapshot().activeRun).toBeNull()
    expect(completedRunId).toBeDefined()

    expect(replaceState).toHaveBeenCalledWith(null, "", `/console/decision-room?run=${completedRunId}`)
    expect(testRouter.replace).not.toHaveBeenCalled()
    expect(screen.getByText("Read-only completed run; no supervised demo actions are available.")).toBeVisible()
    replaceState.mockRestore()
  })
})
