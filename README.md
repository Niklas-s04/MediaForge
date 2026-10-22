# MediaForge

MediaForge is a self-hosted media download and conversion hub for a NAS, home server or private Docker host.

It provides a FastAPI backend, a Celery/Redis worker pipeline, ffmpeg-based media conversion and a React frontend served by the API container.

The committed app logo lives at `apps/frontend/public/logo.png`. Vite serves it as `/logo.png`, and the frontend uses the same transparent logo for the header brand mark, media fallback thumbnail and browser tab icon.

## Features

- Download online media and convert it to common audio or video formats.
- Convert multiple uploaded audio, video, image, PDF, Office and OpenDocument files in one batch.
- Compress mixed batches in a dedicated workspace with independent settings for every file.
- Optimize media and PDFs, repack modern Office/OpenDocument/EPUB files without changing their contents, or archive any file as ZIP, GZIP or XZ.
- Choose the target format separately for every file, download results individually or bundle a completed batch as ZIP.
- Preserve or remove metadata separately for each file when the selected source/target combination supports it.
- Keep the original base filename for converted results; collisions use ` (2)`, ` (3)` and so on instead of job IDs.
- Choose quality presets, target format and advanced codec settings.
- Stream job progress and logs with Server-Sent Events.
- Keep generated output files for 24 hours by default, show a live deletion timer and delete them automatically to save storage.
- Extend individual finished jobs by 24 hours or delete them manually before expiry.
- Hide expired and manually deleted jobs from the frontend job lists.
- Remove uploaded source files after processing.
- Scan uploaded files, remote downloads and converted outputs with ClamAV before processing or release.

The default output formats are MKV for video, PNG for images and MP3 for audio.

## Compression workspace

The **Komprimieren** tab accepts up to 100 files per batch. Choose a target for each file:

| Source | Compression targets | Controls |
| --- | --- | --- |
| Video | MP4, WebM, MKV | Quality preset, CRF, maximum width, frame rate, audio bitrate, metadata removal |
| Audio | Opus, MP3, M4A, FLAC | Quality preset, bitrate, channels, supported sample rates, metadata removal |
| Still images | WebP, AVIF, JPG, PNG | Quality preset, maximum width, image quality, metadata removal |
| PDF | PDF | Quality preset and image resolution from 72 to 300 DPI |
| DOCX, XLSX, PPTX, DOCM, XLSM, PPTM, ODT, ODS, ODP, EPUB | Original format | Lossless package recompression, levels 1, 6 and 9 |
| Any file, including legacy Office, text, code and archives | ZIP, GZIP, XZ | Lossless archive compression, levels 1, 6 and 9 |

GIF, WebP and APNG inputs default to archives so animations are not silently flattened.
Other image conversions produce a single frame. PDF optimization may change signatures
or interactive features; use an archive when exact preservation matters. Native Office
optimization preserves package entry contents, including embedded images and macros.
It does not downsample embedded images. Already compressed inputs can yield larger results;
the completed job reports original/output sizes and actual savings rather than promising
a target size. Outputs are available individually, as a batch ZIP, and in the shared history.

Compression uses the existing scanned upload/worker/download lifecycle and retention policy.
The batch endpoint accepts `operation=compress` with per-file JSON `settings`; omitting the
operation preserves conversion behavior. No database migration is required.
PDF compression requires Ghostscript, now included in the worker Dockerfile: rebuild the
worker image when deploying this update. Local development also needs Ghostscript on PATH.

The refreshed interface has light/dark themes, responsive layouts, keyboard focus states,
CSS transitions and reduced-motion support. Review evidence and verification boundaries
are documented in [docs/design-overhaul-review.md](docs/design-overhaul-review.md).

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
- Node.js 20.19+ for frontend development
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

The first start can take several minutes while ClamAV downloads its signature
database. The API starts only after the scanner reports healthy.

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
API_BIND_ADDRESS=127.0.0.1
TZ=Europe/Berlin
WORKER_CONCURRENCY=1
DATABASE_URL=sqlite:////data/db.sqlite3
REDIS_URL=redis://redis:6379/0
DATA_LOG_DIR=/data/logs
DATA_UPLOAD_DIR=/data/uploads
DATA_OUTPUT_DIR=/data/output
MAX_UPLOAD_BYTES=2147483648
REMOTE_DOWNLOAD_MAX_BYTES=2147483648
OUTPUT_RETENTION_HOURS=24
OUTPUT_CLEANUP_INTERVAL_SECONDS=3600
DOCUMENT_CONVERT_TIMEOUT_SECONDS=120
MALWARE_SCAN_ENABLED=true
CLAMAV_TIMEOUT_SECONDS=900
CLAMAV_IDLE_SECONDS=60
CLAMAV_STARTUP_SECONDS=180
CLAMAV_DATABASE_MAX_AGE_SECONDS=604800
CLAMAV_RETRIES=2
MALWARE_SCAN_MAX_BYTES=2147483648
CLAMAV_MEMORY_LIMIT=3g
CLAMAV_CPUS=2.0
```

`OUTPUT_RETENTION_HOURS` controls how long successful output files remain downloadable. The default is 24 hours.

`OUTPUT_CLEANUP_INTERVAL_SECONDS` controls how often the API checks for expired output files. The default is 3600 seconds. Set it to `0` to disable the background cleanup loop; `/api/jobs` still performs a cleanup pass before returning jobs.

`DOCUMENT_CONVERT_TIMEOUT_SECONDS` controls the LibreOffice/Poppler conversion timeout for uploaded document jobs.

The database, logs, uploads, generated output and archives are stored in the root
`data/` directory and mounted as `/data`. Large temporary files use separate
disk-backed Docker volumes (`api-scratch`, `worker-scratch`, `scanner-scratch`)
mounted at `/scratch`. Each service owns its volume; never share these volumes
between replicas. The application entrypoint removes only its private scratch
contents on restart; ClamAV removes its scan scratch after the engine stops.
User uploads and outputs are not part of this scratch cleanup.

Place Docker storage on the intended SSD pool and set a suitable storage quota
through TrueNAS. These volumes are not automatically size-limited or guaranteed
to live on an SSD; they use the host's Docker storage location and mount options.
The remaining `/tmp` tmpfs defaults to 64 MiB for small runtime files. Existing
`.env` overrides remain effective: update old 4 GiB tmpfs and concurrency values
when adopting the new defaults.

## Low idle resource usage

The scanner gateway keeps TCP port 3310 available while the ClamAV engine is
stopped. Only a scan starts `clamd` on loopback port 3311; scans are serialized,
connections and buffering are bounded, and the engine stops after
`CLAMAV_IDLE_SECONDS` without scans. Health checks do not wake it. A health
response means the gateway/updater and recent database files are available;
the actual engine validates and scans on demand. Missing, stale or invalid
signatures and scanner failures never release unscanned files.

Freshclam continues updating signatures and validates downloads. Updates and
active scans can still require substantial memory: keep the 3 GiB scanner limit
until measured on your workload. `ConcurrentDatabaseReload no` avoids two
simultaneous clamd engines during reload. A first scan after idle waits for the
database to load; `CLAMAV_TIMEOUT_SECONDS` covers this and queued scanning.
The gateway rejects databases with a daily-file modification time older than
seven days by default (`CLAMAV_DATABASE_MAX_AGE_SECONDS`).

One prefork worker child is the default. Flows schedule a step, release the
worker slot, and advance through callbacks; no worker waits for another worker
in the same queue. A step's timeout now measures its execution time, excluding
time waiting in the queue. The soft limit allows cleanup; a hard limit follows
10 seconds later. SQLite stores job/flow state; unused Celery result storage is
disabled, while Redis remains the broker. Finish active jobs and flows before
upgrading or rolling back so callbacks are not mixed between code versions.

The UI polls every 5 seconds while jobs are active, every 30 seconds when idle,
and pauses job polling in hidden tabs. Returning to a visible tab refreshes it.
SSE log reads are bounded to 64 KiB; large completed logs drain in multiple events.
PDF creation streams to disk instead of constructing a complete PDF byte string.

Measure cold idle, warm idle, scans, database updates and post-job idle separately.
The original measurements were approximately 967 MiB in the scanner container
and 190 MiB in the other three groups. They motivate this design, but are not a
before/after benchmark or a guarantee of the new consumption on your NAS.

## Malware protection and containment

Malware scanning is fail-closed and enabled by default:

- Uploads are streamed to ClamAV before a job is created.
- The worker scans again immediately before passing a file to ffmpeg, LibreOffice, Poppler or another converter.
- Remotely downloaded files are scanned before conversion.
- Remote URLs are limited to HTTP(S), reject credentials and local/non-public
  destinations, and downloads stop at `REMOTE_DOWNLOAD_MAX_BYTES`.
- Converted files are scanned before a job is marked successful and again immediately before an individual or ZIP download.
- Detected, encrypted or incompletely scanned files are blocked. If the scanner is unavailable, uploads and downloads return `503` instead of bypassing the check.
- ClamAV receives files through its `INSTREAM` protocol and has no mount of the MediaForge data directory.

The ClamAV port is available only on the private Compose network and must never
be published on the NAS. Its TCP protocol has no authentication or encryption.
`MALWARE_SCAN_ENABLED=false` is intended only for isolated development and
must not be used in production.

Compose binds the web port to `127.0.0.1` by default. Keep that setting for a
reverse proxy on the NAS. For direct trusted-LAN access, set
`API_BIND_ADDRESS` to the NAS's specific LAN address and restrict it with the
firewall; avoid `0.0.0.0`.

Antivirus signatures cannot guarantee that a file is harmless. MediaForge also
runs API and worker processes as UID/GID `10001`, removes Linux capabilities,
uses a read-only container root filesystem and gives the small tmpfs mounts
`noexec`, `nosuid` and `nodev` options. Disk scratch volumes inherit the host
filesystem's restrictions; configure equivalent restrictions on their storage
where supported. Keep the stack and its base images
updated because media parsers remain an important attack surface.

The URL check is a defense-in-depth SSRF control, not a substitute for egress
filtering: redirects and DNS behavior are ultimately handled by yt-dlp. Where
possible, use NAS/firewall rules that prevent the worker network from reaching
management interfaces and unrelated private subnets.

## TrueNAS SCALE deployment

Use a dedicated dataset such as `/mnt/SSD/apps/mediaforge/source/data` for
MediaForge. Do not expose this dataset as an SMB/NFS share and do not mount
other NAS datasets into the worker or ClamAV container. Before the first start,
or once when upgrading from the former root-running images, create the runtime
directories and assign them to the fixed container identity:

```bash
cd /mnt/SSD/apps/mediaforge/source
sudo install -d -o 10001 -g 10001 -m 0750 \
  data data/uploads data/output data/logs data/tmp
sudo chown -R 10001:10001 data
```

Build all three local images:

```bash
cd /mnt/SSD/apps/mediaforge/source
sudo git pull --ff-only
sudo docker build --no-cache -f apps/api/Dockerfile -t mediaforge-api:local .
sudo docker build --no-cache -f apps/worker/Dockerfile -t mediaforge-worker:local .
sudo docker build --no-cache -f docker/clamav/Dockerfile -t mediaforge-clamav:local docker/clamav
```

For a Compose/YAML installation, validate and recreate the stack:

```bash
sudo docker compose -f docker/docker-compose.yml config
sudo docker compose -f docker/docker-compose.yml up -d --force-recreate
sudo docker compose -f docker/docker-compose.yml ps
curl --fail http://127.0.0.1:8787/health
```

Expected health output contains `"malware_scanner":"ready"`. Do not remove the
`clamav-db` volume on normal upgrades; it stores the current signature database.
The service intentionally publishes no port for ClamAV or Redis.

On TrueNAS, additionally:

- expose the web app only through a VPN or an authenticated, TLS-enabled reverse proxy; the application itself is not an Internet-facing identity provider
- restrict the host port with firewall rules to trusted networks
- enable TrueNAS two-factor authentication and use a non-root administrative account
- configure frequent periodic snapshots and replication for the dedicated app dataset
- set a dataset quota so oversized uploads or conversion output cannot fill the NAS
- keep SMB1 and NTLMv1 disabled and avoid sharing the application dataset

See [docs/security-hardening/implementation-plan.md](docs/security-hardening/implementation-plan.md)
for rollout, verification and rollback details.

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
docker compose -f docker/docker-compose.yml build api worker clamav
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
```

## License

See [LICENSE](LICENSE).
