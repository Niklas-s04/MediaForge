const storageKey = 'mediaforge-session-diagnostics'
let entries: string[] = []
let storageWarning = ''
try {
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '[]')
  if (Array.isArray(saved)) entries = saved.filter((line): line is string => typeof line === 'string')
} catch { storageWarning = 'Browserspeicher nicht verfügbar; Protokoll bleibt nur bis zum Neuladen erhalten.' }

const listeners = new Set<() => void>()
export const subscribeDiagnostics = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
export const getDiagnostics = () => `${storageWarning ? storageWarning + '\n' : ''}${entries.join('\n')}`

export function recordDiagnostic(message: string) {
  entries.push(`${new Date().toISOString()} ${message}`)
  try { sessionStorage.setItem(storageKey, JSON.stringify(entries)) }
  catch { storageWarning = 'Browserspeicher voll oder nicht verfügbar; neue Einträge bleiben nur bis zum Neuladen erhalten. Bitte Protokoll herunterladen.' }
  listeners.forEach((listener) => listener())
}

export function recordServerDiagnostic(encoded: string | null) {
  if (!encoded) return
  try { recordDiagnostic(`Server: ${JSON.parse(atob(encoded))}`) }
  catch { recordDiagnostic('Serverdiagnose konnte nicht gelesen werden.') }
}

// Keep diagnostics on this tab: no upload, shared server store or device identifier.
recordDiagnostic(entries.length ? 'Seite neu geladen' : 'Sitzung gestartet')
window.addEventListener('error', (event) => recordDiagnostic(`Browserfehler: ${event.message || 'Ressource konnte nicht geladen werden'}`), true)
window.addEventListener('unhandledrejection', (event) => recordDiagnostic(`Unbehandelter Fehler: ${String(event.reason)}`))

export async function diagnosticFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
  const label = `${init?.method || (input instanceof Request ? input.method : 'GET')} ${url.pathname}`
  const started = performance.now()
  recordDiagnostic(`${label} gestartet`)
  try {
    const response = await fetch(input, init)
    recordDiagnostic(`${label}: HTTP ${response.status} (${Math.round(performance.now() - started)} ms)`)
    recordServerDiagnostic(response.headers.get('X-MediaForge-Diagnostic'))
    if (!response.ok) {
      // Do not consume the application's response or buffer downloads / event streams.
      void response.clone().text().then((body) => recordDiagnostic(`${label}: ${body.slice(0, 16000)}`))
        .catch(() => recordDiagnostic(`${label}: Fehlerantwort konnte nicht gelesen werden`))
    }
    return response
  } catch (error) {
    recordDiagnostic(`${label}: ${String(error)} (${Math.round(performance.now() - started)} ms)`)
    throw error
  }
}
