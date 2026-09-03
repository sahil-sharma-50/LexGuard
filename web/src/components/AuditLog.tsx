"use client"

import type { AuditEvent } from "../lib/simulator/types"

export function AuditLog({ events }: { events: readonly AuditEvent[] }) {
  return (
    <details className="audit-log">
      <summary>Technical audit log ({events.length} events)</summary>
      {events.length === 0 ? (
        <p>No simulator events recorded yet.</p>
      ) : (
        <ol>
          {events.map((event) => (
            <li key={`${event.sequence}-${event.action}`}>
              <div>
                <strong>{event.summary}</strong>
                <span>{event.outcome} · {event.actor}</span>
              </div>
              <time dateTime={event.timestamp}>Sequence {event.sequence} · {event.timestamp}</time>
              {event.details ? (
                <dl>
                  {Object.entries(event.details).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </details>
  )
}
