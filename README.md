# MediaForge

MediaForge is a self-hosted media download and conversion hub for a NAS, home server or private Docker host.

It provides a FastAPI backend, a Celery/Redis worker pipeline, ffmpeg-based media conversion and a React frontend served by the API container.

The committed app logo lives at `apps/frontend/public/logo.png`. Vite serves it as `/logo.png`, and the frontend uses the same transparent logo for the header brand mark, media fallback thumbnail and browser tab icon.

## Features

- Download online media and convert it to common audio or video formats.
- Convert uploaded audio, video, image, PDF, Office and OpenDocument files.
- Choose quality presets, target format and advanced codec settings.
- Stream job progress and logs with Server-Sent Events.
- Keep generated output files for 24 hours by default, show a live deletion timer and delete them automatically to save storage.
- Extend individual finished jobs by 24 hours or delete them manually before expiry.
- Hide expired and manually deleted jobs from the frontend job lists.
- Remove uploaded source files after processing.

## Supported Output Formats

Audio:

```text
mp3, m4a, aac, opus, ogg, oga, weba, mka, wav, flac, aiff, alac, wma
```

Video:

```text
mp4, webm, mkv, mov, m4v, avi, mpg, mpeg, flv, wmv, ogv, ts, m2ts, mts, vob, 3gp, 3g2
```

Image:

```text
webp, jpg, png, avif, gif, bmp, tiff, ico, svg, jp2, tga
```

Documents:

```text
docx, doc, odt, rtf, txt, html, pdf, epub
```

Spreadsheets:

```text
xlsx, xls, ods, csv, html, pdf
```

Presentations:

```text
pptx, ppt, odp, html, pdf
```

PDF/Text:

```text
pdf, txt, html
```

Additional common input-only extensions are recognized for conversion, including Office macro/template files (`docm`, `dotx`, `xlsm`, `ppsx`), AVCHD/mobile video (`mts`, `m2ts`, `3gp`, `3g2`), JPEG 2000 aliases (`j2k`, `jpf`, `jpx`) and common text sources (`md`, `json`, `xml`, `yaml`).
HEIC/HEIF files are recognized as image inputs when possible, but they are not offered as target formats unless the ffmpeg build reliably supports writing them.
JPEG, TIF, AIF and JPEG 2000 aliases are accepted as input/output aliases for their canonical target formats, but the UI shows only the canonical names.
Unsupported project or editor-native files, such as Photoshop `psd` files, are rejected before upload with a compatibility message.
PDF files can be exported to image formats as a ZIP with one image per page; images can also be wrapped into PDF.

## Requirements

- Docker Desktop or Docker Engine with Docker Compose
- Node.js 18+ for frontend development
- Python 3.11 for backend and worker tests

## Quick Start

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Build and start the stack:

```powershell
docker compose -f docker/docker-compose.yml up -d --build
```

Open the app:

```text
http://localhost:8787
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8787/health
```

Stop the stack:

```powershell
docker compose -f docker/docker-compose.yml down
```

## Configuration

Important environment variables:

```text
API_PORT=8787
TZ=Europe/Berlin
WORKER_CONCURRENCY=2
DATABASE_URL=sqlite:////data/db.sqlite3
REDIS_URL=redis://redis:6379/0
DATA_LOG_DIR=/data/logs
DATA_UPLOAD_DIR=/data/uploads
DATA_OUTPUT_DIR=/data/output
MAX_UPLOAD_BYTES=2147483648
OUTPUT_RETENTION_HOURS=24
OUTPUT_CLEANUP_INTERVAL_SECONDS=3600
DOCUMENT_CONVERT_TIMEOUT_SECONDS=120
```

`OUTPUT_RETENTION_HOURS` controls how long successful output files remain downloadable. The default is 24 hours.

`OUTPUT_CLEANUP_INTERVAL_SECONDS` controls how often the API checks for expired output files. The default is 3600 seconds. Set it to `0` to disable the background cleanup loop; `/api/jobs` still performs a cleanup pass before returning jobs.

`DOCUMENT_CONVERT_TIMEOUT_SECONDS` controls the LibreOffice/Poppler conversion timeout for uploaded document jobs.

Runtime files are stored in the root `data/` directory locally and mounted as `/data` inside the containers. The database, logs, uploads, temporary processing files, generated output and archives belong there and are ignored by Git.

## Data Retention

Generated output files are deleted after the configured retention window. When a file expires:

- the file is removed from `DATA_OUTPUT_DIR`
- the job is marked as `expired`
- `output_path` is cleared
- the job no longer appears in the default frontend job lists
- logs and database history remain available for audit/debugging

Users can extend a finished job by 24 hours per click or delete it manually before expiry. Manual deletion marks the job as `deleted`, removes the output file and hides the job from the default frontend lists.

Uploads are temporary processing inputs and are removed by the worker after conversion.

## Local Development

Backend and worker tests:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest apps/api/tests apps/worker/tests -q
```

Frontend:

```powershell
cd apps/frontend
npm ci
npm run check
npm run dev
```

Static frontend assets live in `apps/frontend/public/`. Keep the committed logo assets there; do not keep duplicate root-level logo files.

Playwright E2E:

```powershell
cd apps/frontend
npx playwright test --config=playwright.config.ts
```

## Docker Images

The API image builds the frontend and copies the Vite output to `/app/static`. Commit source files and public frontend assets, but do not commit `apps/frontend/dist`.

The worker image installs ffmpeg, LibreOffice, Poppler tools and fonts, then runs Celery. Actual codec availability depends on the ffmpeg package in the image.

Checks before deployment:

```powershell
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml build api worker
```

## Release Checklist

Before publishing a GitHub release:

- Run backend and worker tests.
- Run frontend typecheck/build and Playwright tests.
- Confirm `.env` is not committed.
- Confirm `apps/frontend/public/logo.png` exists and no duplicate root-level logo files or preview scratch files are staged.
- Confirm `/data/`, SQLite databases, logs, generated media, `node_modules/`, `dist/`, Playwright reports, TypeScript cache files and virtual environments are ignored.
- Build the Docker images from a clean checkout.
- Start the stack and verify `/health`, the frontend, one download job and one upload conversion.

## Repository Contents

Commit:

- source code under `apps/`
- frontend public assets, including `apps/frontend/public/logo.png`
- Docker files under `docker/` and app Dockerfiles
- tests and documentation
- `.env.example`
- release notes/checklists

Do not commit:

- `.env` or secrets
- `/data/`, SQLite databases, logs or generated media files
- `node_modules/`, `dist/`, Playwright reports or Python virtual environments
- root-level scratch assets such as `/logo.png`, `tmp_*` files or local preview HTML
- local Docker override files

## Structure

```text
apps/api       FastAPI app, models, schemas and tests
apps/worker    Celery worker and worker tests
apps/frontend  React/Vite frontend, public assets and E2E tests
docker          Docker Compose stack
docs            Notes and risk documentation
scripts         Local recovery/helper scripts
```

## License

See [LICENSE](LICENSE).
