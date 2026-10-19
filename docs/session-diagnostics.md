# Sitzungsdiagnose

Am Seitenende befindet sich der standardmäßig geschlossene Bereich **Diagnose dieser Sitzung**.
Das Protokoll lässt sich anzeigen, kopieren und als Textdatei herunterladen, auch wenn noch kein Auftrag angelegt wurde.

Ab Laden der Anwendung werden API-Anfragen mit Status und Dauer, Uploads, Fehlerantworten,
Meldungen der Oberfläche und unbehandelte Browserfehler erfasst. Warnungen und Fehler aus
der Bearbeitung einer API-Anfrage kommen ausschließlich mit deren Antwort zurück. Dazu
gehört auch die technische Ursache einer fehlgeschlagenen Verarbeitung des Upload-Bodys.
Die Serverdiagnose ist pro Antwort begrenzt; gekürzte Angaben werden gekennzeichnet.

Das Protokoll bleibt in `sessionStorage` dieses Browser-Tabs und übersteht Neuladen.
Nach Schließen des Tabs endet die Sitzung (Browser können Tabs mitsamt Sitzung wiederherstellen).
Andere Geräte erhalten diese Daten nicht; es gibt keinen Endpunkt zum Abruf von Sitzungsprotokollen.
Die Zuordnung benötigt weder eine IP-Adresse noch einen Geräte-Fingerabdruck.
Bei gesperrtem oder vollem Browserspeicher läuft die Aufzeichnung im Arbeitsspeicher weiter;
der Diagnosebereich weist dann auf den nötigen Download vor dem Neuladen hin.

Die Diagnose umfasst keine globalen Serverlogs und keine im Hintergrund laufenden Workerlogs.
Bestehende Auftragslogs und deren bisherige Zugriffsmöglichkeiten sind davon unabhängig.
Vor Einführung der Funktion aufgetretene Fehler lassen sich damit nicht rückwirkend erfassen.
