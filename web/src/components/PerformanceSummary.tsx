import type { CaseData, RunMode } from "../lib/types"
import { formatMoney } from "../lib/format"

export function PerformanceSummary({ performance, mode }: { performance: CaseData["performance"]; mode?: RunMode }) {
  const resolvedMode = mode ?? (performance.provenance.toLowerCase().includes("paper") ? "DEVELOPMENT_PAPER" : "BACKTEST")
  const qualifier = resolvedMode === "BACKTEST"
    ? "Results are historical backtest outputs, not live-money performance."
    : resolvedMode === "COMPETITION_PAPER"
      ? "Results are recorded competition-paper outcomes, not live-money performance."
      : "Results are simulated paper outcomes (development-paper mode), not live-money performance."
  return <section className="performance-strip" aria-labelledby="performance-title"><div><p className="section-label">After the ruling</p><h2 id="performance-title">Performance ledger</h2><p className="muted-copy">{performance.provenance}. {qualifier}</p></div><dl className="performance-metrics"><div><dt>Realized P&amp;L</dt><dd>{formatMoney(performance.realizedPnl)}</dd></div><div><dt>Total return</dt><dd>{performance.totalReturn}</dd></div><div><dt>Drawdown</dt><dd>{performance.drawdown}</dd></div></dl></section>
}
