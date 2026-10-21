import { test, expect } from '@playwright/test'

// Regression: QA-001 — confirmation must close before a slow request completes.
for (const kind of ['download', 'convert'] as const) {
  test(`${kind}: dismisses quality warning while confirmed request is pending`, async ({ page }) => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    let forcedRequests = 0
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url())
      if (route.request().method() !== 'POST') {
        await route.fulfill({ json: url.pathname === '/api/jobs' ? [] : {} })
        return
      }
      if (url.searchParams.get('force') !== 'true') {
        await route.fulfill({ status: 409, json: { detail: { warning: 'Qualitätsverlust möglich' } } })
        return
      }
      forcedRequests++
      await pending
      await route.fulfill({ status: 500, json: { detail: 'Testserver nicht verfügbar' } })
    })
    await page.goto('/')
    if (kind === 'download') {
      await page.getByRole('textbox', { name: 'Medien-URL' }).fill('https://example.invalid/video')
      await page.locator('[data-testid="create-job"]').click()
    } else {
      await page.getByRole('tab', { name: 'Konvertieren' }).click()
      await page.locator('#file-upload').setInputFiles({ name: 'test.wav', mimeType: 'audio/wav', buffer: Buffer.from('fixture') })
      await page.getByRole('button', { name: /Konvertierung.*starten/ }).click()
    }
    const dialog = page.getByRole('dialog', { name: 'Qualitätswarnung' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Trotzdem starten' }).click()
    try {
      await expect(dialog).not.toBeVisible({ timeout: 1500 })
      await expect(page.getByTestId('create-job')).toBeDisabled()
      expect(forcedRequests).toBe(1)
    } finally { release() }
    await expect(page.getByText(kind === 'download' ? 'Download konnte nicht gestartet werden.' : 'Testserver nicht verfügbar', { exact: true })).toBeVisible()
    await expect(dialog).not.toBeVisible()
    await expect(page.getByTestId('create-job')).toBeEnabled()
  })
}

test('finished files header has padding and does not clip the glow on mobile', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: route.request().url().endsWith('/api/jobs') ? [] : {} }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const toggle = page.getByTestId('history-toggle')
  await expect(toggle).toBeVisible()
  const layout = await toggle.evaluate(el => ({
    padding: parseFloat(getComputedStyle(el).paddingLeft),
    overflow: getComputedStyle(el.closest('.downloads-panel')!).overflow,
  }))
  expect(layout.padding).toBeGreaterThanOrEqual(12)
  expect(layout.overflow).toBe('visible')
  await toggle.hover()
  await toggle.click()
  await expect(page.getByText('Keine fertigen Dateien', { exact: true })).toBeVisible()
  await toggle.click()
  await expect(page.getByText('Keine fertigen Dateien', { exact: true })).not.toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../../.gstack/qa-reports/run-20261021/local-history-after.png', fullPage: true })
  await page.getByRole('button', { name: 'Dunkles Design aktivieren' }).click()
  await toggle.hover()
  await page.screenshot({ path: '../../.gstack/qa-reports/run-20261021/local-history-dark-after.png', fullPage: true })
})
