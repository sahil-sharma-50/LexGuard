"use client"

import { useEffect, useRef, useState } from "react"
import { API_BASE } from "../../lib/apiBase"

/** Every event type the ledger replays over /api/events. */
export const LEDGER_EVENT_NAMES = [
  "OBSERVED",
  "FORECASTED",
  "ARGUED",
  "CERTIFIED",
  "REFUSED",
  "SUBMITTED",
  "REPLACED",
  "FILLED",
  "PARTIALLY_FILLED",
  "MANAGING",
  "CANCELED",
  "REJECTED",
  "RECONCILE_REQUIRED",
  "HALTED",
  "CLOSED",
] as const

export interface FeedEvent {
  id: string
  type: string
  caseId?: string
  timestamp?: string
  summary?: string
}

export type FeedConnection = "connecting" | "live" | "replay-complete" | "unavailable" | "unconfigured"

const MAX_EVENTS = 150
const RETRY_AFTER_ERROR_MS = 15_000
const RECONNECT_AFTER_COMPLETE_MS = 30_000

function parseEvent(type: string, data: string, lastEventId: string): FeedEvent {
  let caseId: string | undefined
  let timestamp: string | undefined
  let summary: string | undefined
  try {
    const payload = JSON.parse(data) as Record<string, unknown>
    if (payload && typeof payload === "object") {
      for (const key of ["case_id", "caseId"]) {
        if (typeof payload[key] === "string") caseId = payload[key] as string
      }
      for (const key of ["recorded_at", "timestamp", "as_of", "created_at"]) {
        if (typeof payload[key] === "string") { timestamp = payload[key] as string; break }
      }
      for (const key of ["summary", "detail", "reason", "message"]) {
        if (typeof payload[key] === "string") { summary = payload[key] as string; break }
      }
      if (!summary && typeof payload.underlying === "string") {
        summary = `${payload.underlying}${typeof payload.decision_window === "string" ? ` · ${payload.decision_window} ET` : ""}`
      }
    }
  } catch {
    // Non-JSON payloads are kept verbatim (truncated) so nothing is hidden.
    summary = data.length > 140 ? `${data.slice(0, 140)}…` : data || undefined
  }
  const id = lastEventId ? `${type}|${lastEventId}` : `${type}|${data}`
  return { id, type, caseId, timestamp, summary }
}

/**
 * Subscribes to the finite /api/events replay stream. The stream ends with
 * "stream-complete", so the hook reconnects on a timer while the page is
 * visible; events are deduplicated by id across replays.
 */
export function useLedgerFeed({ enabled = true, onEvent }: { enabled?: boolean; onEvent?: () => void } = {}) {
  const [events, setEvents] = useState<FeedEvent[]>([])
  const [connection, setConnection] = useState<FeedConnection>(API_BASE === null ? "unconfigured" : "connecting")
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!enabled) return
    if (API_BASE === null) {
      setConnection("unconfigured")
      return
    }
    if (typeof window === "undefined" || typeof window.EventSource !== "function") {
      setConnection("unavailable")
      return
    }

    let closed = false
    let source: EventSource | undefined
    let timer: number | undefined
    const seen = new Set<string>()

    const schedule = (delay: number) => {
      if (closed || timer !== undefined) return
      timer = window.setTimeout(() => {
        timer = undefined
        if (document.visibilityState === "visible") connect()
        else schedule(delay)
      }, delay)
    }

    const record = (type: string, raw: MessageEvent) => {
      if (closed) return
      const event = parseEvent(type, typeof raw.data === "string" ? raw.data : "", raw.lastEventId ?? "")
      if (seen.has(event.id)) return
      seen.add(event.id)
      setEvents((current) => [event, ...current].slice(0, MAX_EVENTS))
      onEventRef.current?.()
    }

    const connect = () => {
      if (closed || source) return
      setConnection("connecting")
      const next = new window.EventSource(`${API_BASE}/api/events`)
      source = next
      let ended = false
      const finish = (state: FeedConnection, delay: number) => {
        if (closed || ended || source !== next) return
        ended = true
        next.close()
        source = undefined
        setConnection(state)
        schedule(delay)
      }
      next.onopen = () => {
        if (!closed && source === next) setConnection("live")
      }
      next.onmessage = (message) => record("EVENT", message)
      for (const name of LEDGER_EVENT_NAMES) {
        next.addEventListener(name, (message) => record(name, message as MessageEvent))
      }
      next.addEventListener("stream-complete", () => finish("replay-complete", RECONNECT_AFTER_COMPLETE_MS))
      next.addEventListener("close", () => finish("replay-complete", RECONNECT_AFTER_COMPLETE_MS))
      next.onerror = () => finish("unavailable", RETRY_AFTER_ERROR_MS)
    }

    const onVisible = () => {
      if (document.visibilityState === "visible" && !source && timer === undefined) connect()
    }
    document.addEventListener("visibilitychange", onVisible)
    connect()

    return () => {
      closed = true
      document.removeEventListener("visibilitychange", onVisible)
      if (timer !== undefined) window.clearTimeout(timer)
      source?.close()
      source = undefined
    }
  }, [enabled])

  return { events, connection }
}
