import { test, expect } from '@playwright/test'
import path from 'node:path'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: new URL(route.request().url()).pathname === '/api/jobs' ? [] : {} }))
})

test('compresses a mixed batch with independent settings and prevents duplicate submissions', async ({ page }) => {
  let requests = 0
  await page.route('**/api/jobs/convert-batch', async route => {
    requests++
    const payload = route.request().postDataBuffer()!.toString()
    expect(payload).toContain('compress')
    expect(payload).toContain('"output_format":"mp4"')
    expect(payload).toContain('"output_format":"xz"')
    expect(payload).toContain('"crf":"28"')
    await route.fulfill({ json: { jobs: [{ id: 1 }, { id: 2 }] } })
  })
  await page.goto('/')
  await page.getByRole('tab', { name: 'Komprimieren' }).click()
  await expect(page.getByRole('button', { name: 'Dateien komprimieren' })).toBeDisabled()
  await page.locator('#compress-upload').setInputFiles([
    { name: 'Film.mp4', mimeType: 'video/mp4', buffer: Buffer.from('test movie') },
    { name: 'Daten.json', mimeType: 'application/json', buffer: Buffer.from('{}') },
  ])
  const rows = page.locator('.compression-entry')
  await rows.first().getByText('Feineinstellungen').click()
  await rows.first().getByLabel('CRF').fill('28')
  await rows.nth(1).getByLabel('Zielformat').selectOption('xz')
  await page.getByRole('tab', { name: 'Herunterladen' }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Konvertieren' })).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Komprimieren' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('button', { name: '2 Dateien komprimieren' }).click()
  await expect(page.getByRole('status')).toContainText('2 Komprimierungsaufträge gestartet')
  expect(requests).toBe(1)
  await expect(rows).toHaveCount(0)
})

test('keeps files after an error and allows retry, remove and tab changes', async ({ page }) => {
  await page.route('**/api/jobs/convert-batch', route => route.fulfill({ status: 503, json: { detail: 'Scanner nicht verfügbar' } }))
  await page.goto('/')
  await page.getByRole('tab', { name: 'Komprimieren' }).click()
  await page.locator('#compress-upload').setInputFiles({ name: 'Animation.gif', mimeType: 'image/gif', buffer: Buffer.from('gif') })
  await expect(page.getByLabel('Zielformat')).toHaveValue('zip')
  await page.getByRole('button', { name: '1 Dateien komprimieren' }).click()
  await expect(page.getByRole('status')).toContainText('Scanner nicht verfügbar')
  await expect(page.locator('.compression-entry')).toHaveCount(1)
  await page.getByRole('tab', { name: 'Herunterladen' }).click()
  await page.getByRole('tab', { name: 'Komprimieren' }).click()
  await expect(page.locator('.compression-entry')).toHaveCount(1)
  await page.getByRole('button', { name: 'Animation.gif entfernen' }).click()
  await expect(page.locator('.compression-entry')).toHaveCount(0)
})

test('downloads the completed compression batch as ZIP', async ({ page }) => {
  let submitted = false
  await page.route('**/api/jobs', route => route.fulfill({ json: submitted ? [{ id: 42, type: 'compress', status: 'success', output_path: '/data/result.gz' }] : [] }))
  await page.route('**/api/jobs/convert-batch', route => {
    submitted = true
    return route.fulfill({ json: { batch_id: 'compression-batch', jobs: [{ id: 42 }] } })
  })
  await page.route('**/api/batches/compression-batch/download', route => route.fulfill({ contentType: 'application/zip', body: Buffer.from('zip') }))
  await page.goto('/')
  await page.getByRole('tab', { name: 'Komprimieren' }).click()
  await page.locator('#compress-upload').setInputFiles({ name: 'data.json', mimeType: 'application/json', buffer: Buffer.from('{}') })
  await page.getByRole('button', { name: '1 Dateien komprimieren' }).click()
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Batch als ZIP laden (1)' }).click()
  expect((await downloading).suggestedFilename()).toBe('mediaforge-komprimiert.zip')
})

test('review screenshots: desktop, light, download, compression and mobile without overflow', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  // Freeze motion for reproducible screenshots; motion itself is covered separately.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const shot = async (name: string) => {
    await page.screenshot({ path: path.resolve('../../tmp/design-review', name + '.png'), fullPage: true, animations: 'disabled' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await shot('v3-01-convert-light')
  await page.getByRole('tab', { name: 'Herunterladen' }).click()
  await shot('v3-02-download-light')
  await page.getByRole('tab', { name: 'Komprimieren' }).click()
  await shot('v3-03-compress-empty')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.resolve('../../tmp/design-review/v3-09-mobile-overview.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.locator('#compress-upload').setInputFiles([
    { name: 'Sommerfilm.mp4', mimeType: 'video/mp4', buffer: Buffer.alloc(1024 * 1024) },
    { name: 'Portfolio.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(1024) },
    { name: 'Projektdaten.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.alloc(2048) },
  ])
  await page.locator('.compression-entry').first().getByText('Feineinstellungen').click()
  await shot('v3-04-compress-settings')
  await page.locator('.theme-toggle').click()
  await shot('v3-05-compress-dark')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot('v3-06-mobile-dark')
  await page.locator('.theme-toggle').click()
  await shot('v3-07-mobile-light')
  await page.setViewportSize({ width: 320, height: 740 })
  await shot('v3-08-small-mobile')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('.work-panel')).toHaveCSS('animation-name', 'none')
  expect(errors).toEqual([])
})
