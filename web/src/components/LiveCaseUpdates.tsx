"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { API_BASE } from "../lib/apiBase"

const MAX_CONNECTION_ATTEMPTS = 3
const MAX_FALLBACK_REFRESHES = 3
const RECONNECT_DELAY_MS = 1_000
const FALLBACK_REFRESH_INTERVAL_MS = 30_000
const EVENT_NAMES = [
  "OBSERVED",
  "FORECASTED",
  "ARGUED",
  "CERTIFIED",
  "REFUSED",
  "HALTED",
  "SUBMITTED",
  "REPLACED",
  "FILLED",
  "MANAGING",
  "CLOSED",
]

type UpdateState = "connecting" | "connected" | "updated" | "available" | "checking" | "unavailable" | "fallback" | "paused" | "unconfigured"

async function publicCaseIsAvailable(): Promise<boolean> {
  if (API_BASE === null) return false
  try {
    const listResponse = await fetch(`${API_BASE}/api/cases`, { headers: { Accept: "application/json" }, cache: "no-store" })
    if (!listResponse.ok) return false
    const list = await listResponse.json() as { items?: unknown }
    if (!Array.isArray(list.items) || list.items.length === 0) return false
    const first = list.items[0]
    if (first === null || typeof first !== "object" || Array.isArray(first)) return false
    const caseId = (first as { case_id?: unknown }).case_id
    if (typeof caseId !== "string" || !caseId) return false
    const caseResponse = await fetch(`${API_BASE}/api/cases/${encodeURIComponent(caseId)}`, { headers: { Accept: "application/json" }, cache: "no-store" })
    if (!caseResponse.ok) return false
    const projection = await caseResponse.json() as { case_id?: unknown; state?: unknown }
    return projection.case_id === caseId && typeof projection.state === "string" && projection.state.length > 0
  } catch {
    return false
  }
}

export function LiveCaseUpdates({ enabled = true }: { enabled?: boolean }) {
  const router = useRouter()
  const [state, setState] = useState<UpdateState>(enabled ? "connecting" : "paused")

  useEffect(() => {
    let closed = false
    let attempts = 0
    let fallbackRefreshes = 0
    let source: EventSource | undefined
    let reconnectTimer: number | undefined
    let fallbackTimer: number | undefined
    let refreshInFlight: Promise<boolean> | undefined

    const clearReconnectTimer = () => {
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = undefined
      }
    }
    const clearFallbackTimer = () => {
      if (fallbackTimer !== undefined) {
        window.clearTimeout(fallbackTimer)
        fallbackTimer = undefined
      }
    }
    const refreshPublicCase = () => {
      if (!refreshInFlight) {
        refreshInFlight = publicCaseIsAvailable().finally(() => {
          refreshInFlight = undefined
        })
      }
      return refreshInFlight
    }
    const refreshFromEvent = async () => {
      if (closed) return
      const refreshed = await refreshPublicCase()
      if (closed) return
      if (refreshed) {
        setState("updated")
        router.refresh()
      } else {
        setState("unavailable")
      }
    }
    const refreshFromFallback = async () => {
      if (closed || fallbackRefreshes >= MAX_FALLBACK_REFRESHES) {
        setState("fallback")
        return
      }
      fallbackRefreshes += 1
      setState("unavailable")
      const refreshed = await refreshPublicCase()
      if (closed) return
      if (refreshed) {
        setState("available")
      } else {
        setState("fallback")
      }
      if (fallbackRefreshes < MAX_FALLBACK_REFRESHES) {
        fallbackTimer = window.setTimeout(refreshFromFallback, FALLBACK_REFRESH_INTERVAL_MS)
      }
    }
    const scheduleFallbackRefresh = () => {
      if (fallbackTimer === undefined) fallbackTimer = window.setTimeout(refreshFromFallback, FALLBACK_REFRESH_INTERVAL_MS)
    }
    const connect = () => {
      if (closed || attempts >= MAX_CONNECTION_ATTEMPTS) {
        setState("fallback")
        scheduleFallbackRefresh()
        return
      }
      attempts += 1
      const nextSource = new window.EventSource(`${API_BASE}/api/events`)
      source = nextSource
      let ended = false
      const finishStream = () => {
        if (closed || ended || source !== nextSource) return
        ended = true
        nextSource.close()
        source = undefined
        setState("checking")
        scheduleFallbackRefresh()
      }
      const finishConnection = () => {
        if (closed || ended || source !== nextSource) return
        ended = true
        nextSource.close()
        source = undefined
        if (attempts < MAX_CONNECTION_ATTEMPTS) {
          setState("unavailable")
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = undefined
            connect()
          }, RECONNECT_DELAY_MS)
        } else {
          setState("fallback")
          scheduleFallbackRefresh()
        }
      }
      nextSource.onopen = () => {
        if (!closed && source === nextSource) setState("connected")
      }
      nextSource.onmessage = () => void refreshFromEvent()
      for (const eventName of EVENT_NAMES) nextSource.addEventListener(eventName, () => void refreshFromEvent())
      // The API emits this before closing its finite response, so completion
      // enters availability checks without consuming the error retry budget.
      nextSource.addEventListener("stream-complete", finishStream)
      nextSource.addEventListener("close", finishConnection)
      nextSource.onerror = finishConnection
    }

    if (!enabled) {
      setState("paused")
      return
    }
    if (API_BASE === null) {
      setState("unconfigured")
      return
    }
    if (typeof window === "undefined" || typeof window.EventSource !== "function") {
      setState("unavailable")
      scheduleFallbackRefresh()
    } else {
      connect()
    }
    return () => {
      closed = true
      clearReconnectTimer()
      clearFallbackTimer()
      source?.close()
      source = undefined
    }
  }, [enabled, router])

  const message = {
    connecting: "Connecting to the case event stream…",
    connected: "Live updates connected; the case will refresh when the ledger changes.",
    updated: "Case updated from the public event stream.",
    available: "Public case data is available; the displayed case remains unchanged until a named ledger event.",
    checking: "Finite event stream completed; checking public case availability without changing this case.",
    unavailable: "Live updates unavailable; keeping the last recorded case while retrying the event stream.",
    fallback: "Live updates unavailable; keeping the last recorded case. Automatic retries are exhausted.",
    paused: "Archived replay; live updates are paused.",
    unconfigured: "Live updates are not configured: NEXT_PUBLIC_API_BASE_URL is missing from this build.",
  }[state]

  return <p className={`live-status live-status-${state}`} role="status" aria-live="polite" aria-label={message}>{message}</p>
}
