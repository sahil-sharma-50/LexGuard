"use client"

import { useState } from "react"
import type { MouseEvent } from "react"
import { ActionConfirmation } from "./ActionConfirmation"
import { EnvironmentDisclosure } from "./EnvironmentDisclosure"
import { ScenarioReset } from "./ScenarioReset"
import { useSimulatorStore } from "./SimulatorProvider"
import { selectActionAvailability } from "../lib/simulator/selectors"
import type { DemoActionType, DemoRun } from "../lib/simulator/types"

const ACTIONS: readonly { type: DemoActionType; label: string }[] = [
  { type: "ADVANCE_EVIDENCE", label: "Advance evidence" },
  { type: "COMPLETE_FORECAST", label: "Complete forecast" },
  { type: "COMPLETE_ARGUMENT", label: "Complete argument" },
  { type: "REQUEST_SUPERVISION", label: "Request supervision" },
  { type: "APPROVE_PROPOSAL", label: "Approve proposal" },
  { type: "VETO_PROPOSAL", label: "Veto proposal" },
  { type: "SIMULATE_SUBMIT", label: "Simulate submit" },
  { type: "SIMULATE_WORKING", label: "Mark order working" },
  { type: "SIMULATE_FILL", label: "Record synthetic fill" },
  { type: "PAUSE_SCHEDULER", label: "Pause scheduler" },
  { type: "RESUME_SCHEDULER", label: "Resume scheduler" },
  { type: "TRIGGER_RECONCILIATION", label: "Present reconciliation" },
  { type: "RESOLVE_RECONCILIATION", label: "Resolve reconciliation" },
  { type: "FAIL_RECONCILIATION", label: "Fail reconciliation" },
  { type: "CLOSE_POSITION", label: "Close position" },
  { type: "COMPLETE_CLOSE", label: "Complete close" },
  { type: "EMERGENCY_STOP", label: "Emergency stop" },
]

const CONFIRMATION_ACTIONS = new Set<DemoActionType>([
  "APPROVE_PROPOSAL",
  "VETO_PROPOSAL",
  "CLOSE_POSITION",
  "EMERGENCY_STOP",
])

export interface ScenarioControlsProps {
  run: DemoRun | null
  onAction?: (action: DemoActionType) => unknown
  onReset?: () => unknown
}

export function ScenarioControls({ run, onAction, onReset }: ScenarioControlsProps) {
  const store = useSimulatorStore()
  const [pendingAction, setPendingAction] = useState<{ type: DemoActionType; invokingElement: HTMLElement } | null>(null)
  const [feedback, setFeedback] = useState("")

  const execute = (action: DemoActionType) => {
    const result = onAction
      ? onAction(action)
      : store.dispatch({ type: action, actor: "PUBLIC_DEMO_USER" })
    if (isRejectedTransition(result)) {
      setFeedback(`${labelFor(action)} unavailable: ${result.event?.summary ?? "the prerequisite is not met."}`)
      return
    }
    setFeedback(`${labelFor(action)} requested in the synthetic browser-local simulator.`)
  }

  const handleClick = (action: DemoActionType, event: MouseEvent<HTMLButtonElement>) => {
    if (CONFIRMATION_ACTIONS.has(action)) {
      setPendingAction({ type: action, invokingElement: event.currentTarget })
      return
    }
    execute(action)
  }

  return (
    <section className="scenario-controls" aria-labelledby="scenario-controls-title">
      <EnvironmentDisclosure />
      <h2 id="scenario-controls-title">Supervised demo actions</h2>
      <p>Operate the authored scenario one deterministic transition at a time.</p>
      <div className="scenario-action-list">
        {ACTIONS.map((action) => {
          const availability = selectActionAvailability(run, action.type)
          const reasonId = `scenario-action-reason-${action.type.toLowerCase()}`
          return (
            <div className="scenario-action" key={action.type}>
              <button
                type="button"
                disabled={!availability.enabled}
                aria-describedby={!availability.enabled ? reasonId : undefined}
                onClick={(event) => handleClick(action.type, event)}
              >
                {action.label}
              </button>
              {!availability.enabled ? <span id={reasonId}>Prerequisite: {availability.reason}</span> : null}
            </div>
          )
        })}
      </div>
      <p className="scenario-feedback" role="status" aria-live="polite">
        {feedback || "No action requested yet."}
      </p>
      <ScenarioReset onReset={onReset} onFeedback={setFeedback} />
      {pendingAction ? (
        <ActionConfirmation
          open
          action={pendingAction.type}
          invokingElement={pendingAction.invokingElement}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => {
            const action = pendingAction.type
            setPendingAction(null)
            execute(action)
          }}
        />
      ) : null}
    </section>
  )
}

function labelFor(action: DemoActionType): string {
  return ACTIONS.find((candidate) => candidate.type === action)?.label ?? action
}

function isRejectedTransition(value: unknown): value is { accepted: false; event?: { summary?: string } } {
  return typeof value === "object" && value !== null && "accepted" in value && (value as { accepted?: unknown }).accepted === false
}
