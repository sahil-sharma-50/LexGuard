import type { CaseData } from "../lib/types"
import { formatMoney, formatTimestamp } from "../lib/format"

const AWAITING_STATES = new Set(["SCHEDULED", "OBSERVED", "FORECASTED", "ARGUED"])
const KNOWN_STATES = new Set([
  ...AWAITING_STATES,
  "CERTIFIED",
  "SUBMITTED",
  "REPLACED",
  "PARTIALLY_FILLED",
  "FILLED",
  "MANAGING",
  "CLOSED",
  "REFUSED",
  "HALTED",
  "RECONCILE_REQUIRED",
  "CANCELED",
  "REJECTED",
])

export function RiskCertificate({ certificate, verdict, caseState }: { certificate: CaseData["certificate"]; verdict: CaseData["verdict"]; caseState?: string }) {
  const normalizedState = caseState?.trim().toUpperCase()
  if (normalizedState && !KNOWN_STATES.has(normalizedState)) return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate state unknown</h2></div><span className="status-word status-warning">Unknown</span></div><p className="muted-copy">Case state “{normalizedState}” is not recognized; certificate status cannot be established. No order action is available until the ledger is reconciled.</p></section>
  if (normalizedState === "HALTED" || normalizedState === "RECONCILE_REQUIRED" || normalizedState === "CANCELED" || normalizedState === "REJECTED") return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate unavailable</h2></div><span className="status-word status-warning">Halted</span></div><p className="muted-copy">A safety halt stopped the case before a usable certificate was available. Broker state requires reconciliation.</p></section>
  if (normalizedState === "REFUSED") return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">No risk certificate</h2></div><span className="status-word status-warning">Refused</span></div><p className="muted-copy">No order can be submitted without a deterministic certificate. The refusal is the complete result for this case.</p></section>
  if (normalizedState && AWAITING_STATES.has(normalizedState)) return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate pending</h2></div><span className="status-word status-warning">Awaiting</span></div><p className="muted-copy">Awaiting deterministic risk gate output. No order can be submitted while the case remains pending.</p></section>
  if (normalizedState && (!certificate || certificate.status === "not-issued")) return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate state unknown</h2></div><span className="status-word status-warning">Unknown</span></div><p className="muted-copy">The recorded case state does not agree with the certificate artifact; certificate status cannot be established. No order action is available until the ledger is reconciled.</p></section>
  if (verdict === "UNKNOWN" || ["CERTIFIED", "WORKING", "PARTIAL", "MANAGING", "CLOSED"].includes(verdict) && !normalizedState) return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate state unknown</h2></div><span className="status-word status-warning">Unknown</span></div><p className="muted-copy">Certificate status cannot be established from the recorded case state. No order action is available until the ledger is reconciled.</p></section>
  if (verdict === "PENDING") return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate pending</h2></div><span className="status-word status-warning">Awaiting</span></div><p className="muted-copy">Awaiting deterministic risk gate output. No order can be submitted while the case remains pending.</p></section>
  if (verdict === "HALTED") return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate unavailable</h2></div><span className="status-word status-warning">Halted</span></div><p className="muted-copy">A safety halt stopped the case before a usable certificate was available. Broker state requires reconciliation.</p></section>
  if (!certificate || certificate.status === "not-issued") return <section className="section-block refusal-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">No risk certificate</h2></div><span className="status-word status-warning">Refused</span></div><p className="muted-copy">No order can be submitted without a deterministic certificate. The refusal is the complete result for this case.</p></section>
  return <section className="section-block" aria-labelledby="certificate-title"><div className="section-heading"><div><p className="section-label">The ruling</p><h2 id="certificate-title">Risk certificate</h2></div><span className="status-word status-good">Issued</span></div><dl className="certificate-grid"><div><dt>Policy</dt><dd>{certificate.policyVersion}</dd></div><div><dt>Max loss</dt><dd>{formatMoney(certificate.maxLoss ?? "")}</dd></div><div><dt>Robust EV</dt><dd>{formatMoney(certificate.robustEv ?? "")}</dd></div><div><dt>Expires</dt><dd>{formatTimestamp(certificate.expiresAt ?? "")}</dd></div></dl><p className="hash-line">Proposal hash <code>{certificate.proposalHash ?? "Not recorded"}</code></p></section>
}
