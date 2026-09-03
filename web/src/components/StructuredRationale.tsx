"use client"

import type { DemoRationale } from "../lib/simulator/types"

export function StructuredRationale({ rationale }: { rationale: DemoRationale | null }) {
  return (
    <section className="structured-rationale" aria-labelledby="structured-rationale-title">
      <h2 id="structured-rationale-title">Structured rationale</h2>
      {rationale === null ? (
        <p className="structured-rationale-empty">No structured rationale is available yet.</p>
      ) : (
        <dl>
          <div>
            <dt>Thesis</dt>
            <dd>{rationale.thesis}</dd>
          </div>
          <div>
            <dt>Supporting evidence</dt>
            <dd>{rationale.supportingEvidence}</dd>
          </div>
          <div>
            <dt>Counterevidence</dt>
            <dd>{rationale.counterevidence}</dd>
          </div>
          <div>
            <dt>Uncertainty</dt>
            <dd>{rationale.uncertainty}</dd>
          </div>
          <div>
            <dt>Recommendation</dt>
            <dd>{rationale.recommendation}</dd>
          </div>
        </dl>
      )}
    </section>
  )
}
