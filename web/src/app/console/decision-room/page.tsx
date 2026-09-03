import { DecisionRoom } from "../../../components/DecisionRoom"

export default async function DecisionRoomPage({
  searchParams,
}: {
  searchParams: Promise<{ scenario?: string; run?: string }>
}) {
  const selection = await searchParams
  return <DecisionRoom requestedScenario={selection.scenario} requestedRun={selection.run} />
}
