"use client"

import type { ReactNode } from "react"
import { ConsoleNavigation } from "./ConsoleNavigation"
import { EnvironmentDisclosure } from "./EnvironmentDisclosure"
import { useSimulatorPersistenceNotice } from "./SimulatorProvider"

export function ConsoleShell({ children }: { children: ReactNode }) {
  const persistenceNotice = useSimulatorPersistenceNotice()

  return (
    <>
      <EnvironmentDisclosure />
      {persistenceNotice ? <p className="fixture-notice console-persistence-notice" role="status">{persistenceNotice}</p> : null}
      <noscript>
        <p className="fixture-notice">
          Interaction requires JavaScript; this training room is a browser-local synthetic simulator.
        </p>
      </noscript>
      <header className="console-training-header">
        <ConsoleNavigation />
      </header>
      <div id="console-main">{children}</div>
    </>
  )
}
