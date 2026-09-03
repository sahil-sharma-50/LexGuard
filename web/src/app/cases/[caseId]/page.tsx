import { CaseFile } from "../../../components/CaseFile"
import { CaseAccessState } from "../../../components/CaseAccessState"
import { getArchivedCase, PublicApiError, UnknownCaseError } from "../../../lib/api"

export const dynamic = "force-dynamic"

export default async function ArchivedCasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params
  try {
    const result = await getArchivedCase(caseId)
    return <CaseFile data={result.data} fixtureNotice={result.notice} isArchive liveUpdates={false} />
  } catch (error) {
    if (error instanceof UnknownCaseError) {
      return <CaseAccessState title="Case not found" caseId={caseId} detail="No archived case matches this identifier. The requested ID was not replaced with another case." />
    }
    const detail = error instanceof PublicApiError ? error.message : "The public read API could not load this case."
    return <CaseAccessState title="Case unavailable" caseId={caseId} detail={`${detail} Try again when the public read service is available.`} />
  }
}
