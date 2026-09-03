import type { CaseData, RunMode } from "../lib/types"

export function OrderLifecycle({ steps, mode = "DEVELOPMENT_PAPER" }: { steps: CaseData["orderLifecycle"]; mode?: RunMode }) {
  const isBacktest = mode === "BACKTEST"
  const title = isBacktest ? "Simulated order lifecycle" : "Alpaca order lifecycle"
  const caption = isBacktest
    ? "Backtest projection · no broker calls"
    : mode === "COMPETITION_PAPER"
      ? "Competition paper endpoint only"
      : "Development paper endpoint only"
  return <section className="section-block" aria-labelledby="lifecycle-title"><div className="section-heading"><div><p className="section-label">{isBacktest ? "Simulation record" : "Broker truth"}</p><h2 id="lifecycle-title">{title}</h2></div><span className="quiet-caption">{caption}</span></div><ol className="lifecycle-list">{steps.map((step, index) => <li className={`lifecycle-step lifecycle-${step.state}`} key={step.label}><span className="step-index" aria-hidden="true">{index + 1}</span><div><h3>{step.label}</h3><p>{step.detail}</p></div></li>)}</ol></section>
}
