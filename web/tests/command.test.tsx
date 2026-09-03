import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AccountTiles } from "../src/components/command/AccountTiles"
import { AgentFeed } from "../src/components/command/AgentFeed"
import { LatestArgument } from "../src/components/command/LatestArgument"
import { OperatorBench } from "../src/components/command/OperatorBench"
import { OrdersPanel } from "../src/components/command/OrdersPanel"
import { PositionsTable } from "../src/components/command/PositionsTable"
import type { AccountData, CaseProjection } from "../src/lib/types"

const controls = vi.hoisted(() => ({
  postControl: vi.fn(),
  postVeto: vi.fn(),
}))

vi.mock("../src/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/api")>()
  return { ...actual, postControl: controls.postControl, postVeto: controls.postVeto }
})

const ACCOUNT: AccountData = {
  status: "ACTIVE",
  equity: "100250",
  lastEquity: "100000",
  dailyPnl: "250",
  competitionDrawdown: "0",
  buyingPower: "200000",
  optionsLevel: 3,
  paperEndpoint: true,
}

function pendingCase(overrides: Partial<CaseProjection> = {}): CaseProjection {
  return {
    case_id: "11111111-2222-3333-4444-555555555555",
    trading_date: "2026-09-01",
    decision_window: "10:05",
    state: "ARGUED",
    underlying: "SPY",
    reason_codes: [],
    artifacts: {},
    as_of: "2026-09-01T14:10:00Z",
    environment: "development",
    mode: "COMPETITION_PAPER",
    ...overrides,
  }
}

describe("account tiles", () => {
  it("renders live money values with the drawdown meter against the $4,000 cap", () => {
    render(<AccountTiles account={{ status: "ok", data: ACCOUNT }} />)

    expect(screen.getByText("$100,250.00")).toBeVisible()
    expect(screen.getByText("+$250.00")).toBeVisible()
    expect(screen.getByText("$200,000.00")).toBeVisible()
    const meter = screen.getByRole("meter", { name: /competition drawdown/i })
    expect(meter).toHaveAttribute("aria-valuemax", "4000")
    expect(meter).toHaveAttribute("aria-valuenow", "0")
  })

  it("withholds values instead of inventing them when the account read fails", () => {
    render(<AccountTiles account={{ status: "unavailable", reason: "public read API error: offline." }} />)

    expect(screen.getByRole("status")).toHaveTextContent(/account read unavailable/i)
    expect(screen.getByRole("status")).toHaveTextContent(/withheld rather than estimated/i)
    // No formatted currency amount (e.g. $100,250.00) may appear - only the cap label.
    expect(screen.queryByText(/\$\d[\d,]*\.\d{2}/)).not.toBeInTheDocument()
  })
})

describe("positions and orders", () => {
  it("expands OCC symbols into per-leg detail with signed unrealized P&L", () => {
    render(
      <PositionsTable positions={{ status: "ok", data: [{ symbol: "SPY260904P00640000", quantity: 1, side: "long", unrealizedPnl: "12.50" }] }} />,
    )

    expect(screen.getByText(/SPY put 640 · exp 2026-09-04/)).toBeVisible()
    expect(screen.getByText("+$12.50")).toBeVisible()
  })

  it("shows order status and fill price, and an explicit unavailable state", () => {
    const { rerender } = render(
      <OrdersPanel orders={{ status: "ok", data: [{ orderId: "abc-123-def-456", status: "NEW", filledQuantity: 0, averageFillPrice: null, clientOrderId: "lexguard-entry-1" }] }} />,
    )
    expect(screen.getByText("lexguard-entry-1")).toBeVisible()
    expect(screen.getByText("NEW")).toBeVisible()

    rerender(<OrdersPanel orders={{ status: "unavailable", reason: "offline." }} />)
    expect(screen.getByRole("status")).toHaveTextContent(/orders unavailable/i)
  })
})

describe("agent feed", () => {
  it("renders ledger events chronologically with event-type styling and case links", () => {
    render(
      <AgentFeed
        connection="live"
        events={[
          { id: "2", type: "CERTIFIED", caseId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", timestamp: "2026-09-01T14:05:00Z" },
          { id: "1", type: "ARGUED", caseId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" },
        ]}
      />,
    )

    expect(screen.getByText("CERTIFIED")).toHaveClass("feed-kind-ruling")
    expect(screen.getByText("ARGUED")).toHaveClass("feed-kind-argument")
    expect(screen.getAllByRole("link", { name: /case aaaaaaaa/i })[0]).toHaveAttribute(
      "href",
      "/cases/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    expect(screen.getByRole("status")).toHaveTextContent(/live/i)
  })

  it("says the stream is unavailable without inventing events", () => {
    render(<AgentFeed connection="unavailable" events={[]} />)

    expect(screen.getAllByRole("status")[0]).toHaveTextContent(/unavailable/i)
    expect(screen.getByText(/no events on the record yet/i)).toBeVisible()
  })
})

describe("latest argument", () => {
  it("shows the verbatim rationale, cited news IDs, and the artifact hash prefix", () => {
    const projection = pendingCase({
      artifacts: {
        catalyst_assessment: {
          scenario: "RANGE_HOLD",
          confidence: 0.62,
          rationale: "Implied move overstates realized volatility into a quiet macro window.",
          evidence_ids: ["news-871", "news-882"],
          content_hash: "sha256:deadbeefcafe",
        },
      },
    })
    render(<LatestArgument cases={{ status: "ok", data: [projection] }} />)

    expect(screen.getByText("Implied move overstates realized volatility into a quiet macro window.")).toBeVisible()
    expect(screen.getByText("news-871")).toBeVisible()
    expect(screen.getByText("news-882")).toBeVisible()
    expect(screen.getByText(/artifact sha256:dea/)).toBeVisible()
    expect(screen.getByRole("link", { name: /read the full case file/i })).toHaveAttribute(
      "href",
      `/cases/${projection.case_id}`,
    )
  })
})

describe("operator bench", () => {
  beforeEach(() => {
    controls.postControl.mockReset()
    controls.postVeto.mockReset()
  })

  it("groups the token as the first step before stop-only controls", () => {
    render(<OperatorBench pendingCases={[]} />)

    expect(screen.getByText("1. Arm the bench")).toBeVisible()
    expect(screen.getByText("2. Stop-only controls")).toBeVisible()
  })

  it("shows the stop-only controls disabled with an explanation until a token is entered", () => {
    render(<OperatorBench pendingCases={[]} />)

    for (const name of ["Pause entries", "Resume entries", "Emergency stop"]) {
      expect(screen.getByRole("button", { name: new RegExp(name) })).toBeDisabled()
    }
    expect(screen.getByText(/enter the operator token to arm the bench/i)).toBeVisible()
    expect(screen.getByText(/can never make it trade/i)).toBeVisible()
  })

  it("confirms before posting a control and reports success", async () => {
    controls.postControl.mockResolvedValue({ ok: true, message: "Pause acknowledged." })
    render(<OperatorBench pendingCases={[]} />)

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "secret-token" } })
    fireEvent.click(screen.getByRole("button", { name: /Pause entries/ }))
    expect(screen.getByRole("dialog")).toBeVisible()
    expect(controls.postControl).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("button", { name: "Confirm Pause entries" }))
    await waitFor(() => expect(controls.postControl).toHaveBeenCalledWith("pause", "secret-token"))
    expect(await screen.findByRole("status")).toHaveTextContent(/pause acknowledged/i)
  })

  it("surfaces a refused token (401) as a visible error", async () => {
    controls.postControl.mockResolvedValue({ ok: false, kind: "unauthorized", message: "Token refused (401). Check the operator token and try again; the token is never stored." })
    render(<OperatorBench pendingCases={[]} />)

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "wrong" } })
    fireEvent.click(screen.getByRole("button", { name: /Emergency stop/ }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm Emergency stop" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/token refused \(401\)/i)
  })

  it("surfaces unconfigured server controls (503) as a visible error", async () => {
    controls.postVeto.mockResolvedValue({ ok: false, kind: "unconfigured", message: "Operator controls are not configured on the server (503). No action was taken." })
    render(<OperatorBench pendingCases={[pendingCase()]} />)

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "token" } })
    fireEvent.click(screen.getByRole("button", { name: "Veto" }))
    fireEvent.click(screen.getByRole("button", { name: /Confirm Veto case/ }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/not configured on the server \(503\)/i)
    expect(controls.postVeto).toHaveBeenCalledWith(pendingCase().case_id, "token")
  })

  it("keeps the token in memory only - never in web storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem")
    render(<OperatorBench pendingCases={[]} />)

    fireEvent.change(screen.getByLabelText("Operator token"), { target: { value: "super-secret" } })

    expect(setItem).not.toHaveBeenCalled()
    const input = screen.getByLabelText("Operator token")
    expect(input).toHaveAttribute("type", "password")
    expect(input).toHaveAttribute("autocomplete", "off")
    setItem.mockRestore()
  })
})
