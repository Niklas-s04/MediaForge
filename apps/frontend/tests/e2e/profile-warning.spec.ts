import { test, expect } from '@playwright/test';

test('confirms small quality warning through force job creation', async ({ page }) => {
  const jobRequests: { force: string | null; body: any }[] = [];

  await page.route('**/api/compression/profile*', (route) => {
    const requestUrl = new URL(route.request().url());
    const profile = requestUrl.searchParams.get('profile');
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile,
        family: requestUrl.searchParams.get('family'),
        warning: profile === 'small' ? 'Aggressive profile: noticeable quality loss possible.' : null,
      }),
    });
  });

  await page.route('**/api/download/inspect', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        title: 'Sample Video',
        uploader: 'Example',
        duration: 125,
        formats: [{ height: 1080, ext: 'mp4', fps: 30 }],
      }),
    });
  });

  await page.route('**/api/jobs/*/events', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'id: 0\ndata: {"status":"success","chunk":""}\n\n',
    });
  });

  await page.route('**/api/jobs*', async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (request.method() !== 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    const body = request.postDataJSON();
    const force = requestUrl.searchParams.get('force');
    jobRequests.push({ force, body });

    if (force !== 'true') {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            warning: 'Aggressive profile: noticeable quality loss possible.',
            message: 'Use ?force=true to override',
          },
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 123, type: 'download', status: 'queued', progress: 0 }),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.waitForSelector('text=MediaForge', { timeout: 60000 });


  await page.fill('input[placeholder="https://..."]', 'https://example.invalid/sample');
  await page.click('[data-testid="quality-small"]');

  await expect(page.locator('.warning-inline')).toContainText('Aggressive');

  await page.click('[data-testid="create-job"]');
  await expect(page.locator('.modal')).toBeVisible();

  await page.click('.modal button.confirm');
  await expect(page.locator('text=Download gestartet: Auftrag #123')).toBeVisible();

  expect(jobRequests).toHaveLength(2);
  expect(jobRequests[0].force).toBeNull();
  expect(jobRequests[0].body.input.output_kind).toBe('video');
  expect(jobRequests[0].body.input.output_format).toBe('mp4');
  expect(jobRequests[0].body.input.quality_preset).toBe('small');
  expect(jobRequests[0].body.input.compression_profile).toBe('small');
  expect(jobRequests[1].force).toBe('true');
});

test('clears selected local file after successful upload conversion', async ({ page }) => {
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ warning: null }),
    });
  });

  await page.route('**/api/jobs/convert-upload*', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 456, type: 'convert', status: 'queued', progress: 0 }),
    });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.waitForSelector('text=MediaForge', { timeout: 60000 });

  await page.click('button:has-text("Konvertieren")');

  await page.setInputFiles('#file-upload', {
    name: 'sample.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('fake-audio'),
  });
  await expect(page.locator('.convert-card').getByText('sample.wav')).toBeVisible();
  await expect(page.getByRole('button', { name: /MP3 Audio/ })).toBeVisible();

  await page.click('button:has-text("Konvertierung starten")');

  await expect(page.locator('text=Konvertierung gestartet: Auftrag #456')).toBeVisible();
  await expect(page.locator('text=sample.wav')).toHaveCount(0);
  await expect(page.locator('text=Datei auswählen oder hier ablegen')).toBeVisible();
});

