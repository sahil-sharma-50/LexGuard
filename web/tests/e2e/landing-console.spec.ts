import { expect, test } from "@playwright/test"

const INITIAL_VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 375, height: 812 },
] as const

test.describe("landing first viewport", () => {
  for (const viewport of INITIAL_VIEWPORTS) {
    test(`${viewport.width}x${viewport.height} exposes the thesis, disclosure, and command-center action`, async ({ browser }) => {
      const context = await browser.newContext({ viewport })
      const page = await context.newPage()
      await page.goto("/")

      const requiredElements = [
        page.getByRole("heading", { name: "AI argues. Risk decides.", exact: true }),
        page.getByRole("link", { name: "Enter the command center" }).first(),
      ]
      // The centered hero keeps the thesis, CTA, and disclosure in the first
      // viewport; the session docket and standing orders live in the authored
      // sections further down and must still be present on the page.
      await expect(page.getByRole("complementary", { name: "Session docket" })).toHaveCount(1)
      await expect(page.getByRole("heading", { name: "Standing orders", exact: true })).toHaveCount(1)
      await expect(page.locator(".session-time", { hasText: "10:05" })).toHaveCount(1)
      await expect(page.locator(".session-time", { hasText: "14:20" })).toHaveCount(1)
      for (const element of requiredElements) {
        await expect(element).toBeVisible()
        const intersects = await element.evaluate((node) => {
          const rect = node.getBoundingClientRect()
          return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth
        })
        expect(intersects, `${await element.evaluate((node) => node.textContent?.trim())} should intersect the initial viewport`).toBe(true)
      }

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
      expect(overflow).toBe(false)
      await context.close()
    })
  }
})

test("landing exposes the console entry point and the authored court sections", async ({ page }) => {
  await page.goto("/")
  const sectionNav = page.getByRole("navigation", { name: "Page sections" })
  await expect(sectionNav.getByRole("link", { name: "Procedure", exact: true })).toHaveAttribute("href", "#procedure")
  await expect(page.getByRole("link", { name: "Open console", exact: true })).toHaveAttribute("href", "/command")

  // The routes themselves live on the console tab bar, always visible there.
  await page.goto("/console")
  const consoleNav = page.getByRole("navigation", { name: "Console routes" })
  await expect(consoleNav.getByRole("link", { name: "Command center", exact: true })).toHaveAttribute("href", "/command")
  await expect(consoleNav.getByRole("link", { name: "Live case", exact: true })).toHaveAttribute("href", "/cases/current")
  await expect(consoleNav.getByRole("link", { name: "Case archive", exact: true })).toHaveAttribute("href", "/cases")
  await expect(consoleNav.getByRole("link", { name: "Training room" })).toHaveCount(0)

  await page.goto("/")
  for (const section of ["Due process of a trade", "Separation of powers", "How the court is wired"]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible()
  }
})

test("javascript-disabled landing retains the court sections and training-room interaction requirement", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  for (const section of ["Due process of a trade", "Separation of powers", "How the court is wired"]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible()
  }
  await expect(page.getByRole("navigation", { name: "Console routes" }).getByRole("link", { name: "Command center", exact: true })).toHaveAttribute("href", "/command")

  await page.goto("/console")
  await expect(page.locator(".fixture-notice")).toContainText(/Interaction requires JavaScript/i)
  await context.close()
})

test("command center shows the three zones and explicit unavailable states without a backend", async ({ page }) => {
  await page.goto("/command", { waitUntil: "domcontentloaded" })
  await expect(page.getByRole("heading", { name: "Command center", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "The ledger", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Decision feed", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Operator bench", exact: true })).toBeVisible()

  // Stop-only controls are visible but disabled until a token is entered.
  for (const name of ["Pause entries", "Resume entries", "Emergency stop"]) {
    await expect(page.getByRole("button", { name: new RegExp(name) })).toBeDisabled()
  }
  await expect(page.getByText(/Enter the operator token to arm the bench/)).toBeVisible()

  // Without a reachable API the money zone withholds values instead of faking them.
  await expect(page.getByText(/Account read unavailable/)).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  expect(overflow).toBe(false)
})

test("unavailable account data uses the warning-yellow status treatment", async ({ page }) => {
  await page.goto("/command")
  const title = page.getByText("Account read unavailable", { exact: true })
  await expect(title).toBeVisible()
  await expect(title).toHaveCSS("color", "rgb(212, 175, 103)")
})

test("landing omits the redundant hero schedule descriptor", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByText("Four windows a day · every ruling on the record", { exact: true })).toHaveCount(0)
})
