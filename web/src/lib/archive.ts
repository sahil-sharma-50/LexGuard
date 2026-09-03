import type { CaseData, ResearchSummaryData } from "./types"

/** Sanitized, archived fixture used only when the public read API cannot be reached. */
export const ARCHIVED_CASE: CaseData = {
  caseId: "44444444-4444-4444-4444-444444444444", tradingDate: "2026-08-24", decisionWindow: "10:05", underlying: "SPY", verdict: "ABSTAIN",
  verdictReason: "Catalyst evidence did not clear the confidence floor. No order was submitted.", reasonCodes: ["CATALYST_VETO"], environment: "development", mode: "DEVELOPMENT_PAPER", asOf: "2026-08-24T14:10:00Z",
  evidence: [
    { label: "Market evidence", value: "Archived sanitized snapshot", provenance: "Archived fixture", state: "verified" },
    { label: "Catalyst review", value: "No defensible event-linked edge", provenance: "Archived fixture", state: "warning" },
    { label: "Risk policy", value: "No certificate issued", provenance: "Archived fixture", state: "verified" },
  ],
  forecast: { nodes: [{ returnValue: "−1.0%", probability: 0.25 }, { returnValue: "0.0%", probability: 0.5 }, { returnValue: "+1.0%", probability: 0.25 }], artifactHash: "archived-fixture" },
  certificate: { status: "not-issued", policyVersion: "risk-constitution.v1" },
  orderLifecycle: [{ label: "Observed", state: "complete", detail: "Archived evidence sealed" }, { label: "Certified", state: "blocked", detail: "No certificate" }, { label: "Submitted", state: "blocked", detail: "Paper broker untouched" }],
  performance: { realizedPnl: "0", totalReturn: "0.00%", drawdown: "0.00%", provenance: "Archived development-paper fixture" },
}

export const ARCHIVED_CASE_ROUTE = "archived"

export const ARCHIVED_RESEARCH: ResearchSummaryData = { environment: "development", asOf: "2026-08-24T14:10:00Z", provenance: "Archived fixture; no recorded research artifact", gate: "NOT_RUN", metrics: {} }
