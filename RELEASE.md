# Release Checklist

Use this before publishing or deploying MediaForge.

## 1. Local Checks

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest apps/api/tests apps/worker/tests -q

cd apps/frontend
npm ci
npm run check
npx playwright test --config=playwright.config.ts
```

## 2. Docker Checks

The API image builds and embeds the frontend, so `apps/frontend/dist` does not need to be committed.

```powershell
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml build api worker clamav
```

Optional local smoke run:

```powershell
Copy-Item .env.example .env
docker compose -f docker/docker-compose.yml up -d --build
Invoke-RestMethod http://localhost:8787/health
```

## 3. Required Configuration

Set these in `.env` or your deployment secret store:

```text
API_PORT
TZ
WORKER_CONCURRENCY
DATABASE_URL
REDIS_URL
DATA_LOG_DIR
DATA_UPLOAD_DIR
DATA_OUTPUT_DIR
MAX_UPLOAD_BYTES
OUTPUT_RETENTION_HOURS
OUTPUT_CLEANUP_INTERVAL_SECONDS
DOCUMENT_CONVERT_TIMEOUT_SECONDS
```

## 4. Data And Backups

- SQLite database, logs, uploads and generated media live under `data/`.
- Container-private scratch uses separate disk-backed Docker volumes; preserve
  `clamav-db` and `redis-data` during upgrades. Do not use `down --volumes` on production.
- Generated output files are deleted after `OUTPUT_RETENTION_HOURS`; expired and manually deleted jobs are hidden from the default frontend lists.
- Back up `data/db.sqlite3` before updates.
- Do not commit `data/` to GitHub.

## 5. GitHub Publication

Before pushing:

- Confirm `.env` is not present in the commit.
- Confirm `data/`, `node_modules/`, `dist/`, virtualenvs and Playwright reports are ignored.
- Run GitHub Actions after push and check Python tests, frontend checks, Playwright and Docker build.

## 6. Post-Deploy Smoke Checks

- `GET /health` returns `{ "status": "ok" }`.
- Frontend opens at the configured `API_PORT`.
- A test job can be created and logs stream over SSE.
- A finished job shows a deletion timer, can be extended, and can be manually deleted.
- An uploaded DOCX/PDF/XLSX/PPTX test file can be converted with the worker image.
- Worker processes queued jobs.

## Lightweight runtime verification

- Install local test tools with `python -m pip install -r requirements-test.txt`.
- Run `python -m pytest apps/api/tests apps/worker/tests docker/clamav/test_gateway.py -q`.
- CI also starts the real clamd binary with a temporary synthetic test signature
  database. Production still uses `OfficialDatabaseOnly yes` and validated updates.
- Update old environment overrides deliberately: worker concurrency 1, small
  tmpfs 64 MiB, scanner timeout 900 seconds. Do not lower the scanner memory limit
  based on idle measurements; active scans and updates still need memory.
- After deploying, check a clean file and an isolated EICAR test, cold start,
  two simultaneous flows, timeout/error handling and unchanged download blocking.
- After 60 seconds without scans, confirm clamd exits and RAM falls. Repeated
  health checks must not restart it. Repeat after a real signature update.
- Check Docker storage placement/quota and temporary files after a failed job.
- Drain work before upgrade/rollback. Roll back all three images and their
  matching Compose configuration together; keep database and signature volumes.
- Deployment to TrueNAS requires the operator's explicit approval of the concrete
  update. Local test success is not a production memory benchmark.
