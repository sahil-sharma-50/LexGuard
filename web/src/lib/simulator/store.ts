import { createAuthoredSeed } from "./fixtures"
import {
  activateScenario as activateScenarioTransition,
  applyDemoAction,
  type ActivationResult,
  type TransitionResult,
} from "./reducer"
import { createPersistence, type DemoPersistence } from "./persistence"
import type { DemoAction, DemoEnvelope, ScenarioId } from "./types"

export interface DemoStore {
  getSnapshot(): DemoEnvelope
  getServerSnapshot(): DemoEnvelope
  subscribe(listener: () => void): () => void
  dispatch(action: DemoAction): TransitionResult
  activateScenario(id: ScenarioId): ActivationResult
  reset(): TransitionResult
  getPersistenceNotice(): string | undefined
}

// One authored object is shared by every server render. This keeps the
// useSyncExternalStore server contract referentially stable.
const SERVER_SNAPSHOT = createAuthoredSeed()

export function createDemoStore(persistence: DemoPersistence = createPersistence()): DemoStore {
  const hydrated = persistence.load()
  let snapshot = hydrated.state
  let persistenceNotice = hydrated.notice
  const listeners = new Set<() => void>()

  // Replace invalid browser data as soon as it is detected, so a refresh does
  // not repeatedly hydrate the same corrupt payload.
  if (hydrated.notice && hydrated.persistent) {
    const saved = persistence.save(snapshot)
    if (saved.notice) persistenceNotice = saved.notice
  }

  const publish = (next: DemoEnvelope): void => {
    if (next === snapshot) return
    snapshot = next
    const saved = persistence.save(snapshot)
    if (saved.notice) {
      persistenceNotice = saved.notice
    } else if (saved.persistent) {
      persistenceNotice = undefined
    }
    for (const listener of listeners) listener()
  }

  const resetStore = (): TransitionResult => {
    persistence.clear()
    const clearNotice = persistence.getNotice?.()
    if (clearNotice) persistenceNotice = clearNotice
    const result = applyDemoAction(snapshot, { type: "RESET_SCENARIO" })
    if (result.state !== snapshot) {
      snapshot = result.state
      for (const listener of listeners) listener()
    }
    return result
  }

  return {
    getSnapshot(): DemoEnvelope {
      return snapshot
    },

    getServerSnapshot(): DemoEnvelope {
      return SERVER_SNAPSHOT
    },

    subscribe(listener: () => void): () => void {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    dispatch(action: DemoAction): TransitionResult {
      if (action.type === "RESET_SCENARIO") return resetStore()
      const result = applyDemoAction(snapshot, action)
      publish(result.state)
      return result
    },

    activateScenario(id: ScenarioId): ActivationResult {
      const result = activateScenarioTransition(snapshot, id)
      publish(result.state)
      return result
    },

    reset(): TransitionResult {
      return resetStore()
    },

    getPersistenceNotice(): string | undefined {
      return persistenceNotice
    },
  }
}
