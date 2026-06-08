import React, { useEffect, useMemo, useRef, useState } from 'react'
import ProfileSelector from './ProfileSelector'
import Modal from './Modal'

type Job = {
  id: number
  type: 'download' | 'convert' | string
  status: string
  progress?: number
  current_step?: string | null
  output_path?: string | null
}

type ActiveTab = 'download' | 'convert'

const terminalStatuses = ['success', 'failed', 'cancelled', 'notfound']

function getStatusTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (['success', 'completed'].includes(normalized)) return 'success'
  if (['running', 'queued', 'started', 'waiting'].includes(normalized)) return 'active'
  if (['failed', 'error', 'cancelled', 'notfound'].includes(normalized)) return 'danger'
  return 'neutral'
}

function StatusBadge({ status }: { status?: string }) {
  const label = status || 'unknown'
  return <span className={`status-badge ${getStatusTone(label)}`}>{label}</span>
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  )
}

function fallbackDownloadName(job: Job) {
  if (!job.output_path) return `mediaforge-job-${job.id}`
  return job.output_path.split(/[\\/]/).pop() || `mediaforge-job-${job.id}`
}

function filenameFromDisposition(header: string | null) {
  if (!header) return null
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match) return decodeURIComponent(utf8Match[1])
  const plainMatch = header.match(/filename="?([^";]+)"?/i)
  return plainMatch ? plainMatch[1] : null
}

function JobDetail({
  job,
  auth,
  onDownload,
  onTerminal,
}: {
  job: Job | null
  auth: string | null
  onDownload: (job: Job) => void
  onTerminal: () => void
}) {
  const [log, setLog] = useState<string>('')
  const [status, setStatus] = useState<string>('')
  const logRef = useRef<HTMLPreElement | null>(null)

  useEffect(() => {
    if (!job?.id) return
    let mounted = true
    let lastEventId = 0
    let backoff = 500
    const maxBackoff = 30000
    let reconnectTimer: number | undefined
    let controller: AbortController | undefined
    let terminal = false
    setLog('')
    setStatus(job.status || '')

    const connect = async () => {
      controller = new AbortController()
      const hdrs: Record<string, string> = auth ? { Authorization: `Basic ${auth}` } : {}
      if (lastEventId) hdrs['Last-Event-ID'] = String(lastEventId)
      try {
        const res = await fetch(`/api/jobs/${job.id}/events`, { headers: hdrs, signal: controller.signal })
        if (!res.ok) return
        const reader = res.body!.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        backoff = 500
        while (mounted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const part of parts) {
            if (!part) continue
            const lines = part.split('\n')
            const idLine = lines.find((line) => line.startsWith('id:'))
            const dataLine = lines.find((line) => line.startsWith('data:'))
            if (idLine) {
              try {
                lastEventId = Number(idLine.replace(/^id:\s*/, ''))
              } catch (e) {
                // keep current offset
              }
            }
            if (dataLine) {
              try {
                const payload = JSON.parse(dataLine.replace(/^data:\s*/, ''))
                if (!mounted) break
                if (payload.chunk !== undefined) setLog((prev) => (prev || '') + payload.chunk)
                if (payload.status !== undefined) {
                  setStatus(payload.status)
                  if (terminalStatuses.includes(payload.status)) {
                    terminal = true
                    onTerminal()
                  }
                }
                setTimeout(() => {
                  if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
                }, 50)
              } catch (e) {
                // ignore malformed SSE payloads
              }
            }
          }
        }
      } catch (e) {
        // stream reconnects below
      }

      if (!mounted || terminal) return
      reconnectTimer = window.setTimeout(() => {
        backoff = Math.min(maxBackoff, backoff * 2)
        connect()
      }, backoff)
    }

    connect()
    return () => {
      mounted = false
      controller?.abort()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [job?.id, auth])

  if (!job) {
    return <EmptyState title="Kein Auftrag ausgewählt" text="Wähle einen Auftrag aus, um Details und Logs zu sehen." />
  }

  return (
    <section className="panel job-detail">
      <div className="panel-header compact">
        <div>
          <p className="eyebrow">Details</p>
          <h2>Auftrag #{job.id}</h2>
        </div>
        <div className="detail-actions">
          <StatusBadge status={status || job.status} />
          {job.status === 'success' && job.output_path ? (
            <button className="button primary" onClick={() => onDownload(job)}>Herunterladen</button>
          ) : null}
        </div>
      </div>
      <div className="detail-meta">
        <span>{job.type === 'convert' ? 'Konvertierung' : 'Download'}</span>
        <span>{job.current_step || (job.output_path ? fallbackDownloadName(job) : 'Wartet auf Verarbeitung')}</span>
      </div>
      <pre ref={logRef} className="log-panel">{log || 'Noch keine Logs vorhanden.'}</pre>
    </section>
  )
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [presets, setPresets] = useState<Record<string, unknown>>({})
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<ActiveTab>('download')
  const [url, setUrl] = useState('')
  const [presetSel, setPresetSel] = useState('default')
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [auth, setAuth] = useState<string | null>(null)
  const [compressionFamily, setCompressionFamily] = useState('audio')
  const [compressionProfile, setCompressionProfile] = useState('balanced')
  const [compressionLang, setCompressionLang] = useState<'de' | 'en'>('de')
  const [compressionWarning, setCompressionWarning] = useState<string | null>(null)
  const [pendingWarning, setPendingWarning] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<ActiveTab>('download')
  const [message, setMessage] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)

  const presetNames = useMemo(() => Object.keys(presets || {}), [presets])
  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedId) || null, [jobs, selectedId])
  const finishedJobs = useMemo(
    () => jobs.filter((job) => job.status === 'success' && job.output_path),
    [jobs],
  )
  const activeJobs = useMemo(
    () => jobs.filter((job) => ['queued', 'running'].includes((job.status || '').toLowerCase())).length,
    [jobs],
  )

  const loadJobs = async () => {
    if (!auth) {
      setJobs([])
      return
    }
    try {
      const r = await fetch('/api/jobs', { headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) {
        setJobs([])
        return
      }
      const d = await r.json()
      setJobs(Array.isArray(d) ? d : [])
    } catch (e) {
      setJobs([])
    }
  }

  useEffect(() => {
    fetch('/api/presets')
      .then((r) => r.json())
      .then((d) => setPresets(d))
      .catch(() => setPresets({}))
  }, [])

  useEffect(() => {
    if (presetNames.length > 0 && !presetNames.includes(presetSel)) {
      setPresetSel(presetNames[0])
    }
  }, [presetNames, presetSel])

  useEffect(() => {
    loadJobs()
  }, [auth])

  useEffect(() => {
    if (!auth) return
    const interval = window.setInterval(loadJobs, 5000)
    return () => window.clearInterval(interval)
  }, [auth])

  const login = () => {
    setAuth(btoa(`${user}:${pass}`))
    setMessage(null)
  }

  const handleAuthRequired = () => {
    setMessage('Bitte zuerst anmelden.')
  }

  const createDownloadJob = async (force = false) => {
    if (!auth) {
      handleAuthRequired()
      return
    }
    if (!url.trim()) {
      setMessage('Bitte eine Download-URL eintragen.')
      return
    }
    const body = {
      type: 'download',
      input: {
        url: url.trim(),
        preset: presetSel,
        compression_profile: compressionProfile,
        lang: compressionLang,
        mime_type: `${compressionFamily}/x-mediaforge`,
      },
    }

    try {
      setMessage(null)
      const params = new URLSearchParams({ lang: compressionLang })
      if (force) params.set('force', 'true')
      const r = await fetch(`/api/jobs?${params.toString()}`, {
        method: 'POST',
        headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (r.ok) {
        const created = await r.json()
        setUrl('')
        setPendingWarning(null)
        setMessage(`Download gestartet: Auftrag #${created.id}`)
        setSelectedId(created.id)
        loadJobs()
      } else if (r.status === 409) {
        const data = await r.json().catch(() => null)
        setPendingAction('download')
        setPendingWarning(data?.detail?.warning || data?.warning || compressionWarning || 'Quality warning')
      } else {
        setMessage('Download konnte nicht gestartet werden.')
      }
    } catch (e) {
      setMessage('Download konnte nicht gestartet werden.')
    }
  }

  const createConvertJob = async (force = false) => {
    if (!auth) {
      handleAuthRequired()
      return
    }
    if (!selectedFile) {
      setMessage('Bitte eine Datei auswählen.')
      return
    }

    const data = new FormData()
    data.set('file', selectedFile)
    data.set('preset', presetSel)
    data.set('compression_family', compressionFamily)
    data.set('compression_profile', compressionProfile)
    data.set('lang', compressionLang)

    try {
      setMessage(null)
      const params = new URLSearchParams()
      if (force) params.set('force', 'true')
      const suffix = params.toString() ? `?${params.toString()}` : ''
      const r = await fetch(`/api/jobs/convert-upload${suffix}`, {
        method: 'POST',
        headers: { Authorization: `Basic ${auth}` },
        body: data,
      })
      if (r.ok) {
        const created = await r.json()
        setSelectedFile(null)
        setPendingWarning(null)
        setMessage(`Konvertierung gestartet: Auftrag #${created.id}`)
        setSelectedId(created.id)
        loadJobs()
      } else if (r.status === 409) {
        const warning = await r.json().catch(() => null)
        setPendingAction('convert')
        setPendingWarning(warning?.detail?.warning || warning?.warning || compressionWarning || 'Quality warning')
      } else {
        setMessage('Konvertierung konnte nicht gestartet werden.')
      }
    } catch (e) {
      setMessage('Konvertierung konnte nicht gestartet werden.')
    }
  }

  const downloadJob = async (job: Job) => {
    if (!auth) {
      handleAuthRequired()
      return
    }
    try {
      const r = await fetch(`/api/jobs/${job.id}/download`, {
        headers: { Authorization: `Basic ${auth}` },
      })
      if (!r.ok) {
        setMessage('Datei ist noch nicht herunterladbar.')
        return
      }
      const blob = await r.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = filenameFromDisposition(r.headers.get('Content-Disposition')) || fallbackDownloadName(job)
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (e) {
      setMessage('Download der fertigen Datei fehlgeschlagen.')
    }
  }

  const confirmPendingWarning = () => {
    if (pendingAction === 'download') {
      createDownloadJob(true)
    } else {
      createConvertJob(true)
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup" aria-label="MediaForge">
          <span className="brand-mark">MF</span>
          <div>
            <h1>MediaForge</h1>
            <p>Medien herunterladen, konvertieren und fertige Dateien sichern.</p>
          </div>
        </div>
        <div className="auth-box">
          <input aria-label="Benutzer" placeholder="user" value={user} onChange={(e) => setUser(e.target.value)} />
          <input
            aria-label="Passwort"
            placeholder="password"
            type="password"
            value={pass}
            onChange={(e) => setPass(e.target.value)}
          />
          <button className="button secondary" onClick={login}>{auth ? 'Aktualisieren' : 'Login'}</button>
        </div>
      </header>

      <section className="main-layout">
        <div className="work-column">
          <div className="tab-bar" role="tablist" aria-label="Auftragstyp">
            <button
              className={`tab-button ${activeTab === 'download' ? 'active' : ''}`}
              role="tab"
              aria-selected={activeTab === 'download'}
              onClick={() => setActiveTab('download')}
            >
              Download
            </button>
            <button
              className={`tab-button ${activeTab === 'convert' ? 'active' : ''}`}
              role="tab"
              aria-selected={activeTab === 'convert'}
              onClick={() => setActiveTab('convert')}
            >
              Konvertieren
            </button>
          </div>

          <section className="panel work-panel">
            {activeTab === 'download' ? (
              <>
                <div className="panel-header">
                  <div>
                    <p className="eyebrow">Online-Quelle</p>
                    <h2>Download starten</h2>
                  </div>
                </div>
                <div className="form-grid download-form">
                  <label className="field wide">
                    <span>URL</span>
                    <input
                      placeholder="https://..."
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Preset</span>
                    <select value={presetSel} onChange={(e) => setPresetSel(e.target.value)}>
                      {(presetNames.length ? presetNames : ['default']).map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <ProfileSelector
                  family={compressionFamily}
                  profile={compressionProfile}
                  lang={compressionLang}
                  warning={compressionWarning}
                  onFamilyChange={setCompressionFamily}
                  onProfileChange={setCompressionProfile}
                  onLangChange={setCompressionLang}
                  onWarningChange={setCompressionWarning}
                />
                <div className="panel-footer">
                  <button className="button primary" data-testid="create-job" onClick={() => createDownloadJob()}>
                    Download starten
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="panel-header">
                  <div>
                    <p className="eyebrow">Lokale Datei</p>
                    <h2>Datei konvertieren</h2>
                  </div>
                </div>
                <div className="upload-area">
                  <input
                    id="file-upload"
                    type="file"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  />
                  <label htmlFor="file-upload">
                    <strong>{selectedFile ? selectedFile.name : 'Datei auswählen'}</strong>
                    <span>
                      {selectedFile
                        ? `${Math.max(1, Math.round(selectedFile.size / 1024))} KB bereit zur Konvertierung`
                        : 'Audio, Video oder Bild vom Computer hochladen'}
                    </span>
                  </label>
                </div>
                <div className="form-grid single-select">
                  <label className="field">
                    <span>Preset</span>
                    <select value={presetSel} onChange={(e) => setPresetSel(e.target.value)}>
                      {(presetNames.length ? presetNames : ['default']).map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <ProfileSelector
                  family={compressionFamily}
                  profile={compressionProfile}
                  lang={compressionLang}
                  warning={compressionWarning}
                  onFamilyChange={setCompressionFamily}
                  onProfileChange={setCompressionProfile}
                  onLangChange={setCompressionLang}
                  onWarningChange={setCompressionWarning}
                />
                <div className="panel-footer">
                  <button className="button primary" onClick={() => createConvertJob()}>
                    Konvertierung starten
                  </button>
                </div>
              </>
            )}
            {message ? <div className="message">{message}</div> : null}
          </section>

          <JobDetail job={selectedJob} auth={auth} onDownload={downloadJob} onTerminal={loadJobs} />
        </div>

        <aside className="side-column">
          <section className="panel queue-panel">
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">Aufträge</p>
                <h2>{jobs.length} insgesamt</h2>
              </div>
              <button className="button ghost" onClick={loadJobs}>Aktualisieren</button>
            </div>
            {!auth ? (
              <EmptyState title="Login erforderlich" text="Melde dich an, um Aufträge zu erstellen und Dateien herunterzuladen." />
            ) : jobs.length === 0 ? (
              <EmptyState title="Noch keine Aufträge" text="Starte einen Download oder lade eine Datei zur Konvertierung hoch." />
            ) : (
              <div className="item-list">
                {jobs.map((job) => (
                  <button
                    key={job.id}
                    className={`list-item ${selectedId === job.id ? 'selected' : ''}`}
                    onClick={() => setSelectedId(job.id)}
                  >
                    <span className="item-main">
                      <strong>#{job.id} {job.type === 'convert' ? 'Konvertierung' : 'Download'}</strong>
                      <small>{job.current_step || (job.output_path ? fallbackDownloadName(job) : 'Wartet')}</small>
                    </span>
                    <StatusBadge status={job.status} />
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="panel downloads-panel">
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">Fertig</p>
                <h2>Downloads</h2>
              </div>
              <span className="count-label">{finishedJobs.length}</span>
            </div>
            {finishedJobs.length === 0 ? (
              <EmptyState title="Keine fertigen Dateien" text={`${activeJobs} Auftrag(e) laufen oder warten aktuell.`} />
            ) : (
              <div className="download-list">
                {finishedJobs.map((job) => (
                  <div className="download-row" key={job.id}>
                    <span>
                      <strong>{fallbackDownloadName(job)}</strong>
                      <small>Auftrag #{job.id}</small>
                    </span>
                    <button className="button secondary" onClick={() => downloadJob(job)}>Download</button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </section>

      {pendingWarning ? (
        <Modal
          title={compressionLang === 'de' ? 'Qualitätswarnung' : 'Quality warning'}
          onClose={() => setPendingWarning(null)}
          onConfirm={confirmPendingWarning}
          cancelLabel={compressionLang === 'de' ? 'Abbrechen' : 'Cancel'}
          confirmLabel={compressionLang === 'de' ? 'Trotzdem starten' : 'Start anyway'}
        >
          <p>{compressionLang === 'de' ? 'Das gewählte Profil kann Qualitätsverluste verursachen:' : 'The selected profile may cause quality loss:'}</p>
          <p><strong>{pendingWarning}</strong></p>
          <p>{compressionLang === 'de' ? 'Möchtest du trotzdem fortfahren?' : 'Do you want to continue?'}</p>
        </Modal>
      ) : null}
    </main>
  )
}

export default App
