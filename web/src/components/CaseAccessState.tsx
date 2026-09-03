import Link from "next/link"
import { ARCHIVED_CASE_ROUTE } from "../lib/archive"
import { SiteHeader } from "./SiteHeader"

export function CaseAccessState({
  title,
  caseId,
  detail,
}: {
  title: string
  caseId: string
  detail: string
}) {
  return (
    <main className="subpage-shell case-access-state">
      <SiteHeader />
      <div className="subpage-body">
        <p className="section-label">Public record</p>
        <h1>{title}</h1>
        <p className="subpage-lede">{detail}</p>
        <p className="case-id case-access-id">Requested case: {caseId}</p>
        <Link prefetch={false} className="text-link" href={`/cases/${ARCHIVED_CASE_ROUTE}`}>Open the archived fixture</Link>
      </div>
    </main>
  )
}
