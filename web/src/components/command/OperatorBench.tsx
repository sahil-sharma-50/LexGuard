"use client"

import { useId, useRef, useState } from "react"
import { postControl, postVeto } from "../../lib/api"
import { API_BASE_CONFIGURED } from "../../lib/apiBase"
import type { CaseProjection, ControlAction, ControlResult } from "../../lib/types"
import { ActionConfirmation } from "../ActionConfirmation"

type PendingAction =
  | { kind: "control"; action: ControlAction; label: string; description: string }
  | { kind: "veto"; caseId: string; label: string; description: string }

const CONTROLS: Array<{ action: ControlAction; label: string; note: string; danger?: boolean }> = [
  { action: "pause", label: "Pause entries", note: "Hold new entries at the coming session windows. Open orders and positions are untouched." },
  { action: "resume", label: "Resume entries", note: "Let the court sit again at the next session window." },
  { action: "emergency-stop", label: "Emergency stop", note: "Disable all new entries now. Only a server-side re-arm reverses this.", danger: true },
]

export function OperatorBench({ pendingCases, onActionComplete }: { pendingCases: CaseProjection[]; onActionComplete?: () => void }) {
  // The operator token lives only in this component's memory for the session.
  // It is never persisted, logged, or echoed back into the page.
  const [token, setToken] = useState("")
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [feedback, setFeedback] = useState<ControlResult | null>(null)
  const [busy, setBusy] = useState(false)
  const invokerRef = useRef<HTMLElement | null>(null)
  const tokenFieldId = useId()

  const armed = token.trim().length > 0 && API_BASE_CONFIGURED
  const disabledReason = !API_BASE_CONFIGURED
    ? "Controls are unavailable: NEXT_PUBLIC_API_BASE_URL is not configured for this build."
    : token.trim().length === 0
      ? "Enter the operator token to arm the bench. Until then the controls stay visible but disabled."
      : null

  const confirm = async () => {
    if (!pending) return
    setBusy(true)
    setFeedback(null)
    const submittedToken = token
    const result = pending.kind === "control"
      ? await postControl(pending.action, submittedToken)
      : await postVeto(pending.caseId, submittedToken)
    setBusy(false)
    setPending(null)
    setFeedback(result)
    if (result.ok) onActionComplete?.()
  }

  const request = (action: PendingAction) => (event: React.MouseEvent<HTMLButtonElement>) => {
    invokerRef.current = event.currentTarget
    setFeedback(null)
    setPending(action)
  }

  return (
    <section className="panel bench-panel" aria-labelledby="operator-bench-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">Zone III · the bench</p>
          <h3 id="operator-bench-title">Operator bench</h3>
        </div>
        <span className="provenance-badge">stop-only</span>
      </div>
      <p className="muted-copy">
        A human can pause, veto, or stop the court, and can never make it trade. Every control below only
        removes permission; none creates an order.
      </p>
      <div className="bench-token">
        <p className="bench-step-label">1. Arm the bench</p>
        <label htmlFor={tokenFieldId}>Operator token</label>
        <input
          id={tokenFieldId}
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="Held in memory for this session only"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <p className="bench-token-note">Sent per request as X-Operator-Token. Never stored, never persisted, cleared when you leave.</p>
      </div>
      <div className="bench-actions">
        <p className="bench-step-label">2. Stop-only controls</p>
        {CONTROLS.map((control) => (
          <div key={control.action} className={control.danger ? "bench-action bench-action-danger" : "bench-action"}>
            <button
              type="button"
              className={`btn ${control.danger ? "btn-danger" : ""}`}
              disabled={!armed || busy}
              onClick={request({ kind: "control", action: control.action, label: control.label, description: `${control.note} This is a stop-only power on the Alpaca paper service; it cannot initiate a trade.` })}
            >
              <span>{control.label}</span>
              <span aria-hidden="true">{control.danger ? "⏻" : "›"}</span>
            </button>
            <p className="bench-action-note">{control.note}</p>
          </div>
        ))}
      </div>
      {disabledReason && <p className="bench-disabled-note" role="status">{disabledReason}</p>}
      {feedback && (
        <p className={`bench-feedback ${feedback.ok ? "bench-feedback-ok" : "bench-feedback-error"}`} role={feedback.ok ? "status" : "alert"}>
          {feedback.message}
        </p>
      )}
      <div className="bench-veto-list" aria-label="Cases awaiting a certificate">
        <p className="quiet-caption" style={{ margin: 0 }}>
          {pendingCases.length > 0
            ? "Per-case veto: available only while a case still awaits its certificate."
            : "Per-case veto appears here while a case awaits its certificate. No case is currently pending."}
        </p>
        {pendingCases.map((item) => (
          <div className="bench-veto-row" key={item.case_id}>
            <span className="mono-chip">{item.underlying ?? "?"} · {item.decision_window} ET · {item.state} · {item.case_id.slice(0, 8)}…</span>
            <button
              type="button"
              className="btn btn-danger"
              disabled={!armed || busy}
              onClick={request({ kind: "veto", caseId: item.case_id, label: `Veto case ${item.case_id.slice(0, 8)}`, description: "Record a veto for this pending case. The risk gate will refuse to certify it and no order can be submitted. Vetoing cannot be undone and cannot start a different trade." })}
            >
              Veto
            </button>
          </div>
        ))}
      </div>
      <ActionConfirmation
        open={pending !== null}
        actionLabel={pending?.label}
        title={pending?.label}
        description={pending?.description}
        onConfirm={() => void confirm()}
        onCancel={() => setPending(null)}
        invokingElement={invokerRef.current}
      />
    </section>
  )
}
