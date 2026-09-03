import { expect, test, type Page } from "@playwright/test"

type SimulatorWindow = Window & {
  __simulatorNetworkCalls?: string[]
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls: string[] = []
    Object.defineProperty(window, "__simulatorNetworkCalls", { value: calls, configurable: true })

    const originalFetch = window.fetch.bind(window)
    window.fetch = ((...args: Parameters<typeof fetch>) => {
      calls.push(`fetch:${String(args[0])}`)
      return originalFetch(...args)
    }) as typeof window.fetch

    const originalOpen = XMLHttpRequest.prototype.open as unknown as (this: XMLHttpRequest, method: string, url: string | URL, async?: boolean, username?: string | null, password?: string | null) => void
    XMLHttpRequest.prototype.open = function (method: string, url: string | URL, async?: boolean, username?: string | null, password?: string | null) {
      calls.push(`xhr:${method}:${String(url)}`)
      return async === undefined
        ? originalOpen.call(this, method, url)
        : originalOpen.call(this, method, url, async, username, password)
    }

    const OriginalEventSource = window.EventSource
    if (typeof OriginalEventSource === "function") {
      window.EventSource = class extends OriginalEventSource {
        constructor(url: string | URL, init?: EventSourceInit) {
          calls.push(`sse:${String(url)}`)
          super(url, init)
        }
      }
    }

    const originalBeacon = navigator.sendBeacon?.bind(navigator)
    if (originalBeacon) {
      navigator.sendBeacon = (url, data) => {
        calls.push(`beacon:${String(url)}`)
        return originalBeacon(url, data)
      }
    }
  })
})

test("certifiable fixture persists, supports pause/resume, and closes normally without network calls", async ({ page }) => {
  await page.goto("/console/decision-room?scenario=guided-certifiable-v1")
  await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()

  await clearNetworkCalls(page)

  await completeCertifiableRunToAwaitingSupervision(page)
  await clickConfirm(page, "Veto proposal", "run-0001")
  await page.goto("/console/cases")
  await expect(page.locator("#console-cases-title")).toBeVisible()
  await expect(page.getByRole("link", { name: "Completed run run-0001", exact: true })).toBeVisible()
  await page.getByRole("link", { name: "Guided certifiable", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Advance evidence", exact: true })).toBeEnabled()
  await clearNetworkCalls(page)
  await clickAction(page, "Advance evidence")
  await expect(page.getByText("IN PROGRESS", { exact: true })).toBeVisible()
  await clickConfirm(page, "Reset demo", undefined, "Demo reset completed")
  await expect(page.getByText(/Run run-0001 · observing/i)).toBeVisible()

  const resetEnvelope = await page.evaluate(() => JSON.parse(window.localStorage.getItem("lexguard:demo:v1") ?? "null") as {
    activeRun?: { runId?: string; evidenceCursor?: number }
    runHistory?: unknown[]
  })
  expect(resetEnvelope).toBeNull()
  await expect(page.getByText("NOT RUN", { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/Technical audit log \(0 events\)/i)).toBeVisible()

  await page.goto("/console/cases")
  await expect(page.locator("#console-cases-title")).toBeVisible()
  await expect(page.getByText("No completed runs yet. Start one from an authored fixture.", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: /Completed run/i })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Current run run-0001", exact: true })).toBeVisible()

  await page.goto("/console/decision-room?scenario=guided-certifiable-v1")
  await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Advance evidence", exact: true })).toBeEnabled()
  await clearNetworkCalls(page)
  await clickAction(page, "Advance evidence")
  await expect(page.getByText("IN PROGRESS", { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText("IN PROGRESS", { exact: true })).toBeVisible()
  await clearNetworkCalls(page)

  await clickAction(page, "Pause scheduler")
  await clickAction(page, "Resume scheduler")

  const forecast = page.getByRole("button", { name: "Complete forecast", exact: true })
  await expect(forecast).toBeDisabled()
  await expect(page.locator("#scenario-action-reason-complete_forecast").first()).toBeVisible()

  for (let index = 0; index < 4; index += 1) await clickAction(page, "Advance evidence")
  await clickAction(page, "Complete forecast")
  await clickAction(page, "Complete argument")
  await expect(page.getByRole("button", { name: "Approve proposal", exact: true })).toBeEnabled()

  await clickConfirm(page, "Approve proposal")
  await clickAction(page, "Simulate submit")
  await clickAction(page, "Mark order working")
  await clickAction(page, "Record synthetic fill")
  await clickAction(page, "Present reconciliation")
  await clickAction(page, "Resolve reconciliation")
  await expect(page.getByRole("button", { name: "Close position", exact: true })).toBeEnabled()

  await clickConfirm(page, "Close position")
  await clickAction(page, "Complete close", "run-0001")
  await expect(page.getByText(/Read-only completed run/i).first()).toBeVisible()
  await expect(page.getByText("CLOSED", { exact: true }).first()).toBeVisible()
})

test("veto fixture records abstention and leaves the broker boundary untouched", async ({ page }) => {
  await page.goto("/console/decision-room?scenario=guided-certifiable-v1")
  await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()
  await clearNetworkCalls(page)

  await completeCertifiableRunToAwaitingSupervision(page)
  await clickConfirm(page, "Veto proposal", "run-0001")
  await expect(page.getByText(/Read-only completed run/i).first()).toBeVisible()
  await expect(page.getByText(/ABSTAIN · CLOSED/i)).toBeVisible()
  await expect(page.getByText(/no supervised demo actions are available/i)).toBeVisible()

  await page.goto("/console/decision-room?scenario=guided-catalyst-veto-v1")
  await expect(page.getByRole("button", { name: "Advance evidence", exact: true })).toBeEnabled()
  await clearNetworkCalls(page)

  for (let index = 0; index < 5; index += 1) await clickAction(page, "Advance evidence")
  await clickAction(page, "Complete forecast")
  await clickAction(page, "Complete argument", "run-0002")
  await expect(page.getByText(/Read-only completed run/i).first()).toBeVisible()
  await expect(page.getByText(/ABSTAIN · CLOSED/i)).toBeVisible()
})

test("failed reconciliation can be emergency-stopped and safely closed without network calls", async ({ page }) => {
  await page.goto("/console/decision-room?scenario=guided-certifiable-v1")
  await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()
  await clearNetworkCalls(page)
  await completeCertifiableRunToFill(page)
  await clickAction(page, "Present reconciliation")
  await expect(page.getByRole("button", { name: "Fail reconciliation", exact: true })).toBeEnabled()
  await clickAction(page, "Fail reconciliation")
  await page.locator("details.audit-log").last().locator("summary").click()
  await expect(page.getByText(/Reconciliation failed closed/i)).toBeVisible()

  await clickConfirm(page, "Emergency stop")
  await clickConfirm(page, "Close position")
  await clickAction(page, "Complete close", "run-0001")
  await expect(page.getByText(/Read-only completed run/i).first()).toBeVisible()
})

async function completeCertifiableRunToAwaitingSupervision(page: Page) {
  for (let index = 0; index < 5; index += 1) await clickAction(page, "Advance evidence")
  await clickAction(page, "Complete forecast")
  await clickAction(page, "Complete argument")
  await expect(page.getByRole("button", { name: "Approve proposal", exact: true })).toBeEnabled()
}

async function completeCertifiableRunToFill(page: Page) {
  await completeCertifiableRunToAwaitingSupervision(page)
  await clickConfirm(page, "Approve proposal")
  await clickAction(page, "Simulate submit")
  await clickAction(page, "Mark order working")
  await clickAction(page, "Record synthetic fill")
}

async function clickAction(page: Page, label: string, terminalRunId?: string) {
  await page.getByRole("button", { name: label, exact: true }).click()
  if (terminalRunId) {
    await expect(page).toHaveURL(new RegExp(`\\/console\\/decision-room\\?run=${terminalRunId}$`))
  } else {
    await expect(page.locator(".scenario-feedback").filter({ hasText: `${label} requested` }).first()).toBeVisible()
  }
  await expectNoNetworkCalls(page)
}

async function clickConfirm(page: Page, label: string, terminalRunId?: string, expectedFeedback = `${label} requested`) {
  await page.getByRole("button", { name: label, exact: true }).click()
  await expectNoNetworkCalls(page)
  const dialog = page.getByRole("dialog")
  await expect(dialog).toBeVisible()
  await dialog.getByRole("button", { name: `Confirm ${label}`, exact: true }).click()
  if (terminalRunId) {
    await expect(page).toHaveURL(new RegExp(`\\/console\\/decision-room\\?run=${terminalRunId}$`))
  } else {
    await expect(page.locator(".scenario-feedback").filter({ hasText: expectedFeedback }).first()).toBeVisible()
  }
  await expectNoNetworkCalls(page)
}

async function clearNetworkCalls(page: Page) {
  await page.evaluate(() => {
    const calls = (window as SimulatorWindow).__simulatorNetworkCalls
    if (!calls) throw new Error("network instrumentation was not installed")
    calls.length = 0
  })
}

async function expectNoNetworkCalls(page: Page) {
  await page.waitForTimeout(25)
  await expect.poll(() => page.evaluate(() => (window as SimulatorWindow).__simulatorNetworkCalls ?? [])).toEqual([])
}
