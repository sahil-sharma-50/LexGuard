import { expect, test } from "@playwright/test"

test("case file remains readable without horizontal overflow", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "AI argues. Risk decides.", exact: true })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  expect(overflow).toBe(false)
})

test("console remains free of horizontal overflow at every required viewport", async ({ page }) => {
  await page.goto("/console")
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  expect(overflow).toBe(false)
})

test("command center has a concise heading and aligned masthead action", async ({ page }) => {
  await page.goto("/")
  const enterConsole = await page.getByRole("link", { name: "Open console" }).boundingBox()

  await page.goto("/command")
  const leaveConsole = await page.getByRole("link", { name: /Landing/ }).boundingBox()

  await expect(page.getByText("Court in session · live projection")).toHaveCount(0)
  await expect(page.getByText("Refreshes while visible")).toBeVisible()
  expect(leaveConsole?.width).toBe(enterConsole?.width)
  expect(leaveConsole?.height).toBe(enterConsole?.height)

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  expect(overflow).toBe(false)
})
