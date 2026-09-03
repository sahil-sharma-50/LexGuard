export const UNKNOWN_VALUE = "n/a"

export function formatMoney(value: string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return UNKNOWN_VALUE
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(amount)
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return "Unknown time"
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "America/New_York" }).format(parsed)
}

export function environmentLabel(mode: string): string {
  return mode.replaceAll("_", " ")
}

export function formatSignedMoney(value: string | number): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return UNKNOWN_VALUE
  const formatted = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Math.abs(amount))
  return amount < 0 ? `−${formatted}` : `+${formatted}`
}

export function formatClockTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return UNKNOWN_VALUE
  return new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" }).format(parsed)
}

/** Expands an OCC option symbol (e.g. SPY260904P00640000) into leg detail. */
export function describeOptionSymbol(symbol: string): string {
  const match = /^([A-Z.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol.trim().toUpperCase())
  if (!match) return symbol
  const [, underlying, yy, mm, dd, right, strikeRaw] = match
  const strike = Number(strikeRaw) / 1000
  if (!Number.isFinite(strike)) return symbol
  return `${underlying} ${right === "C" ? "call" : "put"} ${strike.toLocaleString("en-US", { maximumFractionDigits: 3 })} · exp 20${yy}-${mm}-${dd}`
}
