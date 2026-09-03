"use client"

import { formatMoney, formatSignedMoney, UNKNOWN_VALUE } from "../../lib/format"
import type { AccountData } from "../../lib/types"
import type { PanelData } from "./types"

export const COMPETITION_DRAWDOWN_CAP = 4_000

export function AccountTiles({ account }: { account: PanelData<AccountData> }) {
  const data = account.status === "ok" ? account.data : null
  const dailyPnl = data ? Number(data.dailyPnl) : Number.NaN
  const drawdown = data ? Number(data.competitionDrawdown) : Number.NaN
  const drawdownShare = Number.isFinite(drawdown) ? Math.min(1, Math.max(0, drawdown / COMPETITION_DRAWDOWN_CAP)) : 0
  const meterTone = drawdownShare >= 0.8 ? "critical" : drawdownShare >= 0.5 ? "warning" : "ok"

  return (
    <>
      <div className="stat-tiles">
        <div className="stat-tile">
          <p className="stat-label">Equity</p>
          <p className="stat-value">{data ? formatMoney(data.equity) : <span className="stat-value-unknown">{UNKNOWN_VALUE}</span>}</p>
          <p className="stat-note">{data ? `Account ${data.status}${data.paperEndpoint ? " · paper endpoint" : ""}` : "Alpaca paper account"}</p>
        </div>
        <div className="stat-tile">
          <p className="stat-label">Day P&amp;L</p>
          <p className={`stat-value ${Number.isFinite(dailyPnl) ? (dailyPnl >= 0 ? "stat-delta-up" : "stat-delta-down") : ""}`}>
            {data && Number.isFinite(dailyPnl) ? formatSignedMoney(dailyPnl) : <span className="stat-value-unknown">{UNKNOWN_VALUE}</span>}
          </p>
          <p className="stat-note">{data ? `vs prior close ${formatMoney(data.lastEquity)}` : "vs prior close"}</p>
        </div>
        <div className="stat-tile">
          <p className="stat-label">Buying power</p>
          <p className="stat-value">{data ? formatMoney(data.buyingPower) : <span className="stat-value-unknown">{UNKNOWN_VALUE}</span>}</p>
          <p className="stat-note">{data && data.optionsLevel !== null ? `Options level ${data.optionsLevel}` : "Options approval unknown"}</p>
        </div>
        <div className="stat-tile">
          <p className="stat-label">Drawdown vs cap</p>
          <p className="stat-value">{data && Number.isFinite(drawdown) ? formatMoney(String(drawdown)) : <span className="stat-value-unknown">{UNKNOWN_VALUE}</span>}</p>
          {Number.isFinite(drawdown) ? (
            <div
              className={`drawdown-meter${meterTone === "critical" ? " drawdown-meter-critical" : meterTone === "warning" ? " drawdown-meter-warning" : ""}`}
              role="meter"
              aria-label="Competition drawdown against the $4,000 cap"
              aria-valuemin={0}
              aria-valuemax={COMPETITION_DRAWDOWN_CAP}
              aria-valuenow={Math.min(drawdown, COMPETITION_DRAWDOWN_CAP)}
            >
              <span className="drawdown-meter-fill" style={{ width: `${(drawdownShare * 100).toFixed(1)}%` }} aria-hidden="true" />
            </div>
          ) : (
            <div className="drawdown-meter" aria-hidden="true" />
          )}
          <p className="stat-note">
            {Number.isFinite(drawdown)
              ? `${(drawdownShare * 100).toFixed(1)}% of the $4,000 competition cap${meterTone === "critical" ? " · near the cap" : ""}`
              : "$4,000 competition cap"}
          </p>
        </div>
      </div>
      {account.status === "unavailable" && (
        <p className="panel-unavailable" role="status">
          <strong>Account read unavailable</strong>: {account.reason} · Values are withheld rather than estimated.
        </p>
      )}
      {account.status === "unconfigured" && (
        <p className="panel-unavailable" role="status">
          <strong>Not configured</strong>: {account.reason}
        </p>
      )}
    </>
  )
}
