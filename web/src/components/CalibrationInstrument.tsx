"use client"

import { getFixture } from "../lib/simulator/fixtures"
import { selectBrokerState } from "../lib/simulator/selectors"
import type { DemoRun, ScenarioId } from "../lib/simulator/types"

const STAGES = ["EVIDENCE", "ARGUMENT", "RISK GATE", "BROKER", "VERDICT"] as const

export function CalibrationInstrument({
  run,
  scenarioId,
}: {
  run: DemoRun | null
  scenarioId?: ScenarioId
}) {
  const resolvedScenario = run?.scenarioId ?? scenarioId ?? "guided-certifiable-v1"
  const fixture = getFixture(resolvedScenario)
  const broker = selectBrokerState(run)
  const vetoed = run?.lifecycle === "vetoed"
  const stages = STAGES.map((label) => ({
    label,
    status: statusFor(label, run, fixture.evidence.length, broker.status),
  }))

  return (
    <section className="calibration-instrument" aria-labelledby="calibration-instrument-title">
      <div className="section-heading">
        <div>
          <p className="section-label">Deterministic state instrument</p>
          <h2 id="calibration-instrument-title">Calibration instrument</h2>
        </div>
        <span className="quiet-caption">{fixture.symbol} · synthetic fixture</span>
      </div>
      <svg
        className="calibration-instrument-svg"
        viewBox="0 0 720 180"
        role="img"
        aria-labelledby="calibration-svg-title calibration-svg-description"
      >
        <title id="calibration-svg-title">Calibration instrument for the supervised synthetic run</title>
        <desc id="calibration-svg-description">
          A bounded trace connecting observed evidence, the argument and its abstention semantics, the {vetoed ? "closed " : ""}deterministic risk gate, the broker boundary, and the verdict. Geometry carries no additional market values.
        </desc>
        <path className="calibration-trace calibration-trace-evidence" d="M40 118 C140 74 188 138 286 92" />
        <path className="calibration-trace calibration-trace-argument" d="M286 92 S440 44 520 91" />
        <line
          className={`calibration-risk-gate-marker ${vetoed ? "calibration-risk-gate-marker-closed" : ""}`}
          x1="520"
          y1="26"
          x2="520"
          y2="154"
          role="img"
          aria-label={vetoed ? "Closed risk gate" : "Risk gate marker"}
        />
        {vetoed ? <rect className="calibration-risk-gate-marker calibration-risk-gate-marker-closed" x="512" y="83" width="16" height="16" rx="1" aria-hidden="true" /> : null}
        <path className="calibration-trace calibration-trace-broker" d="M520 91 S620 125 680 60" />
        {stages.map((stage, index) => {
          const x = 40 + index * 160
          const y = index === stages.length - 1 ? 60 : index % 2 === 0 ? 118 : 92
          const tone = toneFor(stage.label, stage.status, vetoed)
          const terminalClass = vetoed && stage.label === "VERDICT" ? " calibration-terminal-gate-node" : ""
          return <circle className={`calibration-stage-node calibration-stage-node-${tone}${terminalClass}`} key={stage.label} cx={x} cy={y} r="8" opacity={stage.status === "NOT RUN" ? 0.28 : 1} />
        })}
      </svg>
      <ol className="calibration-stage-list" aria-label="Calibration stages">
        {stages.map((stage) => (
          <li key={stage.label} className={`calibration-stage calibration-stage-${stage.status.toLowerCase().replaceAll(" ", "-")}`}>
            <span className="calibration-stage-label">{stage.label}</span>
            <span className="calibration-stage-status">{stage.status}</span>
          </li>
        ))}
      </ol>
      <p className="section-label calibration-gate-label">Deterministic risk gate</p>
      {vetoed ? (
        <div className="calibration-terminal-gate" role="status" aria-label="Terminal gate: abstain, entry closed">
          <span className="calibration-terminal-gate-label">Terminal gate</span>
          <strong>ABSTAIN · CLOSED</strong>
          <span>Entry closed before certification.</span>
        </div>
      ) : null}
      <p className="micro-note">{run ? `Run ${run.runId} · ${run.lifecycle}` : "No active run selected."}</p>
    </section>
  )
}

function toneFor(stage: (typeof STAGES)[number], status: string, vetoed: boolean): string {
  switch (stage) {
    case "EVIDENCE":
      return "evidence"
    case "ARGUMENT":
      return "argument"
    case "RISK GATE":
      return vetoed ? "risk-gate-closed" : "risk-gate"
    case "BROKER":
      return "broker"
    case "VERDICT":
      return status === "CERTIFIED" ? "verdict-certified" : "verdict-abstain"
  }
}

function statusFor(
  stage: (typeof STAGES)[number],
  run: DemoRun | null,
  evidenceCount: number,
  brokerStatus: string,
): string {
  if (run === null) return "NOT RUN"
  switch (stage) {
    case "EVIDENCE":
      return run.evidenceCursor === 0 ? "NOT RUN" : run.evidenceCursor < evidenceCount ? "IN PROGRESS" : "RECORDED"
    case "ARGUMENT":
      return run.argument ?? "NOT RUN"
    case "RISK GATE":
      return run.riskGate?.output ?? "NOT RUN"
    case "BROKER":
      return brokerStatus
    case "VERDICT":
      return verdictFor(run)
  }
}

function verdictFor(run: DemoRun): string {
  switch (run.lifecycle) {
    case "vetoed":
      return "ABSTAIN"
    case "certified":
      return "CERTIFIED"
    case "closed":
      return "CLOSED"
    case "broker_unknown":
      return "UNKNOWN"
    default:
      return "PENDING"
  }
}
