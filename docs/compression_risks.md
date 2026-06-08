## Komprimierung — Risiken & Validierung

Kurz: Zusammenfassung der wichtigsten Risiken, Validierungs‑ und Testschritte für die neu implementierte Komprimierungs‑Decision-Logik.

Ziel
- Definieren, wie Dateien in Familien (`audio`, `video`, `image`, `archive`) eingeteilt werden und welche Profile (`balanced`, `small`) anzuwenden sind.

Wesentliche Risiken
- Qualitätsverlust: aggressive Profile können Sprach-/Musikqualität stark beeinträchtigen. Validierung mit Hörstichproben notwendig.
- Metadata-Loss: `strip_metadata: true` entfernt möglicherweise Copyright/Tags — prüfen, ob nötig.
- Dependency-Risiko: `ffmpeg` und `yt-dlp` müssen in der Laufzeitumgebung vorhanden sein. Fehlende Binaries brechen Jobs.
- Performance/Resourcen: transkodieren kann CPU/IO-lastig sein — Rate-Limits und Concurrency begrenzen.
- Sicherheit: Eingaben (URLs, Dateinamen) dürfen nicht zu SSRF/Path-Traversal führen. Worker läuft in isolierter Umgebung.
- Datenspeicherung: temporäre Dateien können sensible Daten enthalten — Cleanup sicherstellen.

Validierung / Tests
- Unit-Tests für `compression_goals.py` (MIME/Extension Resolver, Profile-Lookup) — vorhanden.
- Worker-Unit-Tests mit Mock der Subprozesse — prüft DB-Updates und Logging — vorhanden.
- Manuelle Integrationstests: kleine Sample-Dateien durch alle Profile laufen lassen und Output-Größen + Subjektive Qualität prüfen.
- Automatisierte QoE-Checks: RMS/PSNR/Loudness-Metriken für Audio/Video als optionale Validierung.

Mitigations
- Default-Policy: Fallback-Family `archive` für unbekannte Typen (verlustfrei archivieren).
- Konfigurierbare Presets: erlauben konservative Defaults in Produktivumgebungen.
- Resource-Controls: Worker concurrency in Celery/Container limits setzen; Transcoding-Timeouts.
- Secure Defaults: keine Remote-Execution, Pfade normalisieren, keine Shell-Interpolationen.

Runtime-Anforderungen
- System: `ffmpeg` in PATH oder im Container-Image.
- Downloader: `yt-dlp` verfügbar wenn Remote-Downloads verwendet werden.
- DB: Arbeitsverzeichnis `/data` beschreibbar; Temp-Ordner werden aufgeräumt.

Offene TODOs
- Add automated subjective test harness (listen/compare) für Audio profiles.
- Expose profiles via UI with warnings about quality trade-offs.
- Add telemetry (sampled) for output sizes per profile to refine defaults.

Kurz: Bei Rückfragen kann ich das Dokument in `README.md` zusammenfassen oder Beispiel-Skripte zum Durchtesten hinzufügen.
