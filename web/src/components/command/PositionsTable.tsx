"use client"

import { describeOptionSymbol, formatSignedMoney, UNKNOWN_VALUE } from "../../lib/format"
import type { PositionRow } from "../../lib/types"
import type { PanelData } from "./types"

export function PositionsTable({ positions }: { positions: PanelData<PositionRow[]> }) {
  return (
    <section className="panel" aria-labelledby="positions-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">The ledger · legs</p>
          <h3 id="positions-title">Open positions</h3>
        </div>
        <span className="provenance-badge">via Alpaca MCP</span>
      </div>
      {positions.status === "ok" && positions.data.length > 0 ? (
        <div className="ledger-table-wrap">
          <table className="ledger-table">
            <caption>Per-leg positions on the paper endpoint</caption>
            <thead>
              <tr><th scope="col">Leg</th><th scope="col">Qty</th><th scope="col">Side</th><th scope="col">Unrealized P&amp;L</th></tr>
            </thead>
            <tbody>
              {positions.data.map((position) => {
                const pnl = position.unrealizedPnl === null ? Number.NaN : Number(position.unrealizedPnl)
                return (
                  <tr key={`${position.symbol}-${position.side}`}>
                    <td>
                      {describeOptionSymbol(position.symbol)}
                      <br />
                      <span className="quiet-caption">{position.symbol}</span>
                    </td>
                    <td>{position.quantity}</td>
                    <td>{position.side}</td>
                    <td className={Number.isFinite(pnl) ? (pnl >= 0 ? "pnl-up" : "pnl-down") : undefined}>
                      {Number.isFinite(pnl) ? formatSignedMoney(pnl) : UNKNOWN_VALUE}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : positions.status === "ok" ? (
        <p className="empty-state" role="status">No open legs. The court is flat.</p>
      ) : positions.status === "loading" ? (
        <p className="empty-state" role="status">Reading positions…</p>
      ) : (
        <p className="panel-unavailable" role="status">
          <strong>{positions.status === "unconfigured" ? "Not configured" : "Positions unavailable"}</strong>: {positions.reason}
        </p>
      )}
    </section>
  )
}
