import { describe, expect, it, vi } from "vitest"
import { getAccount, getArchivedCase, getLiveCase, getOrders, getPerformanceHistory, getPositions, postControl, postVeto } from "../src/lib/api"
import { ARCHIVED_CASE } from "../src/lib/archive"

describe("public read API fallback", () => {
  it("labels the archived fixture when the public read API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))

    const result = await getLiveCase()

    expect(result.source).toBe("archived_fixture")
    expect(result.notice).toMatch(/fixture data/i)
    expect(result.data.caseId).toBe("44444444-4444-4444-4444-444444444444")
  })

  it("maps a filled projection to managing and preserves every public artifact", async () => {
    const projection = {
      case_id: "55555555-5555-5555-5555-555555555555",
      trading_date: "2026-08-25",
      decision_window: "10:05",
      state: "FILLED",
      underlying: "SPY",
      reason_codes: [],
      artifacts: {
        market_evidence: { source: "ledger", content_hash: "market-hash" },
        forecast_distribution: { nodes: [], content_hash: "forecast-hash" },
        catalyst_assessment: { scenario: "FIXED_SCENARIO", content_hash: "catalyst-hash" },
        trade_certificate: { policy_version: "risk-constitution.v1", content_hash: "certificate-hash" },
        order_event: { broker_state: "filled", order_id: "alpaca-order-1", content_hash: "order-hash" },
      },
      as_of: "2026-08-25T14:10:00Z",
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
    }
    const performance = {
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
      as_of: "2026-08-25T14:10:00Z",
      provenance: "reconciled paper ledger",
      metrics: { realized_pnl: "12.50", total_return: "1.2%" },
    }
    const response = (body: unknown) => ({ ok: true, json: async () => body })
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/api/cases")) return Promise.resolve(response({ items: [projection], next_offset: null }))
      if (url.includes("/api/cases/")) return Promise.resolve(response(projection))
      return Promise.resolve(response(performance))
    }))

    const result = await getLiveCase()

    expect(result.data.verdict).toBe("MANAGING")
    expect(result.data.evidence.map((item) => item.label)).toContain("Order event")
    expect(result.data.orderLifecycle.find((step) => step.label === "Submitted")?.state).toBe("complete")
    expect(result.data.orderLifecycle.find((step) => step.label === "Submitted")?.detail).toMatch(/filled/i)
  })

  it("does not substitute the archived fixture for an unknown case id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))

    await expect(getArchivedCase("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")).rejects.toThrow(/case not found/i)
  })

  it("keeps the known fixture UUID available when the healthy API has no row", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))

    const result = await getArchivedCase(ARCHIVED_CASE.caseId)

    expect(result.source).toBe("archived_fixture")
    expect(result.data.caseId).toBe(ARCHIVED_CASE.caseId)
  })

  it("supports the documented archived fixture route without an API request", async () => {
    const fetcher = vi.fn()
    vi.stubGlobal("fetch", fetcher)

    const result = await getArchivedCase("archived")

    expect(fetcher).not.toHaveBeenCalled()
    expect(result.source).toBe("archived_fixture")
    expect(result.data.caseId).toBe(ARCHIVED_CASE.caseId)
  })

  it("does not infer an order lifecycle from an arbitrary order-named artifact", async () => {
    const projection = {
      case_id: "66666666-6666-6666-6666-666666666666",
      trading_date: "2026-08-25",
      decision_window: "10:05",
      state: "SUBMITTED",
      underlying: "SPY",
      reason_codes: [],
      artifacts: { order_metadata: { status: "filled" }, trade_certificate: { policy_version: "v1" } },
      as_of: "2026-08-25T14:10:00Z",
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
    }
    const performance = {
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
      as_of: "2026-08-25T14:10:00Z",
      provenance: "reconciled paper ledger",
      metrics: {},
    }
    const response = (body: unknown) => ({ ok: true, json: async () => body })
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/api/cases")) return Promise.resolve(response({ items: [projection], next_offset: null }))
      if (url.includes("/api/cases/")) return Promise.resolve(response(projection))
      return Promise.resolve(response(performance))
    }))

    const result = await getLiveCase()

    expect(result.data.verdict).toBe("WORKING")
    expect(result.data.orderLifecycle.find((step) => step.label === "Submitted")?.state).toBe("pending")
  })

  it("keeps active, partial, halted, and unknown states explicit", async () => {
    const performance = {
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
      as_of: "2026-08-25T14:10:00Z",
      provenance: "reconciled paper ledger",
      metrics: {},
    }
    const response = (body: unknown) => ({ ok: true, json: async () => body })
    const projection = (state: string) => ({
      case_id: "88888888-8888-8888-8888-888888888888",
      trading_date: "2026-08-25",
      decision_window: "10:05",
      state,
      underlying: "SPY",
      reason_codes: [],
      artifacts: {},
      as_of: "2026-08-25T14:10:00Z",
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
    })

    for (const [state, verdict] of [["SUBMITTED", "WORKING"], ["REPLACED", "WORKING"], ["PARTIALLY_FILLED", "PARTIAL"], ["RECONCILE_REQUIRED", "HALTED"], ["CORRUPT", "UNKNOWN"]] as const) {
      const current = projection(state)
      vi.stubGlobal("fetch", vi.fn((url: string) => {
        if (url.endsWith("/api/cases")) return Promise.resolve(response({ items: [current], next_offset: null }))
        if (url.includes("/api/cases/")) return Promise.resolve(response(current))
        return Promise.resolve(response(performance))
      }))

      const result = await getLiveCase()

      expect(result.data.verdict).toBe(verdict)
      expect(result.data.caseState).toBe(state)
      if (state === "CORRUPT") expect(result.data.orderLifecycle.find((step) => step.label === "Submitted")?.state).toBe("blocked")
    }
  })

  it("does not call a status-only reconcile artifact a submitted order", async () => {
    const projection = {
      case_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      trading_date: "2026-08-25",
      decision_window: "10:05",
      state: "RECONCILE_REQUIRED",
      underlying: "SPY",
      reason_codes: [],
      artifacts: { execution_record: { state: "SUBMITTED", filled_quantity: 0 } },
      as_of: "2026-08-25T14:10:00Z",
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
    }
    const performance = { environment: "development", mode: "DEVELOPMENT_PAPER", as_of: projection.as_of, provenance: "reconciled paper ledger", metrics: {} }
    const response = (body: unknown) => ({ ok: true, json: async () => body })
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/api/cases")) return Promise.resolve(response({ items: [projection], next_offset: null }))
      if (url.includes("/api/cases/")) return Promise.resolve(response(projection))
      return Promise.resolve(response(performance))
    }))

    const result = await getLiveCase()

    expect(result.data.verdict).toBe("HALTED")
    expect(result.data.orderLifecycle.find((step) => step.label === "Submitted")?.state).toBe("blocked")
  })

  it("retains a valid public case when performance is unavailable", async () => {
    const projection = {
      case_id: "77777777-7777-7777-7777-777777777777",
      trading_date: "2026-08-25",
      decision_window: "10:05",
      state: "CERTIFIED",
      underlying: "SPY",
      reason_codes: [],
      artifacts: { trade_certificate: { policy_version: "v1" } },
      as_of: "2026-08-25T14:10:00Z",
      environment: "development",
      mode: "DEVELOPMENT_PAPER",
    }
    const response = (body: unknown) => ({ ok: true, json: async () => body })
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/api/cases")) return Promise.resolve(response({ items: [projection], next_offset: null }))
      if (url.includes("/api/cases/")) return Promise.resolve(response(projection))
      return Promise.resolve({ ok: false, status: 503, json: async () => ({}) })
    }))

    const result = await getLiveCase()

    expect(result.source).toBe("public_api")
    expect(result.data.caseId).toBe(projection.case_id)
    expect(result.data.performance.realizedPnl).toBe("unknown")
    expect(result.data.performance.totalReturn).toBe("Unknown")
    expect(result.notice).toMatch(/performance/i)
  })

  it("surfaces an API error in the fixture notice", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }))

    const result = await getLiveCase()

    expect(result.source).toBe("archived_fixture")
    expect(result.notice).toMatch(/503/)
    expect(result.notice).toMatch(/no live broker/i)
  })
})

describe("live command-center reads", () => {
  it("maps the account payload without inventing missing fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ACTIVE", equity: "100250", last_equity: "100000", daily_pnl: "250",
        competition_drawdown: "0", buying_power: "200000", options_level: 3, paper_endpoint: true,
      }),
    }))

    const result = await getAccount()

    expect(result.status).toBe("ok")
    if (result.status !== "ok") throw new Error("expected ok")
    expect(result.data.equity).toBe("100250")
    expect(result.data.dailyPnl).toBe("250")
    expect(result.data.optionsLevel).toBe(3)
    expect(result.data.paperEndpoint).toBe(true)
  })

  it.each([
    ["account", () => getAccount()],
    ["positions", () => getPositions()],
    ["orders", () => getOrders()],
    ["history", () => getPerformanceHistory()],
  ] as const)("returns an explicit unavailable state for %s instead of fake numbers", async (_name, reader) => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))

    const result = await reader()

    expect(result.status).toBe("unavailable")
    if (result.status !== "unavailable") throw new Error("expected unavailable")
    expect(result.reason).toMatch(/offline/i)
  })

  it("maps positions and orders rows, dropping malformed entries", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: async () => (String(url).includes("/api/positions")
        ? { positions: [{ symbol: "SPY260904P00640000", quantity: 1, side: "long", unrealized_pnl: "12.50" }, { bogus: true }] }
        : { orders: [{ order_id: "abc", status: "NEW", filled_quantity: 0, average_fill_price: null, client_order_id: "lexguard-entry-1" }, { no_id: 1 }] }),
    })))

    const positions = await getPositions()
    const orders = await getOrders()

    expect(positions.status).toBe("ok")
    if (positions.status !== "ok") throw new Error("expected ok")
    expect(positions.data).toEqual([{ symbol: "SPY260904P00640000", quantity: 1, side: "long", unrealizedPnl: "12.50" }])
    expect(orders.status).toBe("ok")
    if (orders.status !== "ok") throw new Error("expected ok")
    expect(orders.data).toEqual([{ orderId: "abc", status: "NEW", filledQuantity: 0, averageFillPrice: null, clientOrderId: "lexguard-entry-1" }])
  })

  it("drops non-finite equity points instead of charting them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        points: [
          { recorded_at: "2026-09-01T14:05:00+00:00", equity: "100250", daily_pnl: "250", competition_drawdown: "0" },
          { recorded_at: "2026-09-01T14:06:00+00:00", equity: "not-a-number", daily_pnl: "0", competition_drawdown: "0" },
        ],
      }),
    }))

    const result = await getPerformanceHistory()

    expect(result.status).toBe("ok")
    if (result.status !== "ok") throw new Error("expected ok")
    expect(result.data).toHaveLength(1)
    expect(result.data[0]).toEqual({ recordedAt: "2026-09-01T14:05:00+00:00", equity: 100250, dailyPnl: 250, competitionDrawdown: 0 })
  })
})

describe("stop-only operator controls", () => {
  it("sends the token per request as X-Operator-Token and reports success", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal("fetch", fetcher)

    const result = await postControl("pause", "secret-token")

    expect(result.ok).toBe(true)
    const [url, init] = fetcher.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/controls\/pause$/)
    expect(init.method).toBe("POST")
    expect(init.headers["X-Operator-Token"]).toBe("secret-token")
  })

  it("distinguishes a refused token (401) from unconfigured controls (503)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    const unauthorized = await postControl("emergency-stop", "wrong")
    expect(unauthorized).toMatchObject({ ok: false, kind: "unauthorized" })
    expect(unauthorized.ok === false && unauthorized.message).toMatch(/401/)

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    const unconfigured = await postVeto("case-1", "token")
    expect(unconfigured).toMatchObject({ ok: false, kind: "unconfigured" })
    expect(unconfigured.ok === false && unconfigured.message).toMatch(/503/)
  })

  it("does not assume an action happened when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))

    const result = await postControl("resume", "token")

    expect(result).toMatchObject({ ok: false, kind: "failed" })
    expect(result.ok === false && result.message).toMatch(/no action is assumed/i)
  })
})
