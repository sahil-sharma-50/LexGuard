import { expect, test } from "@playwright/test"

test.describe("case queue responsive semantics", () => {
  test("uses one accessible table at 768px and one accessible list below it", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto("/console/cases", { waitUntil: "domcontentloaded" })

    const table = page.getByRole("table", { name: "Case queue" })
    const list = page.locator(".case-queue-list")
    await expect(table).toBeVisible()
    await expect(list).toBeHidden()
    await expect(page.getByRole("table")).toHaveCount(1)
    await expect(table.getByRole("columnheader", { name: "Lifecycle state" })).toBeVisible()
    await expect(table.getByRole("columnheader", { name: "Last action" })).toBeVisible()
    await expect(table.getByRole("row", { name: /Guided certifiable observing No action recorded/i })).toBeVisible()
    await expect(table.getByRole("row", { name: /Current run run-0001 observing No action recorded/i })).toBeVisible()

    await page.setViewportSize({ width: 767, height: 1024 })
    await expect(table).toBeHidden()
    await expect(list).toBeVisible()
    await expect(page.getByRole("table")).toHaveCount(0)
    await expect(page.getByRole("list").filter({ has: page.getByRole("link", { name: /Guided certifiable/i }) })).toHaveCount(1)
    await expect(list.getByText("Lifecycle state", { exact: true }).first()).toBeVisible()
    await expect(list.getByText("Last action", { exact: true }).first()).toBeVisible()
    await expect(list.getByText("observing", { exact: true }).first()).toBeVisible()
    await expect(list.getByText("No action recorded", { exact: true }).first()).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  })
})
