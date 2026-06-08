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
docker compose -f docker/docker-compose.yml build api worker
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
ADMIN_USER
ADMIN_PASSWORD
WORKER_CONCURRENCY
DATABASE_URL
REDIS_URL
DATA_LOG_DIR
```

Change `ADMIN_PASSWORD` before exposing the app.

## 4. Data And Backups

- SQLite database, logs, temporary files and generated media live under `data/`.
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
- Worker processes queued jobs.
