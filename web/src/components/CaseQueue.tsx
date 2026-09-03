"use client"

import Link from "next/link"
import { SIMULATOR_FIXTURES } from "../lib/simulator/fixtures"
import { useSimulatorSnapshot } from "./SimulatorProvider"
import type { DemoEnvelope, DemoRun, ScenarioId } from "../lib/simulator/types"

const SCENARIO_LABELS: Record<ScenarioId, string> = {
  "guided-certifiable-v1": "Guided certifiable",
  "guided-catalyst-veto-v1": "Guided catalyst veto",
}

export function CaseQueue({ state: providedState, compact = false }: { state?: DemoEnvelope; compact?: boolean } = {}) {
  const contextState = useSimulatorSnapshot()
  const state = providedState ?? contextState
  const active = state.activeRun
  const history = [...state.runHistory].reverse()
  const entries = (Object.keys(SIMULATOR_FIXTURES) as ScenarioId[]).map((scenarioId) => {
    const fixture = SIMULATOR_FIXTURES[scenarioId]
    const current = active?.scenarioId === scenarioId
    return {
      id: `fixture-${scenarioId}`,
      label: SCENARIO_LABELS[scenarioId],
      href: `/console/decision-room?scenario=${scenarioId}`,
      lifecycle: current && active ? active.lifecycle : "not started",
      lastAction: current && active ? lastActionFor(active) : "No action recorded",
      verdict: fixture.forecast.rationale.recommendation === "VETO" ? "ABSTAIN" : "BASE",
      access: current ? "Current active run" : "Authored fixture",
    }
  })
  if (!compact && active) {
    entries.push(runEntry(active, "Current · active"))
  }
  if (!compact) {
    entries.push(...history.map((run) => runEntry(run, "Completed · read-only")))
  }

  return (
    <section className={`case-queue${compact ? " case-queue-compact" : ""}`} aria-labelledby="case-queue-title">
      <div className="section-heading">
        <div>
          <p className="section-label">Synthetic workbench</p>
          <h2 id="case-queue-title">Case queue</h2>
        </div>
        <Link prefetch={false} className="text-link" href="/console/cases">Open full queue</Link>
      </div>
      <p className="muted-copy">Authored fixtures and completed browser-local runs. No broker-backed cases are shown.</p>
      <table className="case-queue-table">
        <caption>Case queue</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Lifecycle state</th>
            <th scope="col">Last action</th>
            <th scope="col">Verdict</th>
            <th scope="col">Access</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <th scope="row"><Link prefetch={false} href={entry.href}>{entry.label}</Link></th>
              <td>{entry.lifecycle}</td>
              <td>{entry.lastAction}</td>
              <td>{entry.verdict}</td>
              <td>{entry.access}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ol className="case-queue-list">
        {entries.map((entry) => (
          <li className="case-queue-row" key={entry.id}>
            <Link prefetch={false} href={entry.href}>{entry.label}</Link>
            <dl className="case-queue-list-details">
              <div><dt>Lifecycle state</dt><dd>{entry.lifecycle}</dd></div>
              <div><dt>Last action</dt><dd>{entry.lastAction}</dd></div>
              <div><dt>Verdict</dt><dd>{entry.verdict}</dd></div>
              <div><dt>Access</dt><dd>{entry.access}</dd></div>
            </dl>
          </li>
        ))}
      </ol>
      {!compact && history.length === 0 ? <p className="empty-state">No completed runs yet. Start one from an authored fixture.</p> : null}
    </section>
  )
}

function runEntry(run: DemoRun, access: string) {
  return {
    id: `run-${run.runId}`,
    label: `${access.startsWith("Completed") ? "Completed run" : "Current run"} ${run.runId}`,
    href: `/console/decision-room?run=${encodeURIComponent(run.runId)}`,
    lifecycle: run.lifecycle,
    lastAction: lastActionFor(run),
    verdict: verdictFor(run),
    access,
  }
}

function lastActionFor(run: DemoRun): string {
  return run.auditEvents.at(-1)?.summary ?? "No action recorded"
}

function verdictFor(run: DemoRun): string {
  if (run.lifecycle === "vetoed") return "ABSTAIN"
  if (run.lifecycle === "certified") return "CERTIFIED"
  if (run.lifecycle === "closed") return "CLOSED"
  if (run.lifecycle === "broker_unknown") return "UNKNOWN"
  return "PENDING"
}
