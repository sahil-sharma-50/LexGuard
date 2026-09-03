import { expect, test } from "@playwright/test"

const pages = [
  { path: "/command", title: "Command center" },
  { path: "/cases/current", title: /SPY \/ 10:05/ },
  { path: "/cases", title: "Case archive" },
  { path: "/research", title: "Research gate" },
] as const

test("console navigation omits the removed Health route", async ({ page }) => {
  await page.goto("/command")
  const navigation = page.getByRole("navigation", { name: "Console routes" })

  await expect(navigation.getByRole("link")).toHaveCount(4)
  await expect(navigation.getByRole("link", { name: "Health" })).toHaveCount(0)
})

test("visible console tabs use one compact page-header system", async ({ page }) => {
  for (const item of pages) {
    await page.goto(item.path)
    const header = page.locator(".console-page-heading")
    await expect(header).toBeVisible()
    await expect(header.getByRole("heading", { name: item.title })).toBeVisible()
  }

  await page.goto("/cases")
  await expect(page.getByText("Public record", { exact: true })).toHaveCount(0)
  const header = page.locator(".console-page-heading")
  const notice = page.getByRole("status").filter({ hasText: /Archive index unavailable|public read API/i })
  await expect(header).toBeVisible()
  await expect(notice).toBeVisible()
  const [noticeBox, headerBox] = await Promise.all([notice.boundingBox(), header.boundingBox()])
  expect(noticeBox).not.toBeNull()
  expect(headerBox).not.toBeNull()
  expect(noticeBox!.y).toBeGreaterThan(headerBox!.y + headerBox!.height)
})

test("subpage headers begin at the same height as Command Center", async ({ page }) => {
  await page.goto("/command")
  const commandHeader = await page.locator(".console-page-heading").boundingBox()
  expect(commandHeader).not.toBeNull()

  for (const path of ["/cases", "/research"]) {
    await page.goto(path)
    const locator = page.locator(".console-page-heading")
    await expect(locator).toBeVisible()
    const header = await locator.boundingBox()
    expect(header).not.toBeNull()
    expect(header!.y).toBe(commandHeader!.y)
  }
})

test("console copy uses native, unsynthesized font rendering", async ({ page }) => {
  await page.goto("/command")

  const typography = await page.locator("body").evaluate((element) => {
    const styles = window.getComputedStyle(element)
    return {
      fontSynthesis: styles.fontSynthesis,
      fontWeight: styles.fontWeight,
    }
  })

  expect(typography).toEqual({ fontSynthesis: "none", fontWeight: "450" })
})

test("command data labels meet the readable 12px floor", async ({ page }) => {
  await page.goto("/command")
  const label = page.getByText("Equity", { exact: true })
  await expect(label).toBeVisible()

  const fontSize = await label.evaluate((element) => Number.parseFloat(window.getComputedStyle(element).fontSize))
  expect(fontSize).toBeGreaterThanOrEqual(12)
})

test("command data groups share a common left edge", async ({ page }) => {
  await page.goto("/command")
  const tiles = page.locator(".stat-tiles")
  const columns = page.locator(".command-columns")
  await expect(tiles).toBeVisible()
  await expect(columns).toBeVisible()

  const [tilesBox, columnsBox] = await Promise.all([tiles.boundingBox(), columns.boundingBox()])
  expect(tilesBox).not.toBeNull()
  expect(columnsBox).not.toBeNull()
  expect(Math.abs(tilesBox!.x - columnsBox!.x)).toBeLessThanOrEqual(1)
})

test("narrow mobile masthead keeps the brand and landing action separate", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/command")
  const brand = page.locator(".masthead-brand")
  const exit = page.locator(".masthead-exit")
  await expect(brand).toBeVisible()
  await expect(exit).toBeVisible()

  const [brandBox, exitBox] = await Promise.all([brand.boundingBox(), exit.boundingBox()])
  expect(brandBox).not.toBeNull()
  expect(exitBox).not.toBeNull()
  expect(exitBox!.y).toBeGreaterThanOrEqual(brandBox!.y + brandBox!.height + 8)
})
