import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ActionConfirmation } from "../src/components/ActionConfirmation"
import { AuditLog } from "../src/components/AuditLog"
import { EnvironmentDisclosure } from "../src/components/EnvironmentDisclosure"
import { ScenarioControls } from "../src/components/ScenarioControls"
import { ScenarioReset } from "../src/components/ScenarioReset"
import { SimulatorProvider, useSimulatorSelector } from "../src/components/SimulatorProvider"
import { ConsoleShell } from "../src/components/ConsoleShell"
import { OperationsOverview } from "../src/components/OperationsOverview"
import { StructuredRationale } from "../src/components/StructuredRationale"
import { createDemoStore } from "../src/lib/simulator/store"
import { createPersistence } from "../src/lib/simulator/persistence"
import { createRun, getFixture } from "../src/lib/simulator/fixtures"
import { selectActiveRun } from "../src/lib/simulator/selectors"
import type { DemoActionType, DemoRun } from "../src/lib/simulator/types"

const DISCLOSURE = "GUIDED DEMO · SYNTHETIC · BROWSER-LOCAL · NO ALPACA CALLS"

function createStore() {
  return createDemoStore(createPersistence(null))
}

function StoreDrivenControls({
  store,
  onAction,
}: {
  store: ReturnType<typeof createStore>
  onAction?: (action: DemoActionType) => void
}) {
  const run = useSimulatorSelector(selectActiveRun)
  return <ScenarioControls run={run} onAction={onAction} />
}

function awaitingRun(): DemoRun {
  const fixture = getFixture("guided-certifiable-v1")
  return {
    ...createRun(fixture, 1),
    lifecycle: "awaiting_supervision",
    argument: "BASE",
    candidate: fixture.candidate,
    riskGate: fixture.riskGate,
  }
}

describe("simulator components", () => {
  it("surfaces persistence failures in the overview instead of claiming versioned availability", () => {
    const store = createStore()

    render(
      <SimulatorProvider store={store}>
        <ConsoleShell><OperationsOverview /></ConsoleShell>
      </SimulatorProvider>,
    )

    expect(screen.getByText(/persistence unavailable/i)).toBeVisible()
    expect(screen.queryByText(/available.*versioned/i)).not.toBeInTheDocument()
  })

  it("surfaces a persisted-data reset notice with the authored-seed status", () => {
    const store = createDemoStore(createPersistence({
      getItem: () => "not-json",
      setItem: () => undefined,
      removeItem: () => undefined,
    }))

    render(
      <SimulatorProvider store={store}>
        <ConsoleShell><OperationsOverview /></ConsoleShell>
      </SimulatorProvider>,
    )

    expect(screen.getByText(/saved demo data was invalid/i)).toBeVisible()
    expect(within(document.querySelector(".overview-status") as HTMLElement).getByText(/reset.*authored seed/i)).toBeVisible()
  })

  it("discloses the synthetic browser-local environment and explains disabled actions", () => {
    const store = createStore()

    render(
      <SimulatorProvider store={store}>
        <StoreDrivenControls store={store} />
      </SimulatorProvider>,
    )

    expect(screen.getByText(DISCLOSURE)).toBeVisible()
    expect(screen.getByRole("button", { name: /approve proposal/i })).toBeDisabled()
    expect(screen.getByText(/complete all authored evidence before recording the forecast/i)).toBeVisible()
  })

  it("keeps structured rationale before the expandable technical audit log", () => {
    const rationale = getFixture("guided-certifiable-v1").forecast.rationale
    const event = {
      sequence: 1,
      timestamp: "2026-08-31T14:00:01.000Z",
      action: "ADVANCE_EVIDENCE" as const,
      priorState: "observing" as const,
      resultingState: "observing" as const,
      actor: "PUBLIC_DEMO_USER" as const,
      summary: "Evidence item 1 accepted",
      outcome: "ACCEPTED" as const,
    }

    render(
      <main>
        <StructuredRationale rationale={rationale} />
        <AuditLog events={[event]} />
      </main>,
    )

    const rationaleHeading = screen.getByRole("heading", { name: /structured rationale/i })
    const auditSummary = screen.getByText(/technical audit log/i)
    expect(rationaleHeading.compareDocumentPosition(auditSummary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText(rationale.thesis)).toBeVisible()
    expect(screen.getByText(/evidence item 1 accepted/i)).not.toBeVisible()
    expect(screen.getByText(/technical audit log/i)).toBeInTheDocument()
  })

  it("opens a labelled confirmation dialog with initial focus and inert background", () => {
    const run = awaitingRun()
    const onAction = vi.fn()

    render(
      <SimulatorProvider store={createStore()}>
        <ScenarioControls run={run} onAction={onAction} />
      </SimulatorProvider>,
    )

    const approve = screen.getByRole("button", { name: /approve proposal/i })
    approve.focus()
    fireEvent.click(approve)

    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAccessibleName(/approve proposal/i)
    expect(dialog).toHaveAccessibleDescription(/synthetic and browser-local/i)
    expect(screen.getByRole("heading", { name: /approve proposal/i })).toBeVisible()
    expect(screen.getByText(/move the run to certified/i)).toBeVisible()
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus()

    const background = document.querySelector("[data-simulator-background]") as HTMLElement
    expect(background.inert).toBe(true)
  })

  it("traps Tab and Shift+Tab, cancels on Escape, and restores invoking focus", () => {
    const run = awaitingRun()
    render(
      <SimulatorProvider store={createStore()}>
        <ScenarioControls run={run} />
      </SimulatorProvider>,
    )

    const approve = screen.getByRole("button", { name: /approve proposal/i })
    approve.focus()
    fireEvent.click(approve)
    const dialog = screen.getByRole("dialog")
    const cancel = screen.getByRole("button", { name: "Cancel" })
    const confirm = screen.getByRole("button", { name: /confirm approve proposal/i })

    confirm.focus()
    fireEvent.keyDown(dialog, { key: "Tab" })
    expect(cancel).toHaveFocus()
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true })
    expect(confirm).toHaveFocus()

    fireEvent.keyDown(dialog, { key: "Escape" })
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(approve).toHaveFocus()
    expect((document.querySelector("[data-simulator-background]") as HTMLElement).inert).toBe(false)
  })

  it("confirms an action and announces concise live feedback", () => {
    const run = awaitingRun()
    const onAction = vi.fn()
    render(
      <SimulatorProvider store={createStore()}>
        <ScenarioControls run={run} onAction={onAction} />
      </SimulatorProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: /approve proposal/i }))
    fireEvent.click(screen.getByRole("button", { name: /confirm approve proposal/i }))

    expect(onAction).toHaveBeenCalledWith("APPROVE_PROPOSAL")
    expect(screen.getByRole("status")).toHaveTextContent(/approve proposal requested.*synthetic browser-local simulator/i)
  })

  it("uses the stable fallback when a confirmed consequential trigger stays connected but becomes disabled", () => {
    const store = createStore()
    act(() => {
      for (const action of [
        ...Array(5).fill({ type: "ADVANCE_EVIDENCE" as const }),
        { type: "COMPLETE_FORECAST" as const },
        { type: "COMPLETE_ARGUMENT" as const },
      ]) store.dispatch(action)
    })

    render(
      <SimulatorProvider store={store}>
        <div data-dialog-focus-fallback="true" tabIndex={-1}>Decision room fallback</div>
        <StoreDrivenControls store={store} />
      </SimulatorProvider>,
    )

    const approve = screen.getByRole("button", { name: "Approve proposal" })
    approve.focus()
    fireEvent.click(approve)
    fireEvent.click(screen.getByRole("button", { name: "Confirm Approve proposal" }))

    expect(approve).toBeDisabled()
    expect(screen.getByText("Decision room fallback")).toHaveFocus()
  })

  it("uses the stable fallback when a connected trigger loses its tab order", () => {
    const fallback = <div data-dialog-focus-fallback="true" tabIndex={-1}>Decision room fallback</div>
    const { rerender } = render(
      <>
        <button type="button">Trigger</button>
        {fallback}
        <ActionConfirmation open={false} action="APPROVE_PROPOSAL" onConfirm={vi.fn()} onCancel={vi.fn()} />
      </>,
    )

    const trigger = screen.getByRole("button", { name: "Trigger" })
    trigger.focus()
    rerender(
      <>
        <button type="button">Trigger</button>
        {fallback}
        <ActionConfirmation open action="APPROVE_PROPOSAL" invokingElement={trigger} onConfirm={vi.fn()} onCancel={vi.fn()} />
      </>,
    )

    trigger.tabIndex = -1
    rerender(
      <>
        <button type="button" tabIndex={-1}>Trigger</button>
        {fallback}
        <ActionConfirmation open={false} action="APPROVE_PROPOSAL" invokingElement={trigger} onConfirm={vi.fn()} onCancel={vi.fn()} />
      </>,
    )

    expect(trigger.isConnected).toBe(true)
    expect(screen.getByText("Decision room fallback")).toHaveFocus()
  })

  it("requires confirmation for reset and restores focus to Reset demo", () => {
    const onReset = vi.fn()
    render(
      <SimulatorProvider store={createStore()}>
        <ScenarioReset onReset={onReset} />
      </SimulatorProvider>,
    )

    const reset = screen.getByRole("button", { name: /reset demo/i })
    reset.focus()
    fireEvent.click(reset)
    expect(screen.getByRole("dialog")).toHaveAccessibleName(/reset demo/i)
    expect(screen.getByText(/active run and run history will be cleared/i)).toBeVisible()
    fireEvent.click(screen.getByRole("button", { name: /confirm reset demo/i }))

    expect(onReset).toHaveBeenCalledTimes(1)
    expect(reset).toHaveFocus()
  })

  it("announces reset completion in the live feedback region", () => {
    const store = createStore()
    const onReset = vi.fn()
    render(
      <SimulatorProvider store={store}>
        <ScenarioControls run={store.getSnapshot().activeRun} onReset={onReset} />
      </SimulatorProvider>,
    )

    fireEvent.click(screen.getByRole("button", { name: /advance evidence/i }))
    expect(screen.getByRole("status")).toHaveTextContent(/advance evidence requested/i)

    fireEvent.click(screen.getByRole("button", { name: /reset demo/i }))
    fireEvent.click(screen.getByRole("button", { name: /confirm reset demo/i }))

    expect(onReset).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("status")).toHaveTextContent(/demo reset completed in the synthetic browser-local simulator/i)
  })

  it("renders the disclosure as a reusable standalone component", () => {
    render(<EnvironmentDisclosure />)
    expect(screen.getByText(DISCLOSURE)).toBeVisible()
  })

  it("cancels a directly rendered confirmation dialog from Escape", () => {
    const onCancel = vi.fn()
    render(
      <ActionConfirmation
        open
        action="VETO_PROPOSAL"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    )

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
