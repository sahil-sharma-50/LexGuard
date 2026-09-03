const SESSIONS = [
  { time: "10:05", order: "SESSION I" },
  { time: "11:35", order: "SESSION II" },
  { time: "13:05", order: "SESSION III" },
  { time: "14:20", order: "SESSION IV" },
] as const

/**
 * The session docket: the court hears entries at four fixed ET windows.
 * Rendered deterministically (no client clock) so server and client agree.
 */
export function SessionDocket({ title = "Session docket", note = "All times ET · entries are heard only at these windows" }: { title?: string; note?: string }) {
  return (
    <aside className="session-docket" aria-label={title}>
      <div className="session-docket-title">
        <h3>{title}</h3>
        <span className="mono-chip">SPY · QQQ · IWM</span>
      </div>
      <ol>
        {SESSIONS.map((session) => (
          <li key={session.time}>
            <span className="session-time">{session.time}</span>
            <span className="session-matter">
              <strong>Entry hearing</strong> · argue → certify or refuse → execute
            </span>
            <span className="session-order">{session.order}</span>
          </li>
        ))}
      </ol>
      <p className="micro-note">{note}</p>
    </aside>
  )
}
