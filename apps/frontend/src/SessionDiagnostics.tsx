import React, { useState, useSyncExternalStore } from 'react'
import { getDiagnostics, subscribeDiagnostics } from './diagnostics'

export default function SessionDiagnostics() {
  const log = useSyncExternalStore(subscribeDiagnostics, getDiagnostics)
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(false)
  const download = () => {
    const url = URL.createObjectURL(new Blob([log], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `mediaforge-diagnose-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <details className="session-diagnostics" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Diagnose dieser Sitzung</summary>
      <p>Anfragen, Uploads und Fehler seit Sitzungsstart – auch ohne Auftrag. Nur lokal in diesem Browser-Tab gespeichert, bei Neuladen erhalten. Keine globalen Server- oder fremden Auftragslogs.</p>
      <div className="history-actions">
        <button type="button" className="button secondary" onClick={download}>Protokoll herunterladen</button>
        <button type="button" className="button ghost" onClick={async () => {
          try { await navigator.clipboard.writeText(log); setNotice('Protokoll kopiert.') }
          catch { setNotice('Kopieren nicht verfügbar. Bitte Protokoll herunterladen oder Text markieren.') }
        }}>Protokoll kopieren</button>
      </div>
      <p role="status">{notice}</p>
      {open ? <pre className="log-panel" tabIndex={0}>{log}</pre> : null}
    </details>
  )
}
