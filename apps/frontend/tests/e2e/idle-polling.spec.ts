import { test, expect } from '@playwright/test'

test('idle polling slows down, pauses when hidden, and refreshes on return', async ({ page }) => {
  let requests = 0
  await page.route('**/api/**', route => {
    const jobs = new URL(route.request().url()).pathname === '/api/jobs'
    if (jobs) requests++
    return route.fulfill({ json: jobs ? [] : {} })
  })
  await page.clock.install()
  await page.goto('/')
  await expect.poll(() => requests).toBeGreaterThan(0)
  await page.waitForLoadState('networkidle')
  const initial = requests
  await page.clock.runFor(20000)
  expect(requests).toBe(initial)
  await page.clock.runFor(10000)
  await expect.poll(() => requests).toBe(initial + 1)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await page.clock.runFor(60000)
  expect(requests).toBe(initial + 1)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect.poll(() => requests).toBe(initial + 2)
})

test('queued work retains five second polling', async ({ page }) => {
  let requests = 0
  await page.route('**/api/**', route => {
    const jobs = new URL(route.request().url()).pathname === '/api/jobs'
    if (jobs) requests++
    return route.fulfill({ json: jobs ? [{ id: 1, type: 'convert', status: 'queued', input: {} }] : {} })
  })
  await page.clock.install()
  await page.goto('/')
  await expect.poll(() => requests).toBeGreaterThan(0)
  await page.waitForLoadState('networkidle')
  const initial = requests
  await page.clock.runFor(5000)
  await expect.poll(() => requests).toBe(initial + 1)
})
