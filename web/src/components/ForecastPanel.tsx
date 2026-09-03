import type { ForecastNode } from "../lib/types"

export function ForecastPanel({ nodes, artifactHash }: { nodes: ForecastNode[]; artifactHash: string }) {
  const totalProbability = nodes.reduce((sum, node) => sum + node.probability, 0)
  const summary = nodes.length === 0
    ? ""
    : `${nodes.length} recorded nodes · probabilities total ${(totalProbability * 100).toFixed(0)}% · point-in-time only.`
  return (
    <section className="section-block forecast-panel" aria-labelledby="forecast-title">
      <div className="section-heading"><div><p className="section-label">Quantitative argument</p><h2 id="forecast-title">Return distribution</h2></div><span className="hash-chip" title={artifactHash}>{artifactHash === "no-recorded-forecast" ? "No artifact" : `Artifact ${artifactHash.slice(0, 10)}…`}</span></div>
      {nodes.length === 0 ? <p className="empty-state" role="status">No recorded forecast artifact is available.</p> : <div className="distribution" aria-label="Forecast return distribution">
        {nodes.map((node) => <div className="distribution-node" key={`${node.returnValue}-${node.probability}`}><div className="distribution-bar-wrap"><div className="distribution-bar" style={{ height: `${Math.max(10, Math.min(100, node.probability * 100 * 2))}%` }} /></div><strong>{node.returnValue}</strong><span>{(node.probability * 100).toFixed(0)}%</span></div>)}
      </div>}
      {summary && <p className="micro-note">{summary}</p>}
    </section>
  )
}
