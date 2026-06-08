# MediaForge

MediaForge ist ein kleiner, selbst gehosteter Media-Download- und Konvertierungs-Hub.

Enthalten sind:

- FastAPI-Backend mit Basic Auth, Jobs, Flows und SSE-Logstreams
- Celery-Worker fuer Downloads und ffmpeg-Konvertierung
- React/Vite-Frontend, das vom API-Container ausgeliefert wird
- Redis als Broker und SQLite als einfache lokale Datenbank

## Voraussetzungen

- Docker Desktop oder Docker Engine mit Docker Compose
- Node.js 18+ fuer Frontend-Entwicklung
- Python 3.11 fuer Backend- und Worker-Tests

## Schnellstart mit Docker

Beispiel-Konfiguration kopieren und Passwort anpassen:

```powershell
Copy-Item .env.example .env
```

Stack bauen und starten:

```powershell
docker compose -f docker/docker-compose.yml up -d --build
```

App oeffnen:

```text
http://localhost:8787
```

Healthcheck:

```powershell
Invoke-RestMethod http://localhost:8787/health
```

Der Compose-Login ist standardmaessig `admin` / `change-me`. Vor Nutzung ausserhalb lokaler Tests unbedingt `ADMIN_PASSWORD` in `.env` aendern.

## Konfiguration

Wichtige Umgebungsvariablen:

```text
API_PORT=8787
TZ=Europe/Berlin
ADMIN_USER=admin
ADMIN_PASSWORD=change-me
WORKER_CONCURRENCY=2
DATABASE_URL=sqlite:////data/db.sqlite3
REDIS_URL=redis://redis:6379/0
DATA_LOG_DIR=/data/logs
```

Laufzeitdaten liegen lokal unter `data/` und im Container unter `/data`. Dieser Ordner wird nicht zu GitHub hochgeladen.

## Lokale Entwicklung

Backend- und Worker-Tests:

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

Das API-Image baut das Frontend selbst und kopiert es nach `/app/static`. `apps/frontend/dist` muss deshalb nicht committed werden.

Vor einem Deployment pruefen:

```powershell
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml build api worker
```

## Was gehoert ins Repository?

Committen:

- Quellcode unter `apps/`
- Docker-Dateien unter `docker/` und die App-Dockerfiles
- Tests, Dokumentation und GitHub Actions
- `.env.example`

Nicht committen:

- `.env` oder Secrets
- `data/`, SQLite-Datenbanken, Logs und generierte Mediendateien
- `node_modules/`, `dist/`, Playwright-Reports und Python-Virtualenvs

## Struktur

```text
apps/api       FastAPI-App, Modelle, Schemas, Tests
apps/worker    Celery-Worker und Worker-Tests
apps/frontend  React/Vite-Frontend und E2E-Tests
docker          Docker-Compose-Stack
docs            Notizen und Risiko-Dokumentation
scripts         Lokale Recovery-/Hilfsskripte
```
