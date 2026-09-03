import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"

const globalsCss = readFileSync("src/app/globals.css", "utf8")
const actionConfirmationSource = readFileSync("src/components/ActionConfirmation.tsx", "utf8")
const scenarioResetSource = readFileSync("src/components/ScenarioReset.tsx", "utf8")
const operatorBenchSource = readFileSync("src/components/command/OperatorBench.tsx", "utf8")

describe("court record style contract", () => {
  it("sets a Midnight Record canvas with readable global type", () => {
    expect(globalsCss).toMatch(/color-scheme:\s*dark/)
    expect(globalsCss).toMatch(/--paper:\s*#0f1720/)
    expect(globalsCss).toMatch(/--sheet:\s*#18232e/)
    expect(globalsCss).toMatch(/--text:\s*#f1eee7/)
    expect(globalsCss).toMatch(/--accent:\s*#a94f63/)
    expect(globalsCss).toMatch(/body\s*\{[^}]*font-size:\s*17px/)
  })

  it("keeps the console-only primary link styles inside the console shell", () => {
    expect(globalsCss).not.toMatch(/(^|,\s*)\.primary-link(?:[,{:\s])/m)
    expect(globalsCss).toMatch(/\.console-shell \.primary-link/)
  })

  it("reserves the seal accent for the landing primary action and console actions", () => {
    expect(globalsCss).toMatch(/\.landing-primary-action[^}]*background:\s*var\(--accent\)/)
    expect(globalsCss).toMatch(/\.console-shell \.primary-link[^}]*background:\s*var\(--accent\)/)
  })

  it("uses the display face for the masthead wordmarks", () => {
    expect(globalsCss).toMatch(/\.masthead-wordmark[^}]*font-family:\s*var\(--font-display\)/)
    expect(globalsCss).toMatch(/\.console-shell \.console-wordmark\s*\{[^}]*font-family:\s*var\(--font-display\)/)
  })

  it("keeps interactive landing, command, and simulator targets at least 44px tall", () => {
    // At least 44px: the landing actions are set at print-form height (46px).
    expect(globalsCss).toMatch(/\.landing-primary-action[^}]*min-height:\s*(?:4[4-9]|[5-9]\d)px/)
    expect(globalsCss).toMatch(/\.landing-secondary-action[^}]*min-height:\s*(?:4[4-9]|[5-9]\d)px/)
    expect(globalsCss).toMatch(/\.masthead-section-link[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/\.masthead-console-link, \.masthead-exit[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/\.console-hub-tabs a[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/\.console-training-header nav a[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/\.console-shell \.scenario-action-list button[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/^\.btn\s*\{[^}]*min-height:\s*44px/m)
    expect(globalsCss).toMatch(/\.bench-token input[^}]*min-height:\s*44px/)
  })

  it("pins the powers limits to a shared baseline", () => {
    expect(globalsCss).toMatch(/\.power-row\s*\{[^}]*display:\s*flex/)
    expect(globalsCss).toMatch(/\.power-body\s*\{[^}]*flex:\s*1/)
    expect(globalsCss).toMatch(/\.power-limit\s*\{[^}]*margin:\s*auto 0 0/)
  })

  it("keeps dialog and reset controls at least 44px tall with scoped hooks", () => {
    expect(actionConfirmationSource).toMatch(/className="dialog-action-cancel"/)
    expect(actionConfirmationSource).toMatch(/className="dialog-action-confirm"/)
    expect(scenarioResetSource).toMatch(/className="scenario-reset-trigger"/)
    expect(globalsCss).toMatch(/\.dialog-action-cancel, \.dialog-action-confirm[^}]*min-height:\s*44px/)
    expect(globalsCss).toMatch(/\.console-shell \.scenario-reset-trigger[^}]*min-height:\s*44px/)
  })

  it("keeps a visible focus indicator on every focusable control", () => {
    expect(globalsCss).toMatch(/a:focus-visible, button:focus-visible, summary:focus-visible, input:focus-visible, \[tabindex\]:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\)/)
  })

  it("provides a static reduced-motion fallback and one authored hero entrance", () => {
    expect(globalsCss).toMatch(/prefers-reduced-motion:\s*no-preference[\s\S]*\.hero-rail[^}]*animation:\s*docket-rise/)
    expect(globalsCss).toMatch(/\.calibration-instrument-svg \.calibration-trace[^}]*animation:\s*trace-reveal/)
    expect(globalsCss).toMatch(/prefers-reduced-motion:\s*reduce[^}]*\.calibration-instrument-svg \.calibration-trace/)
    expect(globalsCss).toMatch(/prefers-reduced-motion:\s*reduce[\s\S]*animation-duration:\s*\.01ms\s*!important/)
  })

  it("never persists the operator token", () => {
    expect(operatorBenchSource).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB/i)
    expect(operatorBenchSource).toMatch(/type="password"/)
    expect(operatorBenchSource).toMatch(/autoComplete="off"/)
  })
})
