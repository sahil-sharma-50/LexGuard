"use client"

import Link from "next/link"
import { getFixture } from "../lib/simulator/fixtures"
import { selectActionAvailabilities, selectAuditEvents, selectBrokerState, selectRationale } from "../lib/simulator/selectors"
import { useSimulatorPersistenceNotice, useSimulatorSnapshot } from "./SimulatorProvider"
import { AuditLog } from "./AuditLog"
import { CalibrationInstrument } from "./CalibrationInstrument"
import { CaseQueue } from "./CaseQueue"
import { StructuredRationale } from "./StructuredRationale"
import type { DemoRun } from "../lib/simulator/types"

export function OperationsOverview() {
  const state = useSimulatorSnapshot()
  const persistenceNotice = useSimulatorPersistenceNotice()
  const run = state.activeRun
  const fixture = run ? getFixture(run.scenarioId) : null
  const broker = selectBrokerState(run)
  const availableActions = run
    ? Object.entries(selectActionAvailabilities(run)).filter(([, availability]) => availability.enabled).map(([action]) => action)
    : []
  const persistenceStatus = persistenceNotice
    ? persistenceNotice.toLowerCase().includes("invalid")
      ? "RESET · AUTHORED SEED"
      : "UNAVAILABLE · SESSION-ONLY"
    : run
      ? "AVAILABLE · VERSIONED"
      : "READY · AUTHORED SEED"

  return (
    <main className="operations-overview" aria-labelledby="operations-overview-title">
      <header className="console-page-heading">
        <p className="section-label">Training room · synthetic replay</p>
        <h1 id="operations-overview-title">Operations overview</h1>
        <p className="subpage-lede">Orient to the active synthetic scenario, inspect its state, and enter the supervised decision room. Nothing here touches a market or a broker.</p>
      </header>
      <section className="overview-summary" aria-labelledby="overview-summary-title">
        <div>
          <p className="section-label">Current simulator state</p>
          <h2 id="overview-summary-title">{run ? `${scenarioLabel(run)} · ${verdictFor(run)}` : "No active scenario"}</h2>
          <p className="muted-copy">{run ? `Run ${run.runId} is ${run.lifecycle}. State is deterministic and browser-local.` : "Choose an authored fixture to start a browser-local run."}</p>
        </div>
        <div className="overview-summary-actions">
          <Link prefetch={false} className="primary-link" href={run ? `/console/decision-room?run=${encodeURIComponent(run.runId)}` : "/console/decision-room?scenario=guided-certifiable-v1"}>
            {run ? "Open active decision room" : "Start guided scenario"}
          </Link>
          <Link prefetch={false} className="text-link" href="/console/cases">Browse case queue</Link>
        </div>
      </section>
      <section className="overview-status" aria-labelledby="overview-status-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Boundary status</p>
            <h2 id="overview-status-title">System and simulator status</h2>
          </div>
        </div>
        <dl>
          <div><dt>Simulator</dt><dd>AVAILABLE · BROWSER-LOCAL</dd></div>
          <div><dt>Persistence</dt><dd>{persistenceStatus}</dd></div>
          <div><dt>Broker boundary</dt><dd>{broker.status === "NOT_STARTED" ? "NOT RUN · NO BROKER CALLS" : `${broker.status} · SYNTHETIC`}</dd></div>
          <div><dt>Action surface</dt><dd>{run ? `${availableActions.length} currently valid actions` : "NOT AVAILABLE · START A SCENARIO"}</dd></div>
        </dl>
      </section>
      <section className="overview-preview" aria-labelledby="overview-preview-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Decision workspace</p>
            <h2 id="overview-preview-title">Active decision room preview</h2>
          </div>
          {run ? <span className="quiet-caption">{run.runId}</span> : null}
        </div>
        <StructuredRationale rationale={selectRationale(run)} />
        <CalibrationInstrument run={run} scenarioId={fixture?.scenarioId} />
      </section>
      <section className="overview-actions" aria-labelledby="overview-actions-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Supervision</p>
            <h2 id="overview-actions-title">Currently valid demo actions</h2>
          </div>
        </div>
        {availableActions.length ? <ul>{availableActions.map((action) => <li key={action}>{action}</li>)}</ul> : <p className="empty-state">No actions are available until a scenario is active.</p>}
      </section>
      <section className="overview-audit" aria-labelledby="overview-audit-title">
        <div className="section-heading">
          <div>
            <p className="section-label">Trace</p>
            <h2 id="overview-audit-title">Technical event log</h2>
          </div>
        </div>
        <AuditLog events={selectAuditEvents(run)} />
      </section>
      <CaseQueue compact={false} />
    </main>
  )
}

function scenarioLabel(run: DemoRun | null): string {
  return run?.scenarioId === "guided-catalyst-veto-v1" ? "Guided catalyst veto" : "Guided certifiable"
}

function verdictFor(run: DemoRun): string {
  if (run.lifecycle === "vetoed") return "ABSTAIN"
  if (run.lifecycle === "certified") return "CERTIFIED"
  if (run.lifecycle === "closed") return "CLOSED"
  if (run.lifecycle === "broker_unknown") return "UNKNOWN"
  return "PENDING"
}
