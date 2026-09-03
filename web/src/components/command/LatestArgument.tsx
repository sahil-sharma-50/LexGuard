"use client"

import Link from "next/link"
import type { CaseProjection } from "../../lib/types"
import type { PanelData } from "./types"

interface Argument {
  caseId: string
  underlying: string
  window: string
  scenario?: string
  confidence?: string
  rationale?: string
  evidenceIds: string[]
  contentHash?: string
}

function asObject(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function extractArgument(cases: CaseProjection[]): Argument | null {
  for (const item of cases) {
    const assessment = asObject(asObject(item.artifacts)?.catalyst_assessment)
    if (!assessment) continue
    const evidenceIds = Array.isArray(assessment.evidence_ids)
      ? assessment.evidence_ids.filter((id): id is string => typeof id === "string")
      : []
    return {
      caseId: item.case_id,
      underlying: item.underlying ?? "Unknown underlying",
      window: item.decision_window,
      scenario: typeof assessment.scenario === "string" ? assessment.scenario : undefined,
      confidence: assessment.confidence !== undefined && assessment.confidence !== null ? String(assessment.confidence) : undefined,
      rationale: typeof assessment.rationale === "string" ? assessment.rationale : undefined,
      evidenceIds,
      contentHash: typeof assessment.content_hash === "string" ? assessment.content_hash : undefined,
    }
  }
  return null
}

export function LatestArgument({ cases }: { cases: PanelData<CaseProjection[]> }) {
  const argument = cases.status === "ok" ? extractArgument(cases.data) : null
  return (
    <section className="panel argument-panel" aria-labelledby="latest-argument-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">The record · argument</p>
          <h3 id="latest-argument-title">Latest argument</h3>
        </div>
        {argument?.contentHash ? <span className="provenance-badge" title={argument.contentHash}>artifact {argument.contentHash.slice(0, 10)}…</span> : null}
      </div>
      {argument ? (
        <>
          <div className="argument-meta">
            <span className="mono-chip">{argument.underlying} · {argument.window} ET</span>
            {argument.scenario ? <span className="mono-chip">scenario {argument.scenario}</span> : null}
            {argument.confidence ? <span className="mono-chip">confidence {argument.confidence}</span> : null}
          </div>
          <blockquote cite={`/cases/${encodeURIComponent(argument.caseId)}`}>
            {argument.rationale ?? "The recorded assessment carries no verbatim rationale."}
          </blockquote>
          {argument.evidenceIds.length > 0 && (
            <>
              <p className="quiet-caption">Cited news evidence</p>
              <ul className="argument-evidence">
                {argument.evidenceIds.map((id) => <li key={id}><span className="mono-chip">{id}</span></li>)}
              </ul>
            </>
          )}
          <p className="micro-note">
            Verbatim from the catalyst assessment artifact. The advocate&rsquo;s words never execute anything;{" "}
            <Link prefetch={false} className="text-link" href={`/cases/${encodeURIComponent(argument.caseId)}`}>read the full case file</Link>.
          </p>
        </>
      ) : cases.status === "loading" ? (
        <p className="empty-state" role="status">Reading recorded cases…</p>
      ) : cases.status === "ok" ? (
        <p className="empty-state" role="status">No recorded catalyst assessment yet. The advocate&rsquo;s verbatim rationale appears here after the next ARGUED event.</p>
      ) : (
        <p className="panel-unavailable" role="status">
          <strong>{cases.status === "unconfigured" ? "Not configured" : "Case record unavailable"}</strong>: {cases.reason}
        </p>
      )}
    </section>
  )
}
