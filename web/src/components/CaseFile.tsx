import type { CaseData } from "../lib/types"
import { EvidenceTimeline } from "./EvidenceTimeline"
import { ForecastPanel } from "./ForecastPanel"
import { LiveCaseUpdates } from "./LiveCaseUpdates"
import { OrderLifecycle } from "./OrderLifecycle"
import { PerformanceSummary } from "./PerformanceSummary"
import { RiskCertificate } from "./RiskCertificate"
import { ConsolePageHeader } from "./ConsolePageHeader"
import { SiteHeader } from "./SiteHeader"
import { VerdictBanner } from "./VerdictBanner"

export function CaseFile({
  data,
  fixtureNotice,
  isArchive = false,
  liveUpdates = !isArchive,
}: {
  data: CaseData
  fixtureNotice?: string
  isArchive?: boolean
  liveUpdates?: boolean
}) {
  const modeDisclosure = data.mode === "BACKTEST"
    ? "Backtest projection · no broker calls"
    : data.mode === "COMPETITION_PAPER"
      ? "Competition paper · no live-money controls"
      : "Development paper · no live-money controls"
  return (
    <main className="case-file-shell">
      <SiteHeader />
      <ConsolePageHeader
        title={`${data.underlying} / ${data.decisionWindow}`}
        description="Live decision record and read-only evidence projection."
      >
        <div className="case-id">{data.caseId}</div>
      </ConsolePageHeader>
      {fixtureNotice && <p className="fixture-notice case-fixture-notice" role="status">{fixtureNotice}</p>}
      {!isArchive && <LiveCaseUpdates enabled={liveUpdates} />}
      <VerdictBanner data={data} />
      <div className="primary-grid"><EvidenceTimeline items={data.evidence} /><ForecastPanel nodes={data.forecast.nodes} artifactHash={data.forecast.artifactHash} /></div>
      <div className="secondary-grid"><RiskCertificate certificate={data.certificate} verdict={data.verdict} caseState={data.caseState} /><OrderLifecycle steps={data.orderLifecycle} mode={data.mode} /></div>
      <PerformanceSummary performance={data.performance} mode={data.mode} />
      <footer className="case-footer"><span>Read-only projection</span><span>{modeDisclosure}</span></footer>
    </main>
  )
}
