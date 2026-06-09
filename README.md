# MediaForge

MediaForge is a self-hosted media download and conversion hub for a NAS, home server or private Docker host.

It provides a FastAPI backend, a Celery/Redis worker pipeline, ffmpeg-based media conversion and a React frontend served by the API container.

## Features

- Download online media and convert it to common audio or video formats.
- Convert uploaded audio, video and image files.
- Choose quality presets, target format and advanced codec settings.
- Stream job progress and logs with Server-Sent Events.
- Keep generated output files for 24 hours by default, then delete them automatically to save storage.
- Hide expired jobs from the frontend job lists after cleanup.
- Remove uploaded source files after processing.

## Supported Output Formats

Audio:

```text
mp3, m4a, aac, opus, ogg, oga, wav, flac, aiff, alac, wma
```

Video:

```text
mp4, webm, mkv, mov, m4v, avi, mpg, mpeg, flv, wmv, ogv, ts, vob
```

Image:

```text
webp, jpg, jpeg, png, avif, gif, bmp, tiff, tif
```

HEIC/HEIF files are recognized as image inputs when possible, but they are not offered as target formats unless the ffmpeg build reliably supports writing them.

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
```

`OUTPUT_RETENTION_HOURS` controls how long successful output files remain downloadable. The default is 24 hours.

`OUTPUT_CLEANUP_INTERVAL_SECONDS` controls how often the API checks for expired output files. The default is 3600 seconds. Set it to `0` to disable the background cleanup loop; `/api/jobs` still performs a cleanup pass before returning jobs.

Runtime files are stored in `data/` locally and mounted as `/data` inside the containers. This directory is ignored by Git.

## Data Retention

Generated output files are deleted after the configured retention window. When a file expires:

- the file is removed from `DATA_OUTPUT_DIR`
- the job is marked as `expired`
- `output_path` is cleared
- the job no longer appears in the default frontend job lists
- logs and database history remain available for audit/debugging

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

Playwright E2E:

```powershell
cd apps/frontend
npx playwright test --config=playwright.config.ts
```

## Docker Images

The API image builds the frontend and copies the Vite output to `/app/static`. Do not commit `apps/frontend/dist`.

The worker image installs ffmpeg and runs Celery. Actual codec availability depends on the ffmpeg package in the image.

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
- Confirm `data/`, SQLite databases, logs, generated media, `node_modules/`, `dist/`, Playwright reports and virtual environments are ignored.
- Build the Docker images from a clean checkout.
- Start the stack and verify `/health`, the frontend, one download job and one upload conversion.

## Repository Contents

Commit:

- source code under `apps/`
- Docker files under `docker/` and app Dockerfiles
- tests and documentation
- `.env.example`
- release notes/checklists

Do not commit:

- `.env` or secrets
- `data/`, SQLite databases, logs or generated media files
- `node_modules/`, `dist/`, Playwright reports or Python virtual environments
- local Docker override files

## Structure

```text
apps/api       FastAPI app, models, schemas and tests
apps/worker    Celery worker and worker tests
apps/frontend  React/Vite frontend and E2E tests
docker          Docker Compose stack
docs            Notes and risk documentation
scripts         Local recovery/helper scripts
```

## License

See [LICENSE](LICENSE).
