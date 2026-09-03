"use client"

import { useState } from "react"
import { ActionConfirmation } from "./ActionConfirmation"
import { useSimulatorStore } from "./SimulatorProvider"

export function ScenarioReset({
  onReset,
  onFeedback,
}: {
  onReset?: () => unknown
  onFeedback?: (message: string) => void
}) {
  const store = useSimulatorStore()
  const [open, setOpen] = useState(false)
  const [invokingElement, setInvokingElement] = useState<HTMLElement | null>(null)

  return (
    <div className="scenario-reset">
      <button
        className="scenario-reset-trigger"
        type="button"
        onClick={(event) => {
          setInvokingElement(event.currentTarget)
          setOpen(true)
        }}
      >
        Reset demo
      </button>
      <ActionConfirmation
        open={open}
        action="RESET_SCENARIO"
        invokingElement={invokingElement}
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          setOpen(false)
          if (onReset) onReset()
          else store.reset()
          onFeedback?.("Demo reset completed in the synthetic browser-local simulator.")
        }}
      />
    </div>
  )
}
