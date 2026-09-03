import type { Metadata } from "next"
import { CommandCenter } from "../../components/command/CommandCenter"
import { ConsolePageHeader } from "../../components/ConsolePageHeader"
import { SiteHeader } from "../../components/SiteHeader"

export const metadata: Metadata = {
  title: "Command center: Lexguard",
  description: "Live account ledger, decision feed, and stop-only operator bench for the autonomous options court on Alpaca paper.",
}

export const dynamic = "force-dynamic"

export default function CommandPage() {
  return (
    <main id="main-content" className="command-shell">
      <a className="skip-link" href="#command-ledger">Skip to the ledger</a>
      <SiteHeader />
      <ConsolePageHeader
        title="Command center"
        description="The money, the record, and the bench. Everything here is read from the public ledger and the Alpaca paper endpoint; the only human powers are brakes."
      >
        <span className="command-refresh-status" role="status">Refreshes while visible</span>
      </ConsolePageHeader>
      <CommandCenter />
    </main>
  )
}
