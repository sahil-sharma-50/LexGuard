import type { EvidenceItem } from "../lib/types"

export function EvidenceTimeline({ items }: { items: EvidenceItem[] }) {
  return (
    <section className="section-block" aria-labelledby="evidence-title">
      <div className="section-heading"><div><p className="section-label">The record</p><h2 id="evidence-title">Evidence chain</h2></div><span className="quiet-caption">Point-in-time only</span></div>
      {items.length === 0 ? <p className="empty-state" role="status">No recorded evidence is available for this case.</p> : <ol className="evidence-list">
        {items.map((item) => <li className="evidence-row" key={item.label}><span className={`state-mark state-${item.state}`} aria-hidden="true" /><div><h3>{item.label}</h3><p>{item.value}</p></div><span className={`evidence-state evidence-state-${item.state}`}>{item.state}</span><span className="provenance">{item.provenance}</span></li>)}
      </ol>}
    </section>
  )
}
