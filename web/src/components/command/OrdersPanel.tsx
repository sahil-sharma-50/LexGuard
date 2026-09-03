"use client"

import { formatMoney, UNKNOWN_VALUE } from "../../lib/format"
import type { OrderRow } from "../../lib/types"
import type { PanelData } from "./types"

const LIVE_STATUSES = new Set(["NEW", "ACCEPTED", "PENDING_NEW", "PENDING_REPLACE", "PARTIALLY_FILLED", "WORKING", "SUBMITTED", "REPLACED"])
const DONE_STATUSES = new Set(["FILLED", "DONE_FOR_DAY", "CLOSED"])

function statusTone(status: string): string {
  const normalized = status.toUpperCase()
  if (LIVE_STATUSES.has(normalized)) return "order-status-live"
  if (DONE_STATUSES.has(normalized)) return "order-status-done"
  return "order-status-dead"
}

export function OrdersPanel({ orders }: { orders: PanelData<OrderRow[]> }) {
  return (
    <section className="panel" aria-labelledby="orders-title">
      <div className="section-heading">
        <div className="panel-title">
          <p className="section-label">The ledger · orders</p>
          <h3 id="orders-title">Orders</h3>
        </div>
        <span className="provenance-badge">Alpaca order IDs</span>
      </div>
      {orders.status === "ok" && orders.data.length > 0 ? (
        <div className="ledger-table-wrap">
          <table className="ledger-table">
            <caption>Broker order lifecycle, paper endpoint</caption>
            <thead>
              <tr><th scope="col">Order</th><th scope="col">Status</th><th scope="col">Filled</th><th scope="col">Avg fill</th></tr>
            </thead>
            <tbody>
              {orders.data.map((order) => (
                <tr key={order.orderId}>
                  <td>
                    {order.clientOrderId ?? order.orderId}
                    <br />
                    <span className="quiet-caption">alpaca {order.orderId.slice(0, 13)}…</span>
                  </td>
                  <td><span className={`order-status ${statusTone(order.status)}`}>{order.status}</span></td>
                  <td>{order.filledQuantity}</td>
                  <td>{order.averageFillPrice !== null ? formatMoney(order.averageFillPrice) : UNKNOWN_VALUE}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : orders.status === "ok" ? (
        <p className="empty-state" role="status">No orders on the tape today.</p>
      ) : orders.status === "loading" ? (
        <p className="empty-state" role="status">Reading orders…</p>
      ) : (
        <p className="panel-unavailable" role="status">
          <strong>{orders.status === "unconfigured" ? "Not configured" : "Orders unavailable"}</strong>: {orders.reason}
        </p>
      )}
    </section>
  )
}
