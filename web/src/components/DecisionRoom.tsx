"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { getFixture } from "../lib/simulator/fixtures"
import {
  selectAuditEvents,
  selectBrokerState,
  selectRationale,
  selectRiskGate,
} from "../lib/simulator/selectors"
import type { DemoRun, ScenarioId } from "../lib/simulator/types"
import { AuditLog } from "./AuditLog"
import { CalibrationInstrument } from "./CalibrationInstrument"
import { ScenarioControls } from "./ScenarioControls"
import { useSimulatorSnapshot, useSimulatorStore } from "./SimulatorProvider"
import { StructuredRationale } from "./StructuredRationale"

export interface DecisionRoomProps {
  requestedScenario?: string
  requestedRun?: string
  readOnlyRun?: DemoRun
}

export function DecisionRoom({ requestedScenario, requestedRun, readOnlyRun }: DecisionRoomProps) {
  const state = useSimulatorSnapshot()
  const store = useSimulatorStore()
  const [starting, setStarting] = useState(false)
  const [activationError, setActivationError] = useState<string | null>(null)
  const previousActiveRun = useRef<DemoRun | null>(state.activeRun)
  const completionRedirected = useRef<string | null>(null)
  const scenario = toScenarioId(requestedScenario)
  const active = state.activeRun
  const requestedHistoryRun = requestedRun ? state.runHistory.find((run) => run.runId === requestedRun) ?? null : null
  const terminalRun = !requestedRun && scenario !== null && active === null
    ? state.runHistory.find((run) => run.runId === previousActiveRun.current?.runId && run.scenarioId === scenario && (run.lifecycle === "vetoed" || run.lifecycle === "closed")) ?? null
    : null
  const selectedRun = readOnlyRun ?? requestedHistoryRun ?? terminalRun ?? (requestedRun ? (active?.runId === requestedRun ? active : null) : scenario ? (active?.scenarioId === scenario ? active : null) : active)
  const unknownRequest = (requestedRun && requestedHistoryRun === null && active?.runId !== requestedRun) || (requestedScenario !== undefined && scenario === null)
  const conflict = !requestedRun && scenario !== null && active !== null && active.scenarioId !== scenario

  useEffect(() => {
    previousActiveRun.current = active
    if (terminalRun) {
      if (completionRedirected.current !== terminalRun.runId) {
        completionRedirected.current = terminalRun.runId
        if (typeof window !== "undefined") {
          window.history.replaceState(null, "", `/console/decision-room?run=${encodeURIComponent(terminalRun.runId)}`)
        }
      }
      return
    }
    if (readOnlyRun || requestedRun || scenario === null || active !== null || starting) return
    setStarting(true)
    const result = store.activateScenario(scenario)
    if (result.blocked) setActivationError(result.reason)
    setStarting(false)
  }, [active, readOnlyRun, requestedRun, scenario, starting, store, terminalRun])

  if (unknownRequest) return <UnknownSelection requested={requestedRun ?? requestedScenario ?? "unknown"} />
  if (conflict) return <ActiveConflict activeRun={active} requestedScenario={scenario} />
  if (starting && selectedRun === null) {
    return (
      <main className="decision-room decision-room-starting" aria-labelledby="decision-room-starting-title">
        <p className="section-label">Synthetic workbench</p>
        <h1 id="decision-room-starting-title">Starting scenario</h1>
        <p className="subpage-lede">Creating the browser-local authored run. No broker or network call is involved.</p>
      </main>
    )
  }
  if (activationError && selectedRun === null) {
    return <UnknownSelection requested={scenario ?? "unknown"} detail={activationError} />
  }
  if (requestedRun && selectedRun === null) return <UnknownSelection requested={requestedRun} />

  const run = selectedRun
  const fixture = getFixture(run?.scenarioId ?? scenario ?? "guided-certifiable-v1")
  const rationale = selectRationale(run)
  const riskGate = selectRiskGate(run)
  const broker = selectBrokerState(run)
  const isReadOnly = readOnlyRun !== undefined || terminalRun !== null || (requestedRun !== undefined && requestedHistoryRun !== null)

  return (
    <main
      className="decision-room"
      aria-labelledby="decision-room-title"
      data-dialog-focus-fallback="true"
      tabIndex={-1}
    >
      <header className="decision-room-heading">
        <p className="section-label">Supervised synthetic case</p>
        <h1 id="decision-room-title">Decision room</h1>
        <p className="subpage-lede">{scenarioLabel(fixture.scenarioId)} · {run ? `run ${run.runId}` : "authored fixture"} · browser-local deterministic state.</p>
        {isReadOnly ? <p className="fixture-notice" role="status">Read-only completed run. Controls are available only for the active run.</p> : null}
      </header>
      <StructuredRationale rationale={rationale} />
      <CalibrationInstrument run={run} scenarioId={fixture.scenarioId} />
      {!isReadOnly && run ? (
        <ScenarioControls run={run} onReset={() => store.reset()} />
      ) : (
        <p className="read-only-state">{isReadOnly ? "Read-only completed run; no supervised demo actions are available." : "No active run; supervised demo actions are unavailable until a scenario starts."}</p>
      )}
      <RiskGateExplanation run={run} />
      <section className="decision-room-audit" aria-labelledby="decision-room-audit-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Trace</p>
            <h2 id="decision-room-audit-title">Technical event log</h2>
          </div>
          <span className="quiet-caption">{selectAuditEvents(run).length} recorded events</span>
        </div>
        <AuditLog events={selectAuditEvents(run)} />
      </section>
    </main>
  )
}

function RiskGateExplanation({ run }: { run: DemoRun | null }) {
  const gate = selectRiskGate(run)
  const broker = selectBrokerState(run)
  return (
    <section className="risk-gate-explanation" aria-labelledby="risk-gate-explanation-title">
      <div className="section-heading">
        <div>
          <p className="section-label">Policy boundary</p>
          <h2 id="risk-gate-explanation-title">Deterministic risk gate</h2>
        </div>
        <span className={`status-word ${gate?.output === "PASS" ? "status-good" : "status-warning"}`}>{gate?.output ?? "NOT EVALUATED"}</span>
      </div>
      <p className="muted-copy">The risk gate is a deterministic fixture check. It is separate from the bounded argument and does not connect to a broker.</p>
      <dl>
        <div><dt>Ratio and expiration</dt><dd>{gate ? `${gate.equalRatio && gate.sameExpiration ? "PASS" : "FAIL"}` : "NOT EVALUATED"}</dd></div>
        <div><dt>Covered legs</dt><dd>{gate ? (gate.coveredLegs ? "PASS" : "FAIL") : "NOT EVALUATED"}</dd></div>
        <div><dt>Evidence freshness</dt><dd>{gate?.evidenceFreshness ?? "NOT EVALUATED"}</dd></div>
        <div><dt>Broker boundary</dt><dd>{broker.status} · SYNTHETIC</dd></div>
      </dl>
    </section>
  )
}

function UnknownSelection({ requested, detail }: { requested: string; detail?: string }) {
  return (
    <main className="decision-room-selection" aria-labelledby="selection-not-found-title">
      <p className="section-label">Synthetic workbench</p>
      <h1 id="selection-not-found-title">Scenario not found</h1>
      <p className="subpage-lede">{detail ?? `The requested scenario or run “${requested}” is not available in this browser-local simulator.`}</p>
      <Link prefetch={false} className="text-link" href="/console/decision-room?scenario=guided-certifiable-v1">Open guided certifiable</Link>
    </main>
  )
}

function ActiveConflict({ activeRun, requestedScenario }: { activeRun: DemoRun; requestedScenario: ScenarioId }) {
  return (
    <main className="decision-room-selection" aria-labelledby="active-conflict-title">
      <p className="section-label">Synthetic workbench</p>
      <h1 id="active-conflict-title">Active scenario conflict</h1>
      <p className="subpage-lede">Finish or reset the active run first before selecting {scenarioLabel(getFixture(requestedScenario).scenarioId)}.</p>
      <Link prefetch={false} className="text-link" aria-label={`Active run ${activeRun.runId}`} href={`/console/decision-room?run=${encodeURIComponent(activeRun.runId)}`}>Open active run {activeRun.runId}</Link>
    </main>
  )
}

function toScenarioId(value: string | undefined): ScenarioId | null {
  if (value === "guided-certifiable-v1" || value === "guided-catalyst-veto-v1") return value
  return value === undefined ? null : null
}

function scenarioLabel(scenarioId: ScenarioId): string {
  return scenarioId === "guided-catalyst-veto-v1" ? "Guided catalyst veto" : "Guided certifiable"
}
