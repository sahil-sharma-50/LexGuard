import { expect, test } from "@playwright/test"

test("judge can trace evidence to the archived paper case", async ({ page }) => {
  await page.goto("/cases/current")
  await page.getByRole("link", { name: "Archive" }).click()
  await expect(page.getByRole("heading", { name: /abstain from the trade/i })).toBeVisible()
  await expect(page.getByText(/alpaca order lifecycle/i)).toBeVisible()
  await expect(page.getByText(/simulated paper outcomes/i)).toBeVisible()
})

test("unknown archive ids are explained instead of replaying another case", async ({ page }) => {
  await page.goto("/cases/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
  await expect(page.getByRole("heading", { name: /case unavailable|case not found/i })).toBeVisible()
  await expect(page.locator(".case-access-id")).toContainText("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
})

test("archive index exposes recorded case links", async ({ page }) => {
  await page.goto("/cases")
  await expect(page.getByRole("heading", { name: /case archive/i })).toBeVisible()
  await expect(page.getByRole("link", { name: /archived fixture/i })).toBeVisible()
})
