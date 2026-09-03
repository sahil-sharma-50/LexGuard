"use client"

import Link from "next/link"
import { formatClockTime } from "../../lib/format"
import type { FeedConnection, FeedEvent } from "./useLedgerFeed"

const EVENT_FAMILY: Record<string, { tone: string; verb: string }> = {
  OBSERVED: { tone: "evidence", verb: "Evidence sealed" },
  FORECASTED: { tone: "evidence", verb: "Distribution filed" },
  ARGUED: { tone: "argument", verb: "Advocate argued" },
  CERTIFIED: { tone: "ruling", verb: "Gate certified" },
  REFUSED: { tone: "refusal", verb: "Entry refused" },
  SUBMITTED: { tone: "ruling", verb: "Order submitted" },
  REPLACED: { tone: "ruling", verb: "Order replaced" },
  FILLED: { tone: "ruling", verb: "Order filled" },
  PARTIALLY_FILLED: { tone: "ruling", verb: "Partial fill" },
  MANAGING: { tone: "ruling", verb: "Managing position" },
  CANCELED: { tone: "refusal", verb: "Order canceled" },
  REJECTED: { tone: "halt", verb: "Broker rejected" },
  RECONCILE_REQUIRED: { tone: "halt", verb: "Reconcile required" },
  HALTED: { tone: "halt", verb: "Court halted" },
  CLOSED: { tone: "ruling", verb: "Case closed" },
}

const CONNECTION_COPY: Record<FeedConnection, { className: string; copy: string }> = {
  connecting: { className: "feed-status", copy: "Connecting to the ledger event stream…" },
  live: { className: "feed-status feed-status-live", copy: "Live · replaying the ledger event stream" },
  "replay-complete": { className: "feed-status", copy: "Replay complete · reconnecting for new events shortly" },
  unavailable: { className: "feed-status feed-status-unavailable", copy: "Event stream unavailable · retrying; nothing is invented while it is down" },
  unconfigured: { className: "feed-status feed-status-unavailable", copy: "Event stream not configured: NEXT_PUBLIC_API_BASE_URL is missing" },
}

export function AgentFeed({ events, connection }: { events: FeedEvent[]; connection: FeedConnection }) {
  const status = CONNECTION_COPY[connection]
  return (
    <section className="panel" aria-labelledby="agent-feed-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">Zone II · the record</p>
          <h3 id="agent-feed-title">Decision feed</h3>
        </div>
        <span className="provenance-badge">ledger replay · /api/events</span>
      </div>
      <p className={status.className} role="status" aria-live="polite">{status.copy}</p>
      {events.length === 0 ? (
        <p className="empty-state" role="status">
          No events on the record yet. When the court sits (observe, forecast, argue, certify, execute,
          reconcile, close), each ledger event appears here in order.
        </p>
      ) : (
        <ol className="feed-list" aria-label="Chronological ledger events, newest first">
          {events.map((event) => {
            const family = EVENT_FAMILY[event.type] ?? { tone: "neutral", verb: event.type }
            return (
              <li className="feed-event" key={event.id}>
                <span className={`feed-kind feed-kind-${family.tone}`}>{event.type}</span>
                <span className="feed-detail">
                  {family.verb}
                  {event.summary ? `: ${event.summary}` : ""}
                  {event.caseId ? (
                    <>
                      {" · "}
                      <Link prefetch={false} href={`/cases/${encodeURIComponent(event.caseId)}`}>case {event.caseId.slice(0, 8)}…</Link>
                    </>
                  ) : null}
                </span>
                <span className="feed-time">{event.timestamp ? `${formatClockTime(event.timestamp)} ET` : ""}</span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
