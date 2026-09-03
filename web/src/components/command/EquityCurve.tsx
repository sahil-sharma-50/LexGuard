"use client"

import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { formatClockTime, formatMoney, formatSignedMoney } from "../../lib/format"
import type { AccountData, EquityPoint } from "../../lib/types"
import type { PanelData } from "./types"

function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: EquityPoint }> }) {
  const point = active ? payload?.[0]?.payload : undefined
  if (!point) return null
  return (
    <div className="chart-tooltip">
      <strong>{formatClockTime(point.recordedAt)} ET</strong>
      <span>{formatMoney(String(point.equity))}</span>
      <br />
      <span className={point.dailyPnl >= 0 ? "pnl-up" : "pnl-down"}>{formatSignedMoney(point.dailyPnl)} on the day</span>
    </div>
  )
}

export function EquityCurve({ history, account }: { history: PanelData<EquityPoint[]>; account: AccountData | null }) {
  const points = history.status === "ok" ? history.data : []
  const priorClose = account ? Number(account.lastEquity) : Number.NaN

  return (
    <section className="panel" aria-labelledby="equity-curve-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">The ledger · equity</p>
          <h3 id="equity-curve-title">Equity curve</h3>
        </div>
        <span className="provenance-badge">via Alpaca MCP · 1-min ledger</span>
      </div>
      {history.status === "ok" && points.length > 0 ? (
        <>
          <figure className="equity-chart-frame" aria-label={`Equity curve, ${points.length} one-minute readings`} style={{ margin: 0 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--accent-strong)" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="var(--accent-strong)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="var(--rule-soft)" />
                <XAxis
                  dataKey="recordedAt"
                  tickFormatter={formatClockTime}
                  tick={{ fill: "var(--ink-dim)", fontSize: 11, fontFamily: "var(--font-mono), monospace" }}
                  axisLine={{ stroke: "var(--rule)" }}
                  tickLine={false}
                  minTickGap={48}
                />
                <YAxis
                  domain={[(dataMin: number) => Math.floor(dataMin - 25), (dataMax: number) => Math.ceil(dataMax + 25)]}
                  tickFormatter={(value: number) => `$${Math.round(value).toLocaleString("en-US")}`}
                  tick={{ fill: "var(--ink-dim)", fontSize: 11, fontFamily: "var(--font-mono), monospace" }}
                  axisLine={false}
                  tickLine={false}
                  width={74}
                />
                <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--rule)", strokeWidth: 1 }} isAnimationActive={false} />
                {Number.isFinite(priorClose) && (
                  <ReferenceLine
                    y={priorClose}
                    stroke="var(--ink-dim)"
                    strokeDasharray="4 5"
                    label={{ value: "prior close", position: "insideTopRight", fill: "var(--ink-dim)", fontSize: 10, fontFamily: "var(--font-mono), monospace" }}
                  />
                )}
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="var(--accent-strong)"
                  strokeWidth={2}
                  fill="url(#equity-fill)"
                  dot={false}
                  activeDot={{ r: 4, stroke: "var(--bench)", strokeWidth: 2, fill: "var(--accent-strong)" }}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </figure>
          <details className="chart-table">
            <summary>View as table</summary>
            <table>
              <thead>
                <tr><th scope="col">Time (ET)</th><th scope="col">Equity</th><th scope="col">Day P&amp;L</th><th scope="col">Drawdown</th></tr>
              </thead>
              <tbody>
                {points.slice(-30).map((point) => (
                  <tr key={point.recordedAt}>
                    <td>{formatClockTime(point.recordedAt)}</td>
                    <td>{formatMoney(String(point.equity))}</td>
                    <td className={point.dailyPnl >= 0 ? "pnl-up" : "pnl-down"}>{formatSignedMoney(point.dailyPnl)}</td>
                    <td>{formatMoney(String(point.competitionDrawdown))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      ) : history.status === "ok" ? (
        <p className="empty-state" role="status">No equity readings recorded yet. The ledger adds one point per minute while the agent runs.</p>
      ) : history.status === "loading" ? (
        <p className="empty-state" role="status">Reading the equity ledger…</p>
      ) : (
        <p className="panel-unavailable" role="status">
          <strong>{history.status === "unconfigured" ? "Not configured" : "Equity history unavailable"}</strong>: {history.reason} · No curve is drawn from invented data.
        </p>
      )}
    </section>
  )
}
