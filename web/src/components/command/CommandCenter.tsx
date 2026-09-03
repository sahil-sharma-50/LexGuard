"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { getAccount, getOrders, getPerformanceHistory, getPositions, getRecentCases } from "../../lib/api"
import { API_BASE_CONFIGURED, API_CONFIG_ERROR } from "../../lib/apiBase"
import { formatTimestamp } from "../../lib/format"
import type { AccountData, CaseProjection, EquityPoint, OrderRow, PositionRow } from "../../lib/types"
import type { PanelData } from "./types"
import { AccountTiles } from "./AccountTiles"
import { AgentFeed } from "./AgentFeed"
import { EquityCurve } from "./EquityCurve"
import { LatestArgument } from "./LatestArgument"
import { OperatorBench } from "./OperatorBench"
import { OrdersPanel } from "./OrdersPanel"
import { PositionsTable } from "./PositionsTable"
import { useLedgerFeed } from "./useLedgerFeed"

const POLL_INTERVAL_MS = 15_000
const EVENT_REFRESH_DEBOUNCE_MS = 1_500

const PENDING_CERTIFICATE_STATES = new Set(["SCHEDULED", "OBSERVED", "FORECASTED", "ARGUED"])

export function CommandCenter() {
  const [account, setAccount] = useState<PanelData<AccountData>>({ status: "loading" })
  const [positions, setPositions] = useState<PanelData<PositionRow[]>>({ status: "loading" })
  const [orders, setOrders] = useState<PanelData<OrderRow[]>>({ status: "loading" })
  const [history, setHistory] = useState<PanelData<EquityPoint[]>>({ status: "loading" })
  const [cases, setCases] = useState<PanelData<CaseProjection[]>>({ status: "loading" })
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const inFlightRef = useRef(false)
  const eventTimerRef = useRef<number | undefined>(undefined)

  const refresh = useCallback(async () => {
    if (typeof document !== "undefined" && document.visibilityState !== "visible") return
    if (inFlightRef.current) return
    inFlightRef.current = true
    try {
      const [nextAccount, nextPositions, nextOrders, nextHistory, nextCases] = await Promise.all([
        getAccount(),
        getPositions(),
        getOrders(),
        getPerformanceHistory(),
        getRecentCases(),
      ])
      setAccount(nextAccount)
      setPositions(nextPositions)
      setOrders(nextOrders)
      setHistory(nextHistory)
      setCases(nextCases)
      if ([nextAccount, nextPositions, nextOrders, nextHistory, nextCases].some((result) => result.status === "ok")) {
        setLastUpdated(new Date().toISOString())
      }
    } finally {
      inFlightRef.current = false
    }
  }, [])

  useEffect(() => {
    void refresh()
    const interval = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener("visibilitychange", onVisible)
      if (eventTimerRef.current !== undefined) window.clearTimeout(eventTimerRef.current)
    }
  }, [refresh])

  const onLedgerEvent = useCallback(() => {
    if (eventTimerRef.current !== undefined) return
    eventTimerRef.current = window.setTimeout(() => {
      eventTimerRef.current = undefined
      void refresh()
    }, EVENT_REFRESH_DEBOUNCE_MS)
  }, [refresh])

  const feed = useLedgerFeed({ enabled: API_BASE_CONFIGURED, onEvent: onLedgerEvent })

  const pendingCases = cases.status === "ok"
    ? cases.data.filter((item) => PENDING_CERTIFICATE_STATES.has(item.state?.toUpperCase?.() ?? ""))
    : []

  return (
    <>
      {!API_BASE_CONFIGURED && (
        <p className="command-config-error" role="alert">
          <strong>Configuration required.</strong> {API_CONFIG_ERROR}
        </p>
      )}
      <section id="command-ledger" aria-labelledby="ledger-zone-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Zone I · the money</p>
            <h2 id="ledger-zone-title" className="panel-title">The ledger</h2>
          </div>
          <span className="quiet-caption" role="status">
            {lastUpdated ? `Last read ${formatTimestamp(lastUpdated)} ET` : "Awaiting first read"}
          </span>
        </div>
        <AccountTiles account={account} />
      </section>
      <div className="command-columns">
        <div className="command-main">
          <EquityCurve history={history} account={account.status === "ok" ? account.data : null} />
          <div className="holdings-grid">
            <PositionsTable positions={positions} />
            <OrdersPanel orders={orders} />
          </div>
          <AgentFeed events={feed.events} connection={feed.connection} />
        </div>
        <div className="command-rail">
          <OperatorBench pendingCases={pendingCases} onActionComplete={refresh} />
          <LatestArgument cases={cases} />
        </div>
      </div>
    </>
  )
}
