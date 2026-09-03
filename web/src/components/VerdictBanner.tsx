import type { CaseData } from "../lib/types"
import { environmentLabel, formatTimestamp } from "../lib/format"

const verdictCopy: Record<CaseData["verdict"], { stamp: string; title: string }> = {
  PENDING: { stamp: "PENDING", title: "Decision pending" },
  ABSTAIN: { stamp: "NO ENTRY", title: "Abstain from the trade" },
  CERTIFIED: { stamp: "CERTIFIED", title: "Certified structure" },
  HALTED: { stamp: "HALTED", title: "Trading halted" },
  WORKING: { stamp: "WORKING", title: "Order working" },
  PARTIAL: { stamp: "PARTIAL", title: "Partial fill" },
  MANAGING: { stamp: "MANAGING", title: "Position being managed" },
  CLOSED: { stamp: "CLOSED", title: "Case closed" },
  UNKNOWN: { stamp: "UNKNOWN", title: "State unavailable" },
}

export function VerdictBanner({ data }: { data: CaseData }) {
  const copy = verdictCopy[data.verdict]
  return (
    <section className={`verdict-banner verdict-${data.verdict.toLowerCase()}`} aria-labelledby="verdict-title">
      <div className="verdict-stamp" aria-hidden="true">{copy.stamp}</div>
      <div className="verdict-copy">
        <p className="section-label">Decision window · {data.decisionWindow} ET</p>
        <h2 id="verdict-title">{copy.title}</h2>
        <p>{data.verdictReason}</p>
        {data.reasonCodes.length > 0 && <p className="reason-code">{data.reasonCodes.join(" · ")}</p>}
        <div className="verdict-meta"><span>{data.underlying}</span><span>{environmentLabel(data.mode)}</span><span>As of {formatTimestamp(data.asOf)}</span></div>
      </div>
    </section>
  )
}
