import { test, expect } from '@playwright/test'
import path from 'node:path'

test('Stitch download flow, responsive geometry and API-backed controls', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const requests: unknown[] = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/download/inspect') return route.fulfill({ json: {
      title: 'Architectural Acoustics & Spatial Audio Engineering', uploader: 'YouTube', duration: 868,
      thumbnail: '/test-media.jpg',
    } })
    if (url.pathname === '/api/jobs' && route.request().method() === 'POST') {
      requests.push(route.request().postDataJSON())
      return route.fulfill({ json: { id: 3, status: 'queued' } })
    }
    return route.fulfill({ json: url.pathname === '/api/jobs' ? [
      { id: 1, type: 'convert', status: 'running', progress: 72, output_path: '/data/audio_lecture_part_2.m4a', current_step: 'Konvertierung läuft · 72 %' },
      { id: 2, type: 'download', status: 'running', progress: 34, output_path: '/data/nature_documentary_4k.mp4', current_step: 'Wird heruntergeladen · 34 %' },
    ] : {} })
  })
  await page.route('**/test-media.jpg', route => route.fulfill({ path: path.resolve('tests/fixtures/stitch-media.jpg'), contentType: 'image/jpeg' }))
  await page.setViewportSize({ width: 1280, height: 1012 })
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Medien-URL' }).fill('https://youtube.com/watch?v=dQw4w9WgXcQ')
  await page.getByRole('button', { name: 'Link prüfen' }).click()
  await expect(page.locator('.inspect-result')).toContainText('Architectural Acoustics')
  await expect(page.locator('.preview-duration')).toHaveText('14:28')
  await page.evaluate(() => document.fonts.ready)
  const box = await page.locator('.work-panel').boundingBox()
  expect(box?.width).toBe(680)
  expect(box?.x).toBe(300)
  for (const [name, width, height] of [['desktop', 1280, 1012], ['tablet', 768, 1024], ['compact', 600, 900], ['mobile', 390, 844]] as const) {
    await page.setViewportSize({ width, height })
    const queue = await page.locator('.queue-panel').boundingBox()
    const workflow = await page.locator('.work-panel').boundingBox()
    expect(queue?.width).toBe(workflow?.width)
    await page.screenshot({ path: path.resolve('../../tmp/stitch/review', `${name}.png`), fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  await page.getByRole('button', { name: 'Dunkles Design aktivieren' }).click()
  await page.screenshot({ path: path.resolve('../../tmp/stitch/review/mobile-dark.png'), fullPage: true })
  await page.getByRole('button', { name: 'Erweiterte Einstellungen' }).click()
  await expect(page.getByRole('button', { name: 'Erweiterte Einstellungen' })).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('combobox', { name: 'Format', exact: true }).selectOption('audio:m4a')
  await page.getByTestId('create-job').click()
  expect(requests).toMatchObject([{ type: 'download', input: { output_kind: 'audio', output_format: 'm4a', url: 'https://youtube.com/watch?v=dQw4w9WgXcQ' } }])
  await expect(page.locator('.message')).toContainText('Download gestartet')
  expect(errors).toEqual([])
})

test('keeps preview geometry when an inspected thumbnail cannot load', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: new URL(route.request().url()).pathname === '/api/download/inspect'
    ? { title: 'A very long media title '.repeat(12), duration: 868, thumbnail: '/missing-preview.jpg' }
    : new URL(route.request().url()).pathname === '/api/jobs' ? [] : {} }))
  await page.route('**/missing-preview.jpg', route => route.fulfill({ status: 404, body: '' }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Medien-URL' }).fill('https://example.com/video')
  await page.getByRole('button', { name: 'Link prüfen' }).click()
  await expect(page.locator('.preview-media img')).toHaveAttribute('src', '/logo.png')
  await expect(page.locator('.preview-duration')).toHaveText('14:28')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
