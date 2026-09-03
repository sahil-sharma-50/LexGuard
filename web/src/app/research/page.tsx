import { getResearchSummary } from "../../lib/api"
import { ConsolePageHeader } from "../../components/ConsolePageHeader"
import { SiteHeader } from "../../components/SiteHeader"

export const dynamic = "force-dynamic"

function gateClass(gate: string) {
  return /^(PASS|READY|COMPLETE)$/i.test(gate) ? "status-good" : "status-warning"
}

export default async function ResearchPage() {
  const result = await getResearchSummary()
  const { data } = result
  return (
    <main className="subpage-shell">
      <SiteHeader />
      <div className="subpage-body">
        <ConsolePageHeader title="Research gate" description="Historical results remain separate from paper execution." />
        {result.notice && <p className="fixture-notice" role="status">{result.notice}</p>}
        <div className="research-ledger">
          <div><span>Provenance</span><strong>{data.provenance}</strong></div>
          <div><span>Environment</span><strong>{data.environment}</strong></div>
          <div><span>Gate</span><strong className={gateClass(data.gate)}>{data.gate}</strong></div>
        </div>
        <p className="muted-copy">BACKTEST, DEVELOPMENT PAPER, and COMPETITION PAPER are distinct labels. This is a read-only projection.</p>
      </div>
    </main>
  )
}
