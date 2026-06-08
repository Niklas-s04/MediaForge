# Frontend (React + Vite)

Dieser Ordner enthält das Frontend der Anwendung. Für ein schnelles MVP wird empfohlen, ein Vite + React + TypeScript Template zu verwenden.

Erstellung eines Vite-Projekts (einmalig):

```bash
cd apps/frontend
npm create vite@latest . -- --template react-ts
npm install
npm run dev
```

Schnellstart (Dev)

```bash
cd apps/frontend
npm install
npm run dev
```

Die UI zeigt beim Wechsel eines Komprimierungsprofils eine kurze Warnung, falls das Profil Qualitäts- oder Metadaten-Risiken hat. Die Warnungen kommen aus der API (`/api/compression/profile`).

Das API-Backend ist standardmäßig unter `http://localhost:8787` erreichbar.

Hinweis: Job-Erstellung erfordert Authentifizierung (Basic). Das Frontend zeigt vor dem Absenden eine Warn‑Bestätigung, wenn das gewählte Profil Risiken hat.

E2E Tests (Playwright)

Installiere Playwright und Browser für CI / lokal:

```bash
cd apps/frontend
npm install
npx playwright install --with-deps
```

Tests ausführen:

```bash
npm run test:e2e
```

Die Tests starten den Dev‑Server automatisch (via `playwright.config.ts`) und mocken API‑Antworten, damit sie reproduzierbar laufen.
