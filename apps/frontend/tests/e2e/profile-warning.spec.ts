import { test, expect } from '@playwright/test';

test('starts in dark mode on the converter tab', async ({ page }) => {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path === '/api/jobs'
      ? []
      : path === '/api/options'
        ? {
            download: { formats: { video: ['mkv'], audio: ['mp3'] } },
            convert: { formats: { video: ['mkv'], audio: ['mp3'], image: ['png'] } },
          }
        : { warning: null };
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#080d16');
  await expect(page.getByRole('tab', { name: 'Konvertieren' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'Dateien im Batch konvertieren' })).toBeVisible();

  const themeToggle = page.locator('.theme-toggle');
  await expect(themeToggle).toHaveAttribute('aria-pressed', 'true');
  await expect(themeToggle).toContainText('Dunkel');
  await themeToggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#f5f7fb');
});

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


  await page.getByRole('tab', { name: 'Download' }).click();
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
  expect(jobRequests[0].body.input.output_format).toBe('mkv');
  expect(jobRequests[0].body.input.quality_preset).toBe('small');
  expect(jobRequests[0].body.input.compression_profile).toBe('small');
  expect(jobRequests[1].force).toBe('true');
});

test('clears selected local files after successful batch conversion', async ({ page }) => {
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ warning: null }),
    });
  });

  await page.route('**/api/jobs/convert-batch*', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'batch-456',
        jobs: [{ id: 456, type: 'convert', status: 'queued', progress: 0 }],
      }),
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
  await expect(page.locator('.batch-file-row').getByText('sample.wav')).toBeVisible();
  await expect(page.getByRole('button', { name: /MP3 Audio/ })).toBeVisible();

  await page.click('button:has-text("1 Konvertierung starten")');

  await expect(page.locator('text=Batch gestartet: 1 Konvertierungen')).toBeVisible();
  await expect(page.locator('text=sample.wav')).toHaveCount(0);
  await expect(page.locator('text=Dateien auswählen oder hier ablegen')).toBeVisible();
});

test('controls metadata preservation separately for each supported batch file', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mkv'], audio: ['mp3'] } },
        convert: { formats: { audio: ['mp3'], document: ['docx'] } },
        metadata_preservation: { audio: ['mp3'] },
      }),
    });
  });
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });
  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');
  await page.setInputFiles('#file-upload', [
    {
      name: 'song.wav',
      mimeType: 'audio/wav',
      buffer: Buffer.from('fake-audio'),
    },
    {
      name: 'report.docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      buffer: Buffer.from('fake-document'),
    },
  ]);

  const metadataButton = page.getByRole('button', { name: 'Metadaten erhalten' });
  await expect(metadataButton).toBeVisible();
  await expect(page.getByText('Keine Metadatenübernahme')).toBeVisible();
  await expect(metadataButton).toHaveAttribute('aria-pressed', 'true');
  await metadataButton.click();
  await expect(page.getByRole('button', { name: 'Metadaten entfernen' })).toHaveAttribute('aria-pressed', 'false');
});

test('asks before adding files with duplicate names', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mkv'], audio: ['mp3'] } },
        convert: { formats: { audio: ['mp3'] } },
      }),
    });
  });
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });
  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');

  await page.setInputFiles('#file-upload', {
    name: 'sample.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('first-audio'),
  });
  await expect(page.locator('.batch-file-row')).toHaveCount(1);

  await page.setInputFiles('#file-upload', {
    name: 'sample.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('second-audio'),
  });
  await expect(page.getByRole('dialog', { name: 'Doppelte Dateinamen' })).toBeVisible();
  await expect(page.locator('.batch-file-row')).toHaveCount(1);

  await page.getByRole('button', { name: 'Nicht hinzufügen' }).click();
  await expect(page.getByRole('dialog', { name: 'Doppelte Dateinamen' })).toHaveCount(0);
  await expect(page.locator('.batch-file-row')).toHaveCount(1);

  await page.setInputFiles('#file-upload', {
    name: 'SAMPLE.WAV',
    mimeType: 'audio/wav',
    buffer: Buffer.from('third-audio'),
  });
  await expect(page.getByRole('dialog', { name: 'Doppelte Dateinamen' })).toContainText('SAMPLE.WAV');
  await page.getByRole('button', { name: 'Trotzdem hinzufügen' }).click();
  await expect(page.locator('.batch-file-row')).toHaveCount(2);
  await expect(page.locator('text=1 doppelte Datei wurde trotzdem hinzugefügt.')).toBeVisible();
});

test('configures batch formats per file and downloads the finished ZIP', async ({ page }) => {
  let batchStarted = false;
  let multipartBody = '';
  const finishedJobs = [
    { id: 701, type: 'convert', status: 'success', progress: 100, current_step: 'Fertig', output_path: '/data/output/job-701-clip.mkv' },
    { id: 702, type: 'convert', status: 'success', progress: 100, current_step: 'Fertig', output_path: '/data/output/job-702-photo.jpg' },
  ];

  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mkv'], audio: ['mp3'] } },
        convert: { formats: { video: ['mkv', 'mp4'], audio: ['mp3'], image: ['png', 'jpg'] } },
      }),
    });
  });
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });
  await page.route('**/api/jobs/convert-batch*', (route) => {
    multipartBody = route.request().postData() || '';
    batchStarted = true;
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'batch-ui',
        jobs: finishedJobs.map((job) => ({ ...job, status: 'queued', progress: 0, output_path: null })),
      }),
    });
  });
  await page.route('**/api/jobs/*/events', (route) => {
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'id: 0\ndata: {"status":"success"}\n\n' });
  });
  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(batchStarted ? finishedJobs : []),
    });
  });
  await page.route('**/api/batches/batch-ui/download', (route) => {
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="mediaforge-batch-batch-ui.zip"',
      },
      body: Buffer.from('fake-zip'),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');
  await page.setInputFiles('#file-upload', [
    { name: 'clip.mp4', mimeType: 'video/mp4', buffer: Buffer.from('video') },
    { name: 'photo.png', mimeType: 'image/png', buffer: Buffer.from('image') },
  ]);

  const rows = page.locator('.batch-file-row');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).getByRole('button', { name: /MKV Video/ })).toBeVisible();
  await rows.nth(1).getByRole('button', { name: /PNG Bild/ }).click();
  await rows.nth(1).locator('.format-results').getByRole('button', { name: /JPG/ }).click();
  await expect(rows.nth(1).getByRole('button', { name: /JPG Bild/ })).toBeVisible();
  await expect(rows.nth(0).getByRole('button', { name: /MKV Video/ })).toBeVisible();

  await page.click('button:has-text("2 Konvertierungen starten")');
  await expect(page.getByRole('button', { name: 'ZIP herunterladen (2)' })).toBeEnabled();
  expect(multipartBody).toContain('{"compression_family":"video","output_format":"mkv","preserve_metadata":true}');
  expect(multipartBody).toContain('{"compression_family":"image","output_format":"jpg","preserve_metadata":true}');

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'ZIP herunterladen (2)' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mediaforge-batch-batch-ui.zip');
});

test('rejects incompatible local files before upload', async ({ page }) => {
  let uploadAttempted = false;

  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { video: ['mp4'], audio: ['mp3'], image: ['webp'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ warning: null }),
    });
  });

  await page.route('**/api/jobs/convert-batch*', (route) => {
    uploadAttempted = true;
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'should not upload' }) });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');

  await page.setInputFiles('#file-upload', {
    name: 'layout.psd',
    mimeType: 'image/vnd.adobe.photoshop',
    buffer: Buffer.from('fake-psd'),
  });

  await expect(page.locator('text=Nicht kompatibel: layout.psd')).toBeVisible();
  await expect(page.locator('text=Dateien auswählen oder hier ablegen')).toBeVisible();

  await page.click('button:has-text("Konvertierungen starten")');
  await expect(page.locator('text=Bitte mindestens eine Datei auswählen.')).toBeVisible();
  expect(uploadAttempted).toBe(false);
});

test('keeps streamed job logs stable across job polling refreshes', async ({ page }) => {
  let jobPolls = 0;

  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { video: ['mp4'], audio: ['mp3'], image: ['webp'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs/321/events', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'id: 84\ndata: {"status":"success","progress":100,"current_step":"Fertig","chunk":"[test] Conversion finished\\n"}\n\n',
    });
  });

  await page.route('**/api/jobs', (route) => {
    jobPolls += 1;
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 321, type: 'convert', status: 'success', progress: 100, current_step: 'Fertig', output_path: '/data/output/job-321.mp3' },
      ]),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("#321 Konvertierung")');

  await expect(page.locator('.log-panel')).toHaveCount(0);
  await page.getByRole('button', { name: /Details \/ Log anzeigen/ }).click();
  await expect(page.locator('.log-panel')).toContainText('Conversion finished');
  await page.locator('button:has-text("Aktualisieren")').click();
  await expect(page.locator('.log-panel')).toContainText('Conversion finished');
  await expect(page.locator('.log-panel')).not.toContainText('Noch keine Logs vorhanden.');
  expect(jobPolls).toBeGreaterThanOrEqual(2);
});

test('shows upload processing state before conversion job is created', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { audio: ['mp3'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs/convert-batch*', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        batch_id: 'batch-654',
        jobs: [{ id: 654, type: 'convert', status: 'queued', progress: 0 }],
      }),
    });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');
  await page.setInputFiles('#file-upload', {
    name: 'large.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.alloc(5 * 1024 * 1024, 1),
  });

  await page.click('button:has-text("1 Konvertierung starten")');
  await expect(page.locator('.transfer-progress')).toContainText(/Upload|verarbeitet/);
  await expect(page.locator('text=Batch gestartet: 1 Konvertierungen')).toBeVisible();
});

test('downloads finished output with unknown response length', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { audio: ['mp3'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs/789/download', (route) => {
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': 'attachment; filename="result.mp3"',
      },
      body: Buffer.from('media-output'),
    });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 789, type: 'convert', status: 'success', progress: 100, current_step: 'Fertig', output_path: '/data/output/result.mp3' },
      ]),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.getByTestId('history-toggle').click();
  await page.locator('.download-row button:has-text("Download")').click();

  await expect(page.locator('.transfer-progress')).toContainText('Download: Auftrag #789');
  await expect(page.locator('.transfer-progress')).toContainText('100%');
});

test('closes the format picker when clicking outside of it', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4', 'webm', 'wmv'], audio: ['mp3', 'alac'] } },
        convert: { formats: { video: ['mp4'], audio: ['mp3'], image: ['webp'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });

  await page.getByRole('tab', { name: 'Download' }).click();
  await page.getByRole('button', { name: /MP4 Video/ }).click();
  await expect(page.locator('.format-menu')).toBeVisible();
  await expect(page.getByRole('button', { name: /WMV/ })).toBeVisible();

  await page.locator('.format-categories').getByRole('button', { name: 'Audio' }).click();
  await expect(page.getByRole('button', { name: /ALAC/ })).toBeVisible();

  await page.locator('.url-row input').click();
  await expect(page.locator('.format-menu')).toHaveCount(0);
});

test('hides expired jobs from the frontend lists', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { video: ['mp4'], audio: ['mp3'], image: ['webp'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 11, type: 'convert', status: 'expired', progress: 100, current_step: 'Ausgabedatei nach 24h gelöscht', output_path: null },
        { id: 12, type: 'convert', status: 'success', progress: 100, current_step: 'Fertig', output_path: '/data/output/job-12.mp3' },
      ]),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });

  await expect(page.getByText('#11 Konvertierung')).toHaveCount(0);
  await expect(page.getByText('#12 Konvertierung')).toBeVisible();
  await expect(page.getByTestId('history-toggle').locator('.count-label')).toHaveText('1');
  await page.getByTestId('history-toggle').click();
  await expect(page.getByText('Auftrag #12')).toBeVisible();
  await expect(page.getByText('Auftrag #11')).toHaveCount(0);
});

test('shows document formats for uploaded office files', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: {
          formats: {
            video: ['mp4'],
            audio: ['mp3'],
            image: ['webp'],
            document: ['docx', 'pdf', 'html'],
            pdf: ['pdf', 'txt'],
            text: ['txt', 'pdf'],
          },
        },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');
  await page.setInputFiles('#file-upload', {
    name: 'report.docx',
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    buffer: Buffer.from('fake-docx'),
  });

  await expect(page.locator('.batch-file-row').getByText(/KB · Dokument/)).toBeVisible();
  await page.getByRole('button', { name: /DOCX Dokument/ }).click();
  await expect(page.locator('.format-menu')).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /PDF/ })).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /HTML/ })).toBeVisible();
});

test('shows canonical image formats and PDF image bridge', async ({ page }) => {
  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: {
          formats: {
            image: ['webp', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'ico', 'svg'],
            pdf: ['pdf', 'txt'],
            text: ['txt', 'pdf'],
          },
        },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });
  await page.click('button:has-text("Konvertieren")');
  await page.setInputFiles('#file-upload', {
    name: 'photo.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('fake-jpg'),
  });

  await expect(page.locator('.batch-file-row').getByText(/KB · Bild/)).toBeVisible();
  await page.getByRole('button', { name: /PNG Bild/ }).click();
  await expect(page.locator('.format-results').getByRole('button', { name: /JPG/ })).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /TIFF/ })).toHaveCount(1);
  await expect(page.locator('.format-results').getByRole('button', { name: /JPEG/ })).toHaveCount(0);
  await expect(page.locator('.format-results').getByRole('button', { name: /^TIF(?!F)/ })).toHaveCount(0);

  await page.locator('.format-categories').getByRole('button', { name: 'PDF' }).click();
  await expect(page.locator('.format-results').getByRole('button', { name: /PDF/ })).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /TXT/ })).toHaveCount(0);

  await page.mouse.click(5, 5);
  await page.setInputFiles('#file-upload', {
    name: 'scan.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('fake-pdf'),
  });

  const pdfRow = page.locator('.batch-file-row').filter({ hasText: 'scan.pdf' });
  await expect(pdfRow.getByText(/KB · PDF/)).toBeVisible();
  await pdfRow.getByRole('button', { name: /PDF PDF/ }).click();
  await pdfRow.locator('.format-categories').getByRole('button', { name: 'Bild' }).click();
  await expect(page.locator('.format-results').getByRole('button', { name: /JPG/ })).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /ICO/ })).toBeVisible();
  await expect(page.locator('.format-results').getByRole('button', { name: /SVG/ })).toBeVisible();
});

test('extends and deletes finished jobs from the frontend', async ({ page }) => {
  let job = {
    id: 44,
    type: 'convert',
    status: 'success',
    progress: 100,
    current_step: 'Fertig',
    output_path: '/data/output/job-44.pdf',
    expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  };

  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mp4'], audio: ['mp3'] } },
        convert: { formats: { video: ['mp4'], audio: ['mp3'], image: ['webp'] } },
      }),
    });
  });

  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });

  await page.route('**/api/jobs/44/extend', (route) => {
    job = { ...job, expires_at: new Date(Date.now() + 25 * 60 * 60 * 1000).toISOString() };
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(job) });
  });

  await page.route('**/api/jobs/44', (route) => {
    if (route.request().method() === 'DELETE') {
      job = { ...job, status: 'deleted', output_path: null };
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(job) });
      return;
    }
    route.fallback();
  });

  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(job.status === 'deleted' ? [] : [job]),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });

  await page.getByTestId('history-toggle').click();
  await expect(page.getByText('Löscht in')).toBeVisible();
  await page.locator('.download-row').getByRole('button', { name: 'Verlängern' }).click();
  await expect(page.getByText('Auftrag #44 wurde um 24h verlängert.')).toBeVisible();

  await page.locator('.download-row').getByRole('button', { name: 'Löschen' }).click();
  await expect(page.getByText('#44 Konvertierung')).toHaveCount(0);
  await expect(page.locator('.download-row')).toHaveCount(0);
});

test('expands the finished history and handles all files at once', async ({ page }) => {
  const finishedJobs = [
    {
      id: 81,
      type: 'convert',
      status: 'success',
      progress: 100,
      current_step: 'Fertig',
      output_path: '/data/output/holiday.mkv',
    },
    {
      id: 82,
      type: 'convert',
      status: 'success',
      progress: 100,
      current_step: 'Fertig',
      output_path: '/data/output/cover.png',
    },
  ];
  let historyDeleted = false;

  await page.route('**/api/options', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        download: { formats: { video: ['mkv'], audio: ['mp3'] } },
        convert: { formats: { video: ['mkv'], audio: ['mp3'], image: ['png'] } },
      }),
    });
  });
  await page.route('**/api/compression/profile*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ warning: null }) });
  });
  await page.route('**/api/history/download', (route) => {
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="mediaforge-chronik-test.zip"',
      },
      body: Buffer.from('history-zip'),
    });
  });
  await page.route('**/api/history', (route) => {
    if (route.request().method() !== 'DELETE') {
      route.fallback();
      return;
    }
    historyDeleted = true;
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ deleted: 2 }),
    });
  });
  await page.route('**/api/jobs', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(historyDeleted ? [] : finishedJobs),
    });
  });

  await page.goto('/');
  await page.waitForFunction(() => (window as any).__APP_READY__ === true, null, { timeout: 60000 });

  const historyToggle = page.getByTestId('history-toggle');
  await expect(historyToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(historyToggle.locator('.count-label')).toHaveText('2');
  await expect(page.locator('.download-row')).toHaveCount(0);

  await historyToggle.click();
  await expect(historyToggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.download-row')).toHaveCount(2);

  const downloadPromise = page.waitForEvent('download');
  await page.getByTestId('history-download-all').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('mediaforge-chronik-test.zip');

  await page.getByTestId('history-delete-all').click();
  const dialog = page.getByRole('dialog', { name: 'Chronik löschen' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Alle löschen' }).click();

  await expect(page.getByText('2 fertige Datei(en) wurden aus der Chronik gelöscht.')).toBeVisible();
  await expect(page.locator('.download-row')).toHaveCount(0);
  await expect(historyToggle.locator('.count-label')).toHaveText('0');
});

