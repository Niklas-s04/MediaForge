import { test, expect } from '@playwright/test';

test('confirms aggressive profile warning through force job creation', async ({ page }) => {
  const jobRequests: { force: string | null; body: any }[] = [];

  page.on('console', (msg) => {
    console.log('PW CONSOLE >', msg.type(), msg.text());
  });
  page.on('pageerror', (err) => {
    console.log('PW PAGEERROR >', err.message, err.stack);
  });

  await page.route('**/api/compression/goals', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        families: {
          audio: {
            profiles: {
              balanced: {},
              small: {},
            },
          },
        },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    const requestUrl = new URL(route.request().url());
    const profile = requestUrl.searchParams.get('profile');
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        profile,
        family: 'audio',
        warning: profile === 'small' ? 'Aggressive profile: noticeable quality loss possible.' : null,
      }),
    });
  });

  await page.route('**/api/presets', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ default: {} }),
    });
  });

  await page.route('**/health', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' }),
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
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ id: 123, type: 'download', status: 'queued', progress: 0 }),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.waitForSelector('text=NAS Convert Hub', { timeout: 60000 });

  await page.fill('input[placeholder="url"]', 'https://example.invalid/sample.mp3');
  await page.selectOption('[data-testid="compression-family"]', 'audio');
  await page.selectOption('[data-testid="compression-profile"]', 'small');

  await expect(page.locator('.warning')).toContainText('Aggressive');

  await page.click('button:has-text("Create Job")');
  await expect(page.locator('.modal')).toBeVisible();

  await page.click('.modal button.confirm');
  await expect(page.locator('text=Job created: 123')).toBeVisible();

  expect(jobRequests).toHaveLength(2);
  expect(jobRequests[0].force).toBeNull();
  expect(jobRequests[0].body.input.compression_profile).toBe('small');
  expect(jobRequests[0].body.input.lang).toBe('de');
  expect(jobRequests[1].force).toBe('true');
  expect(jobRequests[1].body.input.compression_profile).toBe('small');
  expect(jobRequests[1].body.input.lang).toBe('de');
});
