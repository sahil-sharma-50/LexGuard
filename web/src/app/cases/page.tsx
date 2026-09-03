import Link from "next/link"
import { ARCHIVED_CASE, ARCHIVED_CASE_ROUTE } from "../../lib/archive"
import { getCases, PublicApiError } from "../../lib/api"
import { ConsolePageHeader } from "../../components/ConsolePageHeader"
import { SiteHeader } from "../../components/SiteHeader"
import type { CaseProjection } from "../../lib/types"

export const dynamic = "force-dynamic"

export default async function CasesPage() {
  let cases: CaseProjection[] = []
  let notice: string | undefined
  try {
    const result = await getCases()
    cases = result.items
    if (cases.length === 0) notice = "The public read API has no recorded cases. Showing the archived fixture."
  } catch (error) {
    notice = error instanceof PublicApiError ? `Archive index unavailable: ${error.message}` : "Archive index unavailable. Showing the archived fixture."
  }

  return (
    <main className="subpage-shell archive-index">
      <SiteHeader />
      <div className="subpage-body">
        <ConsolePageHeader
          title="Case archive"
          description="Browse sealed, read-only case projections. Each link keeps its recorded identifier and evidence state."
        />
        {notice && <p className="fixture-notice" role="status">{notice} No live broker or credential access was attempted.</p>}
        <ol className="archive-list">
          {cases.length === 0 ? <li className="archive-row"><Link prefetch={false} href={`/cases/${ARCHIVED_CASE_ROUTE}`}>Archived fixture · {ARCHIVED_CASE.underlying} / {ARCHIVED_CASE.decisionWindow}</Link><span>ABSTAIN · fixture</span></li> : cases.map((item) => <li className="archive-row" key={item.case_id}><Link prefetch={false} href={`/cases/${encodeURIComponent(item.case_id)}`}>{item.underlying ?? "Unknown underlying"} / {item.decision_window}</Link><span>{item.state} · {item.trading_date}</span></li>)}
        </ol>
      </div>
    </main>
  )
}
