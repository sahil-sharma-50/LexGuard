"use client"

export const SYNTHETIC_DISCLOSURE = "GUIDED DEMO \u00b7 SYNTHETIC \u00b7 BROWSER-LOCAL \u00b7 NO ALPACA CALLS"

export function EnvironmentDisclosure() {
  return (
    <aside className="environment-disclosure" aria-label="Demo environment">
      <p>{SYNTHETIC_DISCLOSURE}</p>
    </aside>
  )
}
