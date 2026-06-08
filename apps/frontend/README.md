# Frontend (React + Vite)

Dieser Ordner enthält das Frontend der Anwendung.

## Schnellstart

```bash
cd apps/frontend
npm install
npm run dev
```

Die UI zeigt beim Wechsel eines Komprimierungsprofils eine kurze Warnung, falls das Profil Qualitäts- oder Metadaten-Risiken hat. Die Warnungen kommen aus der API (`/api/compression/profile`).

Das API-Backend ist standardmäßig unter `http://localhost:8787` erreichbar.

## E2E Tests (Playwright)

Installiere Playwright und Browser für CI oder lokal:

```bash
cd apps/frontend
npm install
npx playwright install --with-deps
```

Tests ausführen:

```bash
npm run test:e2e
```

Die Tests starten den Dev-Server automatisch (via `playwright.config.ts`) und mocken API-Antworten, damit sie reproduzierbar laufen.
