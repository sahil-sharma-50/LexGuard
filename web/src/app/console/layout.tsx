"use client"

import { useState } from "react"
import { ConsoleShell } from "../../components/ConsoleShell"
import { SimulatorProvider } from "../../components/SimulatorProvider"
import { SiteHeader } from "../../components/SiteHeader"
import { createDemoStore } from "../../lib/simulator/store"

export default function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const [store] = useState(() => createDemoStore())

  return (
    <SimulatorProvider store={store}>
      <main id="main-content" className="console-shell">
        <a className="skip-link" href="#console-main">
          Skip to console content
        </a>
        <SiteHeader />
        <ConsoleShell>{children}</ConsoleShell>
      </main>
    </SimulatorProvider>
  )
}
