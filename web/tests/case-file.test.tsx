import { render, screen, waitFor, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { PerformanceSummary } from "../src/components/PerformanceSummary"
import { CaseFile } from "../src/components/CaseFile"
import { RiskCertificate } from "../src/components/RiskCertificate"
import { LiveCaseUpdates } from "../src/components/LiveCaseUpdates"
import { OrderLifecycle } from "../src/components/OrderLifecycle"
import { ARCHIVED_CASE } from "../src/lib/archive"

const testRouter = vi.hoisted(() => ({ refresh: vi.fn() }))
const testPathname = vi.hoisted(() => ({ value: "/cases/current" }))
vi.mock("next/navigation", () => ({
  useRouter: () => testRouter,
  usePathname: () => testPathname.value,
}))

describe("Case File", () => {
  it("renders an abstention as a complete case", () => {
    render(<CaseFile data={ARCHIVED_CASE} />)
    expect(screen.getByRole("heading", { name: /abstain from the trade/i })).toBeVisible()
    expect(screen.getByText("CATALYST_VETO")).toBeInTheDocument()
    expect(screen.getByText(/paper endpoint only/i)).toBeVisible()
  })

  it("never presents paper pnl as live money", () => {
    render(<PerformanceSummary performance={{ realizedPnl: "0", totalReturn: "0.00%", drawdown: "0.00%", provenance: "Competition paper ledger" }} />)
    expect(screen.getByText(/simulated paper outcomes/i)).toBeVisible()
  })

  it("uses historical copy for backtest performance", () => {
    render(<PerformanceSummary mode="BACKTEST" performance={{ realizedPnl: "0", totalReturn: "0.00%", drawdown: "0.00%", provenance: "Backtest ledger" }} />)
    expect(screen.getByText(/historical backtest outputs/i)).toBeVisible()
    expect(screen.queryByText(/simulated paper outcomes/i)).not.toBeInTheDocument()
  })

  it("exposes console routes as tabs in the shared masthead", () => {
    render(<CaseFile data={{ ...ARCHIVED_CASE, caseId: "99999999-9999-9999-9999-999999999999" }} liveUpdates={false} />)
    const consoleNav = screen.getByRole("navigation", { name: "Console routes" })
    expect(within(consoleNav).getByRole("link", { name: "Live case" })).toHaveAttribute("href", "/cases/current")
    expect(within(consoleNav).getByRole("link", { name: "Case archive" })).toHaveAttribute("href", "/cases")
  })

  it("marks the active console route in the shared tab bar", () => {
    testPathname.value = "/cases"
    render(<CaseFile data={ARCHIVED_CASE} isArchive liveUpdates={false} />)
    const consoleNav = screen.getByRole("navigation", { name: "Console routes" })
    expect(within(consoleNav).getByRole("link", { name: "Case archive" })).toHaveAttribute("aria-current", "page")
  })

  it("labels order lifecycle copy as simulated in backtest mode", () => {
    render(<OrderLifecycle mode="BACKTEST" steps={ARCHIVED_CASE.orderLifecycle} />)
    expect(screen.getByRole("heading", { name: /simulated order lifecycle/i })).toBeVisible()
    expect(screen.getByText(/backtest projection/i)).toBeVisible()
  })

  it("visibly labels an archived fixture when the public API is unavailable", () => {
    render(<CaseFile data={ARCHIVED_CASE} fixtureNotice="Archived demo fixture data - public read API unavailable." />)
    expect(screen.getByText(/archived demo fixture data/i)).toBeVisible()
  })
  it("announces when live updates cannot be connected", () => {
    render(<CaseFile data={ARCHIVED_CASE} liveUpdates />)
    expect(screen.getByRole("status", { name: /live updates unavailable/i })).toBeInTheDocument()
  })

  it("explains when a case has no recorded evidence or forecast", () => {
    render(<CaseFile data={{ ...ARCHIVED_CASE, evidence: [], forecast: { nodes: [], artifactHash: "no-recorded-forecast" } }} liveUpdates={false} />)
    expect(screen.getByText(/no recorded evidence/i)).toBeInTheDocument()
    expect(screen.getByText(/no recorded forecast/i)).toBeInTheDocument()
  })

  it("distinguishes an awaiting certificate from a refused certificate", () => {
    render(<RiskCertificate certificate={{ status: "not-issued", policyVersion: "v1" }} verdict="PENDING" />)

    expect(screen.getByRole("heading", { name: /risk certificate pending/i })).toBeVisible()
    expect(screen.getByText(/awaiting deterministic risk gate/i)).toBeVisible()
  })

  it("labels a halted certificate separately from a refusal", () => {
    render(<RiskCertificate certificate={{ status: "not-issued", policyVersion: "v1" }} verdict="HALTED" />)

    expect(screen.getByRole("heading", { name: /risk certificate unavailable/i })).toBeVisible()
    expect(screen.getByText(/safety halt/i)).toBeVisible()
  })

  it("fails closed when the case state cannot establish certificate status", () => {
    render(<RiskCertificate certificate={{ status: "not-issued", policyVersion: "v1" }} verdict="PENDING" caseState="UNEXPECTED" />)

    expect(screen.getByRole("heading", { name: /risk certificate state unknown/i })).toBeVisible()
    expect(screen.getByText(/certificate status cannot be established/i)).toBeVisible()
  })

  it("fails closed when an issued certificate has no case state", () => {
    render(<RiskCertificate certificate={{ status: "issued", policyVersion: "v1" }} verdict="CERTIFIED" />)

    expect(screen.getByRole("heading", { name: /risk certificate state unknown/i })).toBeVisible()
  })

  it("shows the evidence state as visible text", () => {
    render(<CaseFile data={ARCHIVED_CASE} />)

    expect(screen.getAllByText("warning").length).toBeGreaterThan(0)
  })

  it("closes the event stream after bounded connection failures", async () => {
    const sources: Array<{ onerror?: () => void; close: ReturnType<typeof vi.fn>; addEventListener: ReturnType<typeof vi.fn> }> = []
    class FakeEventSource {
      onerror?: () => void
      close = vi.fn()
      addEventListener = vi.fn()
      constructor() {
        sources.push(this)
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource)

    render(<LiveCaseUpdates />)
    sources[0].onerror?.()
    sources[0].onerror?.()
    sources[0].onerror?.()
    sources[0].onerror?.()

    expect(sources[0].close).toHaveBeenCalled()
    expect(sources[0].addEventListener).toHaveBeenCalledWith("close", expect.any(Function))
    expect(sources[0].addEventListener).toHaveBeenCalledWith("stream-complete", expect.any(Function))
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/automatic retries exhausted|keeping the last recorded case/i))
  })

  it("treats finite stream completion as an availability fallback", async () => {
    const handlers: Record<string, () => void> = {}
    const sources: Array<{ close: ReturnType<typeof vi.fn> }> = []
    class FakeEventSource {
      close = vi.fn()
      addEventListener = vi.fn((name: string, handler: () => void) => { handlers[name] = handler })
      constructor() {
        sources.push(this)
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource)

    render(<LiveCaseUpdates />)
    handlers["stream-complete"]?.()

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/finite event stream completed|checking public case availability/i))
    expect(sources[0].close).toHaveBeenCalled()
    expect(testRouter.refresh).not.toHaveBeenCalled()
  })

  it("does not refresh into fixture data when the public case refresh fails", async () => {
    const sources: Array<{ onmessage?: () => void; close: ReturnType<typeof vi.fn>; addEventListener: ReturnType<typeof vi.fn> }> = []
    class FakeEventSource {
      onmessage?: () => void
      close = vi.fn()
      addEventListener = vi.fn()
      constructor() {
        sources.push(this)
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource)
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))

    render(<LiveCaseUpdates />)
    sources[0].onmessage?.()

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/unavailable/i))
    expect(testRouter.refresh).not.toHaveBeenCalled()
  })
})
