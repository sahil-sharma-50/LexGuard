import { expect, test, type Request, type Response } from "@playwright/test"

const PUBLIC_ROUTES = [
  "/",
  "/console",
  "/console/decision-room?scenario=guided-certifiable-v1",
  "/console/cases",
] as const

const SENTINELS = [
  "SENTINEL_API_KEY_DO_NOT_RENDER",
  "SENTINEL_PRIVATE_ACCOUNT_DO_NOT_RENDER",
  "SENTINEL_BROKER_ID_DO_NOT_RENDER",
  "SENTINEL_PRIVATE_EXPORT_DO_NOT_RENDER",
] as const

test("never renders private sentinels in server HTML, DOM text, or response bodies", async ({ page, request, context, baseURL }) => {
  await context.addCookies(SENTINELS.map((sentinel, index) => ({
    name: `privacy_canary_${index}`,
    value: sentinel,
    url: baseURL ?? "http://127.0.0.1:3000",
  })))
  await page.setExtraHTTPHeaders({ "x-privacy-canary": SENTINELS.join(",") })
  await page.addInitScript((sentinels) => {
    for (const [index, sentinel] of sentinels.entries()) window.localStorage.setItem(`privacy-canary-${index}`, sentinel)
  }, SENTINELS)

  for (const route of PUBLIC_ROUTES) {
    const serverResponse = await request.get(route)
    expect(serverResponse.ok(), `${route} server response`).toBe(true)
    const serverHtml = await serverResponse.text()
    expectAbsent(serverHtml, `${route} server HTML`)

    const responseBodies: Promise<CapturedResponse>[] = []
    const responseBodyErrors: string[] = []
    const canaryRequests: string[] = []
    const onResponse = (response: Response) => {
      const captured = captureResponse(response, responseBodyErrors)
      if (captured) responseBodies.push(captured)
    }
    const onRequest = (browserRequest: Request) => {
      if (browserRequest.headers()["x-privacy-canary"]?.includes(SENTINELS[0])) canaryRequests.push(browserRequest.url())
    }
    page.on("response", onResponse)
    page.on("request", onRequest)
    await page.goto(route, { waitUntil: "domcontentloaded" })
    await expect(page.locator("main").first()).toBeVisible()
    await page.waitForLoadState("networkidle")
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    expect(canaryRequests.length, `${route} requests carried the privacy canary header`).toBeGreaterThan(0)
    expect(await page.evaluate((sentinels) => sentinels.map((_, index) => window.localStorage.getItem(`privacy-canary-${index}`)), SENTINELS)).toEqual([...SENTINELS])
    expectAbsent(await page.locator("body").innerText(), `${route} DOM text`)
    const responses = await Promise.all(responseBodies)
    expect(responses.length, `${route} captured response count`).toBeGreaterThan(0)
    expect(responses.map(({ url }) => url), `${route} inspected response URLs`).not.toEqual([])
    expect(responses.filter(({ resourceType, url }) => resourceType === "document" || url.includes("_rsc=")).length, `${route} document/RSC response count`).toBeGreaterThan(0)
    expect(responseBodyErrors, `${route} response body errors`).toEqual([])
    expect(responses.filter(({ readable }) => readable).length, `${route} response bodies read successfully`).toBeGreaterThan(0)
    expectAbsent(responses.map(({ body }) => body).join("\n"), `${route} response bodies`)
    page.off("response", onResponse)
    page.off("request", onRequest)
  }
})

test("fails closed when the response collector receives a sentinel canary", async ({ page }) => {
  await page.route("**/privacy-sentinel-canary", (route) => route.fulfill({
    status: 200,
    contentType: "text/plain",
    body: SENTINELS[0],
  }))
  const responseBodies: Promise<CapturedResponse>[] = []
  const responseBodyErrors: string[] = []
  const onResponse = (response: Response) => {
    const captured = captureResponse(response, responseBodyErrors)
    if (captured) responseBodies.push(captured)
  }
  page.on("response", onResponse)
  await page.goto("/", { waitUntil: "domcontentloaded" })
  await page.evaluate(() => fetch("/privacy-sentinel-canary").then((response) => response.text()))
  await page.waitForLoadState("networkidle")
  const responses = await Promise.all(responseBodies)
  expect(responses.length).toBeGreaterThan(0)
  expect(responseBodyErrors).toEqual([])
  expect(responses.some(({ url }) => url.endsWith("/privacy-sentinel-canary"))).toBe(true)
  expect(() => expectAbsent(responses.map(({ body }) => body).join("\n"), "sentinel canary response body")).toThrow(SENTINELS[0])
  page.off("response", onResponse)
})

type CapturedResponse = { url: string; body: string; readable: boolean; resourceType: string }

function captureResponse(response: Response, responseBodyErrors: string[]): Promise<CapturedResponse> | null {
  const resourceType = response.request().resourceType()
  const isDocumentOrRsc = resourceType === "document" || resourceType === "fetch" || resourceType === "xhr" || response.url().includes("_rsc=")
  if (!isDocumentOrRsc) return null
  if (response.status() >= 300 && response.status() < 400) return Promise.resolve({ url: response.url(), body: "", readable: false, resourceType })
  return response.body().then((body) => ({ url: response.url(), body: body.toString("utf8"), readable: true, resourceType })).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : String(error)
    const message = `Could not inspect response body for ${response.url()}: ${detail}`
    responseBodyErrors.push(message)
    throw new Error(message)
  })
}

function expectAbsent(value: string, surface: string) {
  for (const sentinel of SENTINELS) expect(value, `${sentinel} leaked into ${surface}`).not.toContain(sentinel)
}
