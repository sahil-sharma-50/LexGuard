import { expect, test } from "@playwright/test"

test.describe("legacy read-only routes", () => {
  test("keeps the documented archive, current case, and research routes available", async ({ page }) => {
    const routes = [
      { path: "/cases/current", heading: /SPY \/ 10:05/ },
      { path: "/cases/archived", heading: /SPY \/ 10:05/ },
      { path: "/research", heading: "Research gate" },
    ] as const

    for (const route of routes) {
      await page.goto(route.path, { waitUntil: "domcontentloaded" })
      await expect(page.getByRole("heading", { name: route.heading })).toBeVisible()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    }
  })

  test("keeps archive replay read-only and pauses live updates", async ({ page }) => {
    await page.goto("/cases/archived", { waitUntil: "domcontentloaded" })
    await expect(page.getByRole("heading", { name: /SPY \/ 10:05/ })).toBeVisible()
    await expect(page.getByRole("button")).toHaveCount(0)
  })
})
