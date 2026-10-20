# Stitch implementation

The visual source is Google Stitch project `9468772688105973646`, **MediaForge Self-Hosted Studio**. The newer light screen `2168953198f4469983a9487eca61080f` supplies the primary composition; its exports are `tmp/stitch/screen-0.html` and `tmp/stitch/screen-0.png`. The older dark technical alternate `43362ee042c64849a00484b75b823676` is retained in `tmp/stitch/screen-1.html` and `tmp/stitch/screen-1.png`.

The implementation keeps React 18, TypeScript, Vite 7, and plain CSS. `src/main.tsx` loads `studio.css` after the existing `styles.css` and `workshop.css`; `App.tsx` adapts the interface while preserving application handlers. The desktop layout has a 680px work column, 56px navigation, and 960px header container. Local Geist and JetBrains Mono fonts and their licenses live in `public/fonts`; `index.html` preloads the primary font.

The light reference determines geometry in both themes. Dark primary green (`#39735e`) was darkened to support white-label contrast of at least 4.5:1; light placeholders use `#667068`. Native format and quality selects retain keyboard behavior. URL previews call `/api/download/inspect`, jobs use `/api/jobs`, and existing conversion/compression APIs remain in place. The destination reads **Browser-Download**. Reference-only account, settings, and custom filesystem destination controls were omitted because their backend behavior is unavailable.

## Changes attributable to this implementation

- Adapted `apps/frontend/src/App.tsx`, `src/main.tsx`, and `index.html`.
- Added `apps/frontend/src/studio.css` and local font assets/licenses under `public/fonts`.
- Added `apps/frontend/tests/e2e/stitch.spec.ts` and its reference-image fixture/provenance.
- Updated selectors and landing-page expectations in `profile-warning.spec.ts`, `session-diagnostics.spec.ts`, `interface.spec.ts`, and `compression.spec.ts`.
- Added root `DESIGN.md`, `.impeccable/design.json`, and this implementation record.

Pre-existing working-tree changes, including conversion/compression work, `workshop.css`, API/worker files, and earlier test coverage and documentation, were preserved and are not attributed to this Stitch implementation.

## Verification

`npm run check` passed (TypeScript and production build). All 25 Playwright cases passed across the full run and a targeted rerun: 22 initially passed, three failures were corrected, and the targeted five-case rerun passed. This is not a claim that a subsequent complete 25-case run passed. No lint script is configured.

Browser tests use mocked API responses. A live backend was not running, so live media download, conversion, and compression end-to-end behavior was not verified in this task.

Review screenshots are retained at `tmp/stitch/review/desktop.png`, `tablet.png`, `mobile.png`, and `mobile-dark.png`. These temporary local artifacts support visual review and are not production assets. The media fixture is used only by tests; production previews continue to use actual inspected media.

## Polish pass — 2026-10-20

Added the reference's duration overlay and a stable fallback for unavailable preview images. Aligned footer diagnostics at intermediate widths and made the two-row navigation consistent below 760px. Added a 600px capture (`compact.png`) and regression coverage for failed thumbnails and long media titles. The full suite now passes in one run: **26/26 Playwright tests**, plus TypeScript and production build. API responses remain mocked.
