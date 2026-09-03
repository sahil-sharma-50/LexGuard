import { API_BASE, API_CONFIG_ERROR } from "./apiBase"
import { ARCHIVED_CASE, ARCHIVED_CASE_ROUTE, ARCHIVED_RESEARCH } from "./archive"
import type {
  AccountData,
  CaseData,
  CaseProjection,
  ControlAction,
  ControlResult,
  Environment,
  EquityPoint,
  LiveReadResult,
  OrderRow,
  PerformanceData,
  PositionRow,
  ReadResult,
  ResearchSummaryData,
  RunMode,
} from "./types"

const REQUEST_TIMEOUT_MS = 5_000

export class PublicApiError extends Error {
  readonly status?: number
  readonly timedOut: boolean
  readonly notConfigured: boolean

  constructor(message: string, options: { status?: number; timedOut?: boolean; notConfigured?: boolean } = {}) {
    super(message)
    this.name = "PublicApiError"
    this.status = options.status
    this.timedOut = options.timedOut ?? false
    this.notConfigured = options.notConfigured ?? false
  }
}

export class UnknownCaseError extends Error {
  readonly caseId: string

  constructor(caseId: string) {
    super(`Case not found: ${caseId}`)
    this.name = "UnknownCaseError"
    this.caseId = caseId
  }
}

async function read<T>(path: string): Promise<T> {
  if (API_BASE === null) throw new PublicApiError(API_CONFIG_ERROR, { notConfigured: true })
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new PublicApiError(`Public read API returned ${response.status} for ${path}`, { status: response.status })
    }
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof PublicApiError) throw error
    if (error instanceof Error && error.name === "AbortError") {
      throw new PublicApiError(`Public read API timed out after ${REQUEST_TIMEOUT_MS}ms for ${path}`, { timedOut: true })
    }
    const detail = error instanceof Error ? error.message : "unknown network error"
    throw new PublicApiError(`Public read API request failed for ${path}: ${detail}`)
  } finally {
    clearTimeout(timeout)
  }
}

export function getCases(): Promise<{ items: CaseProjection[]; next_offset: number | null }> {
  return read("/api/cases")
}

export function getCase(caseId: string): Promise<CaseProjection> {
  return read(`/api/cases/${encodeURIComponent(caseId)}`)
}

export function getPerformance(): Promise<PerformanceData> {
  return read("/api/performance")
}

export async function getLiveCase(): Promise<ReadResult<CaseData>> {
  try {
    const list = await getCases()
    if (list.items.length === 0) throw new PublicApiError("Public read API returned no recorded cases")
    const projection = await getCase(list.items[0].case_id)
    const performance = await performanceForCase(projection)
    return { data: toCaseData(projection, performance.data), source: "public_api", notice: performance.notice }
  } catch (error) {
    return archived(ARCHIVED_CASE, describeFallback(error))
  }
}

export async function getArchivedCase(caseId: string): Promise<ReadResult<CaseData>> {
  if (caseId === ARCHIVED_CASE_ROUTE) return archived(ARCHIVED_CASE, "documented archived fixture route")
  let projection: CaseProjection
  try {
    projection = await getCase(caseId)
  } catch (error) {
    if (caseId === ARCHIVED_CASE.caseId) return archived(ARCHIVED_CASE, describeFallback(error))
    if (isNotFound(error)) throw new UnknownCaseError(caseId)
    throw error
  }

  const performance = await performanceForCase(projection)
  return { data: toCaseData(projection, performance.data), source: "public_api", notice: performance.notice }
}

async function performanceForCase(projection: CaseProjection): Promise<{ data: PerformanceData; notice?: string }> {
  try {
    return { data: await getPerformance() }
  } catch (error) {
    return {
      data: {
        environment: projection.environment,
        mode: projection.mode,
        asOf: projection.as_of ?? "",
        provenance: "Performance unavailable",
        metrics: {},
      },
      notice: `Performance ledger unavailable: ${describeFallback(error)} Metrics are shown as unknown; the recorded case was retained.`,
    }
  }
}

export async function getResearchSummary(): Promise<ReadResult<ResearchSummaryData>> {
  try {
    const data = await read<{
      environment: Environment
      as_of: string
      provenance: string
      gate: string
      metrics: Record<string, unknown>
    }>("/api/research/summary")
    return {
      data: { environment: data.environment, asOf: data.as_of, provenance: data.provenance, gate: data.gate, metrics: data.metrics },
      source: "public_api",
    }
  } catch (error) {
    return archived(ARCHIVED_RESEARCH, describeFallback(error))
  }
}

/* ----------------------------------------------------------------------------
 * Live command-center reads. There is no archived fixture for money data:
 * a failed read returns an explicit unavailable state, never invented numbers.
 * ------------------------------------------------------------------------- */

async function liveRead<Raw, T>(path: string, map: (raw: Raw) => T): Promise<LiveReadResult<T>> {
  try {
    const raw = await read<Raw>(path)
    return { status: "ok", data: map(raw) }
  } catch (error) {
    if (error instanceof PublicApiError && error.notConfigured) {
      return { status: "unconfigured", reason: API_CONFIG_ERROR }
    }
    return { status: "unavailable", reason: describeFallback(error) }
  }
}

export function getAccount(): Promise<LiveReadResult<AccountData>> {
  return liveRead<Record<string, unknown>, AccountData>("/api/account", (raw) => ({
    status: stringValue(raw.status) ?? "UNKNOWN",
    equity: stringValue(raw.equity) ?? "",
    lastEquity: stringValue(raw.last_equity) ?? "",
    dailyPnl: stringValue(raw.daily_pnl) ?? "",
    competitionDrawdown: stringValue(raw.competition_drawdown) ?? "",
    buyingPower: stringValue(raw.buying_power) ?? "",
    optionsLevel: Number.isFinite(Number(raw.options_level)) ? Number(raw.options_level) : null,
    paperEndpoint: raw.paper_endpoint === true,
  }))
}

export function getPositions(): Promise<LiveReadResult<PositionRow[]>> {
  return liveRead<{ positions?: unknown }, PositionRow[]>("/api/positions", (raw) =>
    (Array.isArray(raw.positions) ? raw.positions : []).flatMap((item) => {
      const row = object(item)
      if (!row || typeof row.symbol !== "string") return []
      return [{
        symbol: row.symbol,
        quantity: Number.isFinite(Number(row.quantity)) ? Number(row.quantity) : 0,
        side: stringValue(row.side) ?? "unknown",
        unrealizedPnl: stringValue(row.unrealized_pnl) ?? null,
      }]
    }),
  )
}

export function getOrders(): Promise<LiveReadResult<OrderRow[]>> {
  return liveRead<{ orders?: unknown }, OrderRow[]>("/api/orders", (raw) =>
    (Array.isArray(raw.orders) ? raw.orders : []).flatMap((item) => {
      const row = object(item)
      if (!row) return []
      const orderId = stringValue(row.order_id)
      if (!orderId) return []
      return [{
        orderId,
        status: stringValue(row.status) ?? "UNKNOWN",
        filledQuantity: Number.isFinite(Number(row.filled_quantity)) ? Number(row.filled_quantity) : 0,
        averageFillPrice: stringValue(row.average_fill_price) ?? null,
        clientOrderId: stringValue(row.client_order_id) ?? null,
      }]
    }),
  )
}

export function getRecentCases(limit = 12): Promise<LiveReadResult<CaseProjection[]>> {
  return liveRead<{ items?: unknown }, CaseProjection[]>(`/api/cases?offset=0&limit=${limit}`, (raw) =>
    (Array.isArray(raw.items) ? raw.items : []).flatMap((item) => {
      const projection = object(item)
      return projection && typeof projection.case_id === "string" ? [projection as unknown as CaseProjection] : []
    }),
  )
}

export function getPerformanceHistory(): Promise<LiveReadResult<EquityPoint[]>> {
  return liveRead<{ points?: unknown }, EquityPoint[]>("/api/performance/history", (raw) =>
    (Array.isArray(raw.points) ? raw.points : []).flatMap((item) => {
      const point = object(item)
      const recordedAt = point ? stringValue(point.recorded_at) : undefined
      const equity = Number(point?.equity)
      if (!point || !recordedAt || !Number.isFinite(equity)) return []
      const dailyPnl = Number(point.daily_pnl)
      const competitionDrawdown = Number(point.competition_drawdown)
      return [{
        recordedAt,
        equity,
        dailyPnl: Number.isFinite(dailyPnl) ? dailyPnl : 0,
        competitionDrawdown: Number.isFinite(competitionDrawdown) ? competitionDrawdown : 0,
      }]
    }),
  )
}

/* ----------------------------------------------------------------------------
 * Stop-only operator controls. The token is passed through per request and is
 * never stored by this module. 401 and 503 are surfaced as distinct states.
 * ------------------------------------------------------------------------- */

async function postOperator(path: string, token: string, successMessage: string): Promise<ControlResult> {
  if (API_BASE === null) return { ok: false, kind: "unconfigured", message: API_CONFIG_ERROR }
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "X-Operator-Token": token },
      cache: "no-store",
      signal: controller.signal,
    })
    if (response.status === 401) return { ok: false, kind: "unauthorized", message: "Token refused (401). Check the operator token and try again; the token is never stored." }
    if (response.status === 503) return { ok: false, kind: "unconfigured", message: "Operator controls are not configured on the server (503). No action was taken." }
    if (!response.ok) return { ok: false, kind: "failed", message: `The control endpoint returned ${response.status}. No action is assumed; check the ledger.` }
    return { ok: true, message: successMessage }
  } catch (error) {
    const detail = error instanceof Error && error.name === "AbortError" ? "the request timed out" : "the API could not be reached"
    return { ok: false, kind: "failed", message: `Control request failed: ${detail}. No action is assumed; check the ledger.` }
  } finally {
    clearTimeout(timeout)
  }
}

const CONTROL_SUCCESS: Record<ControlAction, string> = {
  pause: "Pause acknowledged. New entries are held; open orders and positions are untouched.",
  resume: "Resume acknowledged. The agent may argue at the next session window.",
  "emergency-stop": "Emergency stop acknowledged. Entries are disabled until an operator re-arms the service.",
}

export function postControl(action: ControlAction, token: string): Promise<ControlResult> {
  return postOperator(`/api/controls/${action}`, token, CONTROL_SUCCESS[action])
}

export function postVeto(caseId: string, token: string): Promise<ControlResult> {
  return postOperator(`/api/cases/${encodeURIComponent(caseId)}/veto`, token, `Veto recorded for case ${caseId}. No certificate can be issued for it.`)
}

function archived<T>(data: T, reason: string): ReadResult<T> {
  return {
    data,
    source: "archived_fixture",
    notice: `Archived fixture data - ${reason} No live broker or credential access was attempted.`,
  }
}

function describeFallback(error: unknown): string {
  if (error instanceof PublicApiError) return error.message
  if (error instanceof Error) return `public read API error: ${error.message}`
  return "public read API is unavailable"
}

function isNotFound(error: unknown): boolean {
  return error instanceof PublicApiError && error.status === 404
}

function toCaseData(projection: CaseProjection, performance: PerformanceData): CaseData {
  const artifacts = objects(projection.artifacts)
  const forecast = artifacts.forecast_distribution
  const certificate = artifacts.trade_certificate
  const reasonCodes = projection.reason_codes.map(String)
  const state = projection.state.toUpperCase()
  const verdict = verdictForState(state)
  const nodes = Array.isArray(forecast?.nodes)
    ? forecast.nodes.flatMap((node) => {
        const value = object(node)
        const probability = Number(value?.probability)
        return value && Number.isFinite(probability)
          ? [{ returnValue: String(value.return_value ?? "0"), probability }]
          : []
      })
    : []

  return {
    caseId: projection.case_id,
    caseState: state,
    tradingDate: projection.trading_date,
    decisionWindow: projection.decision_window,
    underlying: projection.underlying ?? "Unknown underlying",
    verdict,
    verdictReason: reasonCodes.length
      ? `Recorded reason: ${reasonCodes.join(" · ")}. No public action is available.`
      : state === "SCHEDULED" || verdict === "PENDING"
        ? `The ${state.toLowerCase()} case has not reached a final ruling.`
        : `Recorded ledger state: ${state}. No public action is available.`,
    reasonCodes,
    environment: projection.environment,
    mode: projection.mode,
    asOf: projection.as_of ?? performance.asOf,
    evidence: evidenceFromArtifacts(artifacts),
    forecast: { nodes, artifactHash: String(forecast?.content_hash ?? "no-recorded-forecast") },
    certificate: certificate
      ? {
          status: "issued",
          policyVersion: String(certificate.policy_version ?? "recorded-policy"),
          proposalHash: stringValue(certificate.proposal_hash),
          expiresAt: stringValue(certificate.expires_at),
          maxLoss: stringValue(object(certificate.candidate)?.max_loss),
          robustEv: stringValue(object(certificate.candidate)?.robust_ev),
        }
      : { status: "not-issued", policyVersion: "no-recorded-certificate" },
    orderLifecycle: lifecycleForState(state, artifacts),
    performance: {
      realizedPnl: stringValue(performance.metrics.realized_pnl) ?? "unknown",
      totalReturn: stringValue(performance.metrics.total_return) ?? "Unknown",
      drawdown: stringValue(performance.metrics.drawdown ?? performance.metrics.max_drawdown) ?? "Unknown",
      provenance: performance.provenance,
    },
  }
}

function verdictForState(state: string): CaseData["verdict"] {
  if (state === "REFUSED") return "ABSTAIN"
  if (state === "CERTIFIED") return "CERTIFIED"
  if (["HALTED", "RECONCILE_REQUIRED", "CANCELED", "REJECTED"].includes(state)) return "HALTED"
  if (["SUBMITTED", "REPLACED"].includes(state)) return "WORKING"
  if (state === "PARTIALLY_FILLED") return "PARTIAL"
  if (["FILLED", "MANAGING"].includes(state)) return "MANAGING"
  if (state === "CLOSED") return "CLOSED"
  if (["SCHEDULED", "OBSERVED", "FORECASTED", "ARGUED"].includes(state)) return "PENDING"
  return "UNKNOWN"
}

function evidenceFromArtifacts(artifacts: Record<string, Record<string, unknown>>): CaseData["evidence"] {
  return Object.entries(artifacts).map(([key, artifact]) => {
    const normalized = key.replaceAll("_", " ")
    const label = normalized.charAt(0).toUpperCase() + normalized.slice(1)
    const state: CaseData["evidence"][number]["state"] = key === "refusal_record" || key === "halt_record" ? "warning" : "verified"
    return {
      label,
      value: artifactDescription(key, artifact),
      provenance: String(artifact.source ?? artifact.content_hash ?? "Ledger"),
      state,
    }
  })
}

function artifactDescription(key: string, artifact: Record<string, unknown>): string {
  const hash = stringValue(artifact.content_hash)
  if (key === "market_evidence") return hash ? `Recorded market evidence (${hash})` : "Recorded market evidence"
  if (key === "forecast_distribution") return hash ? `Recorded forecast distribution (${hash})` : "Recorded forecast distribution"
  if (key === "catalyst_assessment") return hash ? `Recorded catalyst assessment (${hash})` : "Recorded catalyst assessment"
  if (key === "trade_certificate") return "Risk certificate recorded"
  if (key === "refusal_record") return "Refusal recorded; no order was submitted"
  if (key === "halt_record") return "Safety halt recorded; broker state requires reconciliation"
  return hash ? `Recorded ledger artifact (${hash})` : "Recorded ledger artifact"
}

function lifecycleForState(state: string, artifacts: Record<string, Record<string, unknown>>): CaseData["orderLifecycle"] {
  const terminalBeforeOrder = state === "REFUSED"
  const safetyHalt = ["HALTED", "RECONCILE_REQUIRED", "CANCELED", "REJECTED"].includes(state)
  const unknownState = !KNOWN_CASE_STATES.has(state)
  const hasObservation = Boolean(artifacts.market_evidence)
  const hasForecast = Boolean(artifacts.forecast_distribution)
  const hasArgument = Boolean(artifacts.catalyst_assessment)
  const hasCertificate = Boolean(artifacts.trade_certificate)
  const orderEvidence = explicitOrderEvidence(artifacts)
  const hasSubmission = orderEvidence.some(({ key, artifact }) => isSubmissionArtifact(key, artifact))
  const orderDescription = orderEvidence.find(({ key, artifact }) => isSubmissionArtifact(key, artifact))
  const certified = hasCertificate
  return [
    { label: "Observed", state: hasObservation ? "complete" : "pending", detail: hasObservation ? "Evidence snapshot recorded" : "Awaiting evidence snapshot" },
    { label: "Forecasted", state: hasForecast ? "complete" : "pending", detail: hasForecast ? "Distribution artifact recorded" : "Awaiting forecast artifact" },
    { label: "Argued", state: hasArgument ? "complete" : "pending", detail: hasArgument ? "Catalyst assessment recorded" : "Awaiting catalyst assessment" },
    {
      label: "Certified",
      state: terminalBeforeOrder || safetyHalt || unknownState ? "blocked" : certified ? "complete" : "pending",
      detail: terminalBeforeOrder ? "No certificate; entry refused" : safetyHalt ? "Safety halt; certificate unavailable" : unknownState ? "Unknown case state; certificate status unavailable" : certified ? "Deterministic risk gate recorded" : "Awaiting deterministic risk gate",
    },
    {
      label: "Submitted",
      state: hasSubmission ? "complete" : terminalBeforeOrder || safetyHalt || unknownState ? "blocked" : "pending",
      detail: hasSubmission ? `Broker lifecycle recorded${orderDescription ? ` (${orderStatus(orderDescription.artifact)})` : ""}` : terminalBeforeOrder ? "Paper broker untouched" : safetyHalt ? "No public order action" : unknownState ? "Unknown case state; no order action" : "No recorded broker event",
    },
  ]
}

const EXPLICIT_ORDER_ARTIFACTS = new Set([
  "execution_record",
  "order_event",
  "order_submission",
  "order_replacement",
  "order_replace_event",
  "order_fill",
  "fill_event",
  "position_snapshot",
  "position_event",
  "management_event",
])

const KNOWN_CASE_STATES = new Set([
  "SCHEDULED",
  "OBSERVED",
  "FORECASTED",
  "ARGUED",
  "CERTIFIED",
  "SUBMITTED",
  "REPLACED",
  "PARTIALLY_FILLED",
  "FILLED",
  "MANAGING",
  "CLOSED",
  "REFUSED",
  "HALTED",
  "RECONCILE_REQUIRED",
  "CANCELED",
  "REJECTED",
])

const ACCEPTED_ORDER_STATES = new Set([
  "SUBMITTED",
  "WORKING",
  "NEW",
  "ACCEPTED",
  "PENDING_NEW",
  "PENDING_REPLACE",
  "REPLACED",
  "PARTIAL",
  "PARTIALLY_FILLED",
  "FILLED",
  "MANAGING",
])

function explicitOrderEvidence(artifacts: Record<string, Record<string, unknown>>) {
  return Object.entries(artifacts).filter(([key]) => EXPLICIT_ORDER_ARTIFACTS.has(key)).map(([key, artifact]) => ({ key, artifact }))
}

function isSubmissionArtifact(key: string, artifact: Record<string, unknown>): boolean {
  if (!EXPLICIT_ORDER_ARTIFACTS.has(key)) return false
  const status = orderStatus(artifact)
  return Boolean(status && ACCEPTED_ORDER_STATES.has(status) && hasBrokerOrderId(artifact))
}

function orderStatus(artifact: Record<string, unknown>): string | undefined {
  for (const key of ["state", "status", "broker_state", "order_status"]) {
    const value = artifact[key]
    if (typeof value === "string" && value.trim()) return value.toUpperCase()
  }
  return undefined
}

function hasBrokerOrderId(artifact: Record<string, unknown>): boolean {
  for (const key of ["alpaca_order_id", "order_id"]) {
    const value = artifact[key]
    if (typeof value === "string" && value.trim()) return true
  }
  for (const key of ["alpaca_order_ids", "order_ids"]) {
    const value = artifact[key]
    if (Array.isArray(value) && value.some((item) => typeof item === "string" && item.trim())) return true
  }
  return false
}

function objects(value: Record<string, unknown>): Record<string, Record<string, unknown>> {
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    const result = object(item)
    return result ? [[key, result]] : []
  }))
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function stringValue(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : String(value)
}
