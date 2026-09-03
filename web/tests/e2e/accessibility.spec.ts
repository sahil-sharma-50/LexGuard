import { AxeBuilder } from "@axe-core/playwright"
import { expect, test, type Locator, type Page } from "@playwright/test"
import path from "node:path"

const PUBLIC_ROUTES = [
  "/",
  "/command",
  "/console",
  "/console/decision-room?scenario=guided-certifiable-v1",
  "/console/cases",
] as const

test.describe("public accessibility gates", () => {
  test("has no serious or critical axe violations on every public route", async ({ page }) => {
    for (const route of PUBLIC_ROUTES) {
      await page.goto(route, { waitUntil: "domcontentloaded" })
      await expect(page.locator("main").first()).toBeVisible()
      // Let the authored entrance animations settle: axe measures the blended
      // mid-animation opacity as a (transient) contrast failure otherwise.
      await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))))
      const results = await new AxeBuilder({ page }).analyze()
      expect(
        results.violations.filter(({ impact }) => impact === "serious" || impact === "critical"),
        `${route} has serious or critical accessibility violations`,
      ).toEqual([])
    }
  })

  test("uses the Midnight Record palette and readable type on public surfaces", async ({ page }) => {
    for (const route of ["/", "/command", "/cases/current"] as const) {
      await page.goto(route, { waitUntil: "domcontentloaded" })
      const root = await page.locator("html").evaluate((element) => getComputedStyle(element).colorScheme)
      expect(root).toBe("dark")
      const bodySize = await page.locator("body").evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize))
      expect(bodySize).toBeGreaterThanOrEqual(17)
    }

    await page.goto("/cases/current", { waitUntil: "domcontentloaded" })
    const caseHeading = await computedContrast(page, ".case-heading h1")
    expect(contrastRatio(caseHeading.foreground, caseHeading.background)).toBeGreaterThanOrEqual(4.5)

    await page.goto("/", { waitUntil: "domcontentloaded" })
    const sectionLabelSize = await page.locator(".section-label").first().evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize))
    expect(sectionLabelSize).toBeGreaterThanOrEqual(11)

    await page.goto("/command", { waitUntil: "domcontentloaded" })
    const quietCaptionSize = await page.locator(".quiet-caption").first().evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize))
    expect(quietCaptionSize).toBeGreaterThanOrEqual(14)
  })

  test("meets the required computed text, focus, and non-text contrast ratios", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" })

    for (const selector of ["body", ".landing-lede", ".section-label", ".landing-primary-action"]) {
      const pair = await computedContrast(page, selector)
      expect(
        contrastRatio(pair.foreground, pair.background),
        `${selector} normal-text contrast ${pair.foreground} on ${pair.background}`,
      ).toBeGreaterThanOrEqual(4.5)
    }

    const largeText = await computedContrast(page, "h1")
    expect(contrastRatio(largeText.foreground, largeText.background), "h1 large-text contrast").toBeGreaterThanOrEqual(3)

    const primaryAction = page.locator(".landing-primary-action").first()
    // Hydration resets document.activeElement, so wait for it the way the
    // keyboard-navigation test does before walking the tab order.
    await page.waitForLoadState("load")
    await focusWithKeyboard(page, primaryAction)
    const focusPair = await primaryAction.evaluate((element) => {
      const styles = getComputedStyle(element)
      return {
        foreground: styles.outlineColor,
        background: getComputedStyle(document.body).backgroundColor,
        outlineWidth: styles.outlineWidth,
        outlineStyle: styles.outlineStyle,
      }
    })
    expect(focusPair.outlineStyle).not.toBe("none")
    expect(Number.parseFloat(focusPair.outlineWidth)).toBeGreaterThanOrEqual(2)
    expect(contrastRatio(focusPair.foreground, focusPair.background), "focus indicator contrast").toBeGreaterThanOrEqual(3)

    const nonTextPair = await primaryAction.evaluate((element) => {
      const styles = getComputedStyle(element)
      return { foreground: styles.borderTopColor, background: getComputedStyle(document.body).backgroundColor }
    })
    expect(contrastRatio(nonTextPair.foreground, nonTextPair.background), "primary action border contrast").toBeGreaterThanOrEqual(3)
  })

  test("supports keyboard-only navigation through the primary action", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" })
    await expect(page.locator(".skip-link")).toHaveCount(1)
    await page.waitForLoadState("load")
    // Hydration can steal focus for a frame, so re-press Tab until the skip
    // link actually holds focus instead of asserting a single press.
    await expect(async () => {
      await page.keyboard.press("Tab")
      await expect(page.locator(".skip-link")).toBeFocused({ timeout: 1000 })
    }).toPass({ timeout: 10_000 })
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/#hero$/)

    await page.goto("/", { waitUntil: "domcontentloaded" })
    const primaryAction = page.getByRole("link", { name: "Enter the command center" }).first()
    await focusWithKeyboard(page, primaryAction)
    await expect(primaryAction).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/command$/)
  })

  test("keeps confirmation dialog focus contained, background inert, and Escape reversible", async ({ page }) => {
    await page.goto("/console/decision-room?scenario=guided-certifiable-v1", { waitUntil: "domcontentloaded" })
    await expect(page.getByRole("heading", { name: "Decision room" })).toBeVisible()
    for (let index = 0; index < 5; index += 1) {
      await page.getByRole("button", { name: "Advance evidence", exact: true }).click()
      await expect(page.locator(".scenario-feedback")).toContainText("Advance evidence requested")
    }
    await page.getByRole("button", { name: "Complete forecast", exact: true }).click()
    await page.getByRole("button", { name: "Complete argument", exact: true }).click()

    const approve = page.getByRole("button", { name: "Approve proposal", exact: true })
    await expect(approve).toBeEnabled()
    await approve.click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    const cancel = dialog.getByRole("button", { name: "Cancel", exact: true })
    const confirm = dialog.getByRole("button", { name: "Confirm Approve proposal", exact: true })
    await expect(cancel).toBeFocused()
    await expect.poll(() => page.locator("[data-simulator-background]").evaluateAll((elements) => elements.length > 0 && elements.every((element) => (element as HTMLElement).inert))).toBe(true)

    await page.keyboard.press("Tab")
    await expect(confirm).toBeFocused()
    await page.keyboard.press("Tab")
    await expect(cancel).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(dialog).toBeHidden()
    await expect(approve).toBeFocused()
  })

  test("honors reduced-motion preferences", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.goto("/", { waitUntil: "domcontentloaded" })
    await expect.poll(() => page.locator(".hero-rail").evaluate((element) => Number.parseFloat(getComputedStyle(element).animationDuration))).toBeLessThanOrEqual(0.001)
  })

  test("keeps every public route free of horizontal body overflow", async ({ page }) => {
    for (const route of PUBLIC_ROUTES) {
      await page.goto(route, { waitUntil: "domcontentloaded" })
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    }
  })

  test("reflows at a 200 percent zoom-equivalent CSS viewport and completes the primary action", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page)
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 720,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    })
    await page.goto("/", { waitUntil: "domcontentloaded" })
    await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 2 })
    await expect.poll(() => page.evaluate(() => visualViewport?.scale ?? 0)).toBe(2)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    const primaryAction = page.getByRole("link", { name: "Enter the command center" }).first()
    await primaryAction.focus()
    await expect(primaryAction).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/command$/)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  })

  test("wraps long case identifiers without horizontal overflow", async ({ page }) => {
    const longId = `case-${"x".repeat(240)}`
    await page.goto(`/cases/${longId}`, { waitUntil: "domcontentloaded" })
    await expect(page.getByRole("heading", { name: /Case (not found|unavailable)/ })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    const id = page.locator(".case-id")
    await expect(id).toBeVisible()
    expect(await id.evaluate((element) => getComputedStyle(element).overflowWrap)).toMatch(/anywhere|break-word/)
  })
})

test.describe("font and hydration gates", () => {
  test("requests fonts only from the local application origin", async ({ page, baseURL }) => {
    const fontRequests: string[] = []
    page.on("request", (request) => {
      if (/\.(?:woff2?|ttf|otf)(?:\?|$)/i.test(request.url())) fontRequests.push(request.url())
    })
    await page.goto("/", { waitUntil: "domcontentloaded" })
    await page.evaluate(() => document.fonts.ready)
    expect(fontRequests.length).toBeGreaterThan(0)
    expect(fontRequests.filter((url) => /fonts\.(?:googleapis|gstatic)\.com/i.test(url))).toEqual([])
    expect(fontRequests.every((url) => new URL(url).origin === new URL(baseURL ?? "http://127.0.0.1:3000").origin)).toBe(true)
  })

  test("still renders when every local font request is forced to fail", async ({ page }, testInfo) => {
    const abortedFonts: string[] = []
    await page.route(/\.(?:woff2?|ttf|otf)(?:\?|$)/i, (route) => {
      abortedFonts.push(route.request().url())
      return route.abort()
    })
    const pageErrors: string[] = []
    page.on("pageerror", (error) => pageErrors.push(error.message))
    await page.goto("/", { waitUntil: "domcontentloaded" })
    await expect(page.getByRole("heading", { name: "AI argues. Risk decides.", exact: true })).toBeVisible()
    await expect(page.getByRole("link", { name: "Enter the command center" }).first()).toBeVisible()
    await expect(page.getByRole("link", { name: "Follow the live case", exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    expect(abortedFonts.length).toBeGreaterThan(0)
    await page.getByRole("link", { name: "Enter the command center" }).first().click()
    await expect(page.getByRole("heading", { name: "Command center", exact: true })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Operator bench", exact: true })).toBeVisible()
    await expect(page.getByRole("heading", { name: "Decision feed", exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    expect(abortedFonts.length).toBeGreaterThan(0)
    if (testInfo.project.name === "desktop") {
      await page.screenshot({ path: path.resolve(process.cwd(), "test-results", "forced-font-fallback.png") })
    }
    expect(pageErrors).toEqual([])
  })

  test("does not emit hydration mismatch errors on public routes", async ({ page }) => {
    const hydrationErrors: string[] = []
    page.on("console", (message) => {
      if (/hydration|did not match/i.test(message.text())) hydrationErrors.push(message.text())
    })
    const readiness = [
      ".session-docket",
      "#operator-bench-title",
      "#operations-overview-title",
      "#decision-room-title",
      "#console-cases-title",
    ] as const
    for (const [index, route] of PUBLIC_ROUTES.entries()) {
      await page.goto(route, { waitUntil: "domcontentloaded" })
      await expect(page.locator(readiness[index]).first()).toBeVisible()
      await page.waitForLoadState("networkidle")
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    }
    await expect.poll(() => hydrationErrors).toEqual([])
  })
})

async function focusWithKeyboard(page: Page, locator: Locator) {
  // Hydration can reset document.activeElement mid-walk, which strands the tab
  // sequence at <body>. Restart the walk from a known state before giving up.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.())
    for (let index = 0; index < 40; index += 1) {
      if (await locator.evaluate((element) => document.activeElement === element)) return
      await page.keyboard.press("Tab")
    }
  }
  throw new Error("Could not reach the requested control with keyboard navigation")
}

async function computedContrast(page: Page, selector: string): Promise<{ foreground: string; background: string }> {
  return page.locator(selector).first().evaluate((element) => {
    const styles = getComputedStyle(element)
    let background = styles.backgroundColor
    let parent = element.parentElement
    while ((background === "transparent" || background === "rgba(0, 0, 0, 0)") && parent) {
      background = getComputedStyle(parent).backgroundColor
      parent = parent.parentElement
    }
    if (background === "transparent" || background === "rgba(0, 0, 0, 0)") background = getComputedStyle(document.body).backgroundColor
    return { foreground: styles.color, background }
  })
}

function contrastRatio(foreground: string, background: string): number {
  const first = relativeLuminance(parseColor(foreground))
  const second = relativeLuminance(parseColor(background))
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
}

function parseColor(color: string): [number, number, number] {
  const channels = color.match(/rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)/i)
  if (!channels) throw new Error(`Unsupported computed color: ${color}`)
  return [Number(channels[1]), Number(channels[2]), Number(channels[3])]
}

function relativeLuminance([red, green, blue]: [number, number, number]): number {
  const channel = (value: number) => {
    const normalized = value / 255
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
}
