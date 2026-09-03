"use client"

import { createContext, useContext, useMemo, useSyncExternalStore } from "react"
import type { ReactNode } from "react"
import type { DemoEnvelope } from "../lib/simulator/types"
import type { DemoStore } from "../lib/simulator/store"

const SimulatorContext = createContext<SimulatorContextValue | null>(null)

interface SimulatorContextValue {
  store: DemoStore
  snapshot: DemoEnvelope
  persistenceNotice: string | undefined
}

const SERVER_PERSISTENCE_NOTICE = undefined

export function SimulatorProvider({ store, children }: { store: DemoStore; children: ReactNode }) {
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
  )
  const persistenceNotice = useSyncExternalStore(
    store.subscribe,
    store.getPersistenceNotice,
    () => SERVER_PERSISTENCE_NOTICE,
  )
  const value = useMemo(() => ({ store, snapshot, persistenceNotice }), [store, snapshot, persistenceNotice])

  return (
    <SimulatorContext.Provider value={value}>
      <div data-simulator-background="true">{children}</div>
    </SimulatorContext.Provider>
  )
}

export function useSimulatorStore(): DemoStore {
  const context = useContext(SimulatorContext)
  if (context === null) {
    throw new Error("useSimulatorStore must be used inside SimulatorProvider")
  }
  return context.store
}

export function useSimulatorSnapshot(): DemoEnvelope {
  const context = useContext(SimulatorContext)
  if (context === null) {
    throw new Error("useSimulatorSnapshot must be used inside SimulatorProvider")
  }
  return context.snapshot
}

export function useSimulatorPersistenceNotice(): string | undefined {
  const context = useContext(SimulatorContext)
  if (context === null) {
    throw new Error("useSimulatorPersistenceNotice must be used inside SimulatorProvider")
  }
  return context.persistenceNotice
}

export function useSimulatorSelector<T>(selector: (state: DemoEnvelope) => T): T {
  return selector(useSimulatorSnapshot())
}
