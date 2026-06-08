# MediaForge

MediaForge is a small self-hosted media download and conversion hub.

It includes:

- FastAPI backend with jobs, flows and SSE log streaming
- Celery worker for downloads and ffmpeg conversion
- React/Vite frontend served by the API container
- Redis as the task broker
- SQLite as the default local database

## Requirements

- Docker Desktop or Docker Engine with Docker Compose
- Node.js 18+ for frontend development
- Python 3.11 for backend and worker tests

## Quick Start With Docker

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
MAX_UPLOAD_BYTES=2147483648
```

Runtime files are stored in `data/` locally and mounted as `/data` inside the containers. This directory is ignored by Git.

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

## Docker

The API image builds the frontend and copies it to `/app/static`. You do not need to commit `apps/frontend/dist`.

Checks before deployment:

```powershell
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml build api worker
```

## Repository Contents

Commit:

- source code under `apps/`
- Docker files under `docker/` and app Dockerfiles
- tests, documentation and GitHub Actions
- `.env.example`

Do not commit:

- `.env` or secrets
- `data/`, SQLite databases, logs or generated media files
- `node_modules/`, `dist/`, Playwright reports or Python virtual environments

## Structure

```text
apps/api       FastAPI app, models, schemas and tests
apps/worker    Celery worker and worker tests
apps/frontend  React/Vite frontend and E2E tests
docker          Docker Compose stack
docs            Notes and risk documentation
scripts         Local recovery/helper scripts
```
