import { test, expect } from '@playwright/test'

test('diagnoses failed uploads without a job, survives reload and stays in this browser', async ({ page, browser }) => {
  const mock = async (target: typeof page) => target.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({
      status: path === '/api/jobs/convert-batch' ? 400 : 200,
      contentType: 'application/json',
      headers: path === '/api/jobs/convert-batch'
        ? { 'X-MediaForge-Diagnostic': Buffer.from(JSON.stringify('OSError: temporary storage full')).toString('base64') } : {},
      body: JSON.stringify(path === '/api/jobs' ? [] : path === '/api/jobs/convert-batch'
        ? { detail: 'There was an error parsing the body' } : { warning: null }),
    })
  })
  await mock(page)
  await page.goto('/')
  await page.locator('input[type=file]').setInputFiles({ name: 'video.mp4', mimeType: 'video/mp4', buffer: Buffer.from('sample') })
  await page.getByRole('button', { name: '1 Konvertierung starten' }).click()
  await expect(page.locator('.message')).toContainText('There was an error parsing the body')
  await page.getByText('Diagnose dieser Sitzung', { exact: true }).click()
  const log = page.locator('.session-diagnostics pre')
  await expect(log).toContainText('HTTP 400')
  await expect(log).toContainText('temporary storage full')
  await expect(log).toContainText('There was an error parsing the body')
  await page.reload()
  await page.getByText('Diagnose dieser Sitzung', { exact: true }).click()
  await expect(log).toContainText('temporary storage full')
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Protokoll herunterladen' }).click()
  expect((await downloaded).suggestedFilename()).toMatch(/^mediaforge-diagnose-.*\.txt$/)
  const other = await browser.newContext()
  try {
    const otherPage = await other.newPage()
    await mock(otherPage)
    await otherPage.goto('http://localhost:5173/')
    await otherPage.getByText('Diagnose dieser Sitzung', { exact: true }).click()
    await expect(otherPage.locator('.session-diagnostics pre')).not.toContainText('temporary storage full')
  } finally { await other.close() }
})
