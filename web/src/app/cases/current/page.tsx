import { CaseFile } from "../../../components/CaseFile"
import { getLiveCase } from "../../../lib/api"

export const dynamic = "force-dynamic"

export default async function CurrentCasePage() {
  const result = await getLiveCase()
  return <CaseFile data={result.data} fixtureNotice={result.notice} liveUpdates={result.source === "public_api"} />
}
