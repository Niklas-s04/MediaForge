import React, { useEffect, useMemo, useRef, useState } from 'react'
import ProfileSelector from './ProfileSelector'
import Modal from './Modal'

type Job = {
  id: number
  type: string
  status: string
  progress?: number
  current_step?: string | null
  output_path?: string | null
}

type Flow = {
  id: number
  name: string
  description?: string | null
  steps?: Array<{ action?: string; input?: Record<string, unknown> }>
  enabled?: boolean
  last_run_triggered?: number
}

type FlowRun = {
  id: number
  flow_id: number
  status: string
  job_ids?: number[]
  started_at?: string | null
  finished_at?: string | null
}

const terminalJobStatuses = ['success', 'failed', 'cancelled', 'notfound']
const terminalRunStatuses = ['completed', 'failed', 'cancelled', 'notfound']

function getStatusTone(status?: string) {
  const normalized = (status || '').toLowerCase()
  if (['ok', 'success', 'completed', 'enabled'].includes(normalized)) return 'success'
  if (['running', 'queued', 'started', 'unknown'].includes(normalized)) return 'active'
  if (['failed', 'error', 'cancelled', 'disabled', 'notfound'].includes(normalized)) return 'danger'
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

function JobDetail({ id, auth }: { id: number | null; auth: string | null }) {
  const [log, setLog] = useState<string>('')
  const [status, setStatus] = useState<string>('')
  const logRef = useRef<HTMLPreElement | null>(null)

  useEffect(() => {
    if (!id) return
    let mounted = true
    let lastEventId = 0
    let backoff = 500
    const maxBackoff = 30000
    let reconnectTimer: number | undefined
    let controller: AbortController | undefined
    let terminal = false
    setLog('')
    setStatus('')

    const connect = async () => {
      controller = new AbortController()
      const hdrs: Record<string, string> = auth ? { Authorization: `Basic ${auth}` } : {}
      if (lastEventId) hdrs['Last-Event-ID'] = String(lastEventId)
      try {
        const res = await fetch(`/api/jobs/${id}/events`, { headers: hdrs, signal: controller.signal })
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
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find((l) => l.startsWith('id:'))
            const dataLine = lines.find((l) => l.startsWith('data:'))
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
                if (payload.status !== undefined) setStatus(payload.status)
                if (terminalJobStatuses.includes(payload.status)) terminal = true
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
  }, [id, auth])

  if (!id) {
    return <EmptyState title="Kein Job ausgewahlt" text="Wahle links einen Job aus, um Live-Logs zu sehen." />
  }

  return (
    <section className="panel detail-panel">
      <div className="panel-header compact">
        <div>
          <p className="eyebrow">Live-Log</p>
          <h2>Job #{id}</h2>
        </div>
        <StatusBadge status={status || 'waiting'} />
      </div>
      <pre ref={logRef} className="log-panel">{log || 'Noch keine Logs vorhanden.'}</pre>
    </section>
  )
}

function App() {
  const [health, setHealth] = useState<string>('unknown')
  const [jobs, setJobs] = useState<Job[]>([])
  const [presets, setPresets] = useState<Record<string, unknown>>({})
  const [selected, setSelected] = useState<number | null>(null)
  const [url, setUrl] = useState<string>('')
  const [presetSel, setPresetSel] = useState<string>('default')
  const [user, setUser] = useState<string>('')
  const [pass, setPass] = useState<string>('')
  const [auth, setAuth] = useState<string | null>(null)
  const [compressionFamily, setCompressionFamily] = useState<string>('audio')
  const [compressionProfile, setCompressionProfile] = useState<string>('balanced')
  const [compressionLang, setCompressionLang] = useState<'de' | 'en'>('de')
  const [compressionWarning, setCompressionWarning] = useState<string | null>(null)
  const [pendingWarning, setPendingWarning] = useState<string | null>(null)
  const [jobMessage, setJobMessage] = useState<string | null>(null)
  const [flowMessage, setFlowMessage] = useState<string | null>(null)

  const [flows, setFlows] = useState<Flow[]>([])
  const [flowName, setFlowName] = useState('')
  const [flowUrl, setFlowUrl] = useState('')
  const [selectedFlow, setSelectedFlow] = useState<Flow | null>(null)
  const [flowLog, setFlowLog] = useState<string>('')
  const flowLogRef = useRef<HTMLPreElement | null>(null)
  const [runs, setRuns] = useState<FlowRun[]>([])
  const [selectedRun, setSelectedRun] = useState<FlowRun | null>(null)
  const [runLog, setRunLog] = useState<string>('')
  const runLogRef = useRef<HTMLPreElement | null>(null)

  const presetNames = useMemo(() => Object.keys(presets || {}), [presets])
  const activeJobs = useMemo(
    () => jobs.filter((job) => ['queued', 'running'].includes((job.status || '').toLowerCase())).length,
    [jobs],
  )

  const loadJobs = async () => {
    try {
      const h: Record<string, string> = auth ? { Authorization: `Basic ${auth}` } : {}
      const r = await fetch('/api/jobs', { headers: h })
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

  const loadFlows = async () => {
    if (!auth) {
      setFlows([])
      return
    }
    try {
      const r = await fetch('/api/flows', { headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) {
        setFlows([])
        return
      }
      const d = await r.json()
      setFlows(Array.isArray(d) ? d : [])
    } catch (e) {
      setFlows([])
    }
  }

  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then((d) => setHealth(d.status))
      .catch(() => setHealth('error'))
  }, [])

  useEffect(() => {
    loadJobs()
  }, [auth])

  useEffect(() => {
    fetch('/api/presets')
      .then((r) => r.json())
      .then((d) => setPresets(d))
      .catch(() => setPresets({}))
  }, [])

  useEffect(() => {
    loadFlows()
  }, [auth])

  useEffect(() => {
    if (presetNames.length > 0 && !presetNames.includes(presetSel)) {
      setPresetSel(presetNames[0])
    }
  }, [presetNames, presetSel])

  useEffect(() => {
    if (!selectedFlow || !auth) return
    let mounted = true
    setFlowLog('')
    let lastEventId = 0
    let backoff = 500
    const maxBackoff = 30000
    let reconnectTimer: number | undefined
    let controller: AbortController | undefined
    let terminal = false

    const connect = async () => {
      controller = new AbortController()
      const hdrs: Record<string, string> = { Authorization: `Basic ${auth}` }
      if (lastEventId) hdrs['Last-Event-ID'] = String(lastEventId)
      try {
        const res = await fetch(`/api/flows/${selectedFlow.id}/events`, { headers: hdrs, signal: controller.signal })
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
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find((l) => l.startsWith('id:'))
            const dataLine = lines.find((l) => l.startsWith('data:'))
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
                if (payload.chunk) setFlowLog((prev) => (prev || '') + payload.chunk)
                if (['disabled', 'notfound', 'error'].includes(payload.status)) terminal = true
                if (
                  typeof payload.chunk === 'string' &&
                  (payload.chunk.includes('completed') ||
                    payload.chunk.includes('failed') ||
                    payload.chunk.includes('unexpected error'))
                ) {
                  terminal = true
                }
                setTimeout(() => {
                  if (flowLogRef.current) flowLogRef.current.scrollTop = flowLogRef.current.scrollHeight
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
  }, [selectedFlow?.id, auth])

  useEffect(() => {
    if (!selectedRun || !auth) return
    let mounted = true
    const interval = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/runs/${selectedRun.id}`, { headers: { Authorization: `Basic ${auth}` } })
        if (!r.ok) return
        const d = await r.json()
        if (!mounted) return
        setSelectedRun(d)
      } catch (e) {
        // keep last visible run state
      }
    }, 2000)
    return () => {
      mounted = false
      window.clearInterval(interval)
    }
  }, [selectedRun?.id, auth])

  useEffect(() => {
    if (!selectedRun || !auth) return
    let mounted = true
    setRunLog('')
    let lastEventId = 0
    let backoff = 500
    const maxBackoff = 30000
    let reconnectTimer: number | undefined
    let controller: AbortController | undefined
    let terminal = false

    const connect = async () => {
      controller = new AbortController()
      const hdrs: Record<string, string> = { Authorization: `Basic ${auth}` }
      if (lastEventId) hdrs['Last-Event-ID'] = String(lastEventId)
      try {
        const res = await fetch(`/api/runs/${selectedRun.id}/events`, { headers: hdrs, signal: controller.signal })
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
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find((l) => l.startsWith('id:'))
            const dataLine = lines.find((l) => l.startsWith('data:'))
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
                if (payload.run_log) setRunLog((prev) => (prev || '') + payload.run_log)
                if (terminalRunStatuses.includes(payload.status)) terminal = true
                setTimeout(() => {
                  if (runLogRef.current) runLogRef.current.scrollTop = runLogRef.current.scrollHeight
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
  }, [selectedRun?.id, auth])

  const login = () => {
    const token = btoa(`${user}:${pass}`)
    setAuth(token)
    setJobMessage(null)
    setFlowMessage(null)
  }

  const createJob = async (force = false) => {
    if (!url.trim()) {
      setJobMessage('Bitte eine Download-URL eintragen.')
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
      setJobMessage(null)
      const h: Record<string, string> = { 'Content-Type': 'application/json' }
      if (auth) h.Authorization = `Basic ${auth}`
      const params = new URLSearchParams({ lang: compressionLang })
      if (force) params.set('force', 'true')
      const r = await fetch(`/api/jobs?${params.toString()}`, { method: 'POST', headers: h, body: JSON.stringify(body) })
      if (r.ok) {
        const created = await r.json()
        setUrl('')
        setPendingWarning(null)
        setJobMessage(`Job created: ${created.id}`)
        if (created.id) setSelected(created.id)
        loadJobs()
      } else if (r.status === 409) {
        const data = await r.json().catch(() => null)
        const warning = data?.detail?.warning || data?.warning || compressionWarning || 'Quality warning'
        setPendingWarning(warning)
      } else {
        const txt = await r.text().catch(() => '')
        setJobMessage(`Job konnte nicht erstellt werden${txt ? `: ${txt}` : ''}`)
      }
    } catch (e) {
      setJobMessage('Job-Erstellung fehlgeschlagen.')
    }
  }

  const createFlow = async () => {
    if (!auth) {
      setFlowMessage('Bitte zuerst anmelden.')
      return
    }
    if (!flowName.trim() || !flowUrl.trim()) {
      setFlowMessage('Name und Download-URL werden benotigt.')
      return
    }
    const body = {
      name: flowName.trim(),
      steps: [
        {
          action: 'download',
          input: {
            url: flowUrl.trim(),
            preset: presetSel,
            compression_profile: compressionProfile,
            lang: compressionLang,
            mime_type: `${compressionFamily}/x-mediaforge`,
          },
        },
      ],
    }
    try {
      setFlowMessage(null)
      const r = await fetch('/api/flows', {
        method: 'POST',
        headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        setFlowMessage('Flow konnte nicht erstellt werden.')
        return
      }
      const f = await r.json()
      setFlowName('')
      setFlowUrl('')
      setFlows((prev) => [f, ...prev])
      setFlowMessage(`Flow erstellt: ${f.name}`)
    } catch (e) {
      setFlowMessage('Flow-Erstellung fehlgeschlagen.')
    }
  }

  const runFlow = async (flowId: number) => {
    if (!auth) {
      setFlowMessage('Bitte zuerst anmelden.')
      return
    }
    try {
      const r = await fetch(`/api/flows/${flowId}/run`, { method: 'POST', headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) {
        setFlowMessage('Flow konnte nicht gestartet werden.')
        return
      }
      const data = await r.json()
      setFlows((prev) => prev.map((f) => (f.id === flowId ? { ...f, last_run_triggered: Date.now() } : f)))
      setFlowMessage(`Flow gestartet: Run #${data.run_id}`)
      if (data.run_id) {
        setSelectedRun({ id: data.run_id, flow_id: data.flow_id, status: 'running' })
        loadRuns(flowId)
      }
    } catch (e) {
      setFlowMessage('Flow-Start fehlgeschlagen.')
    }
  }

  const loadRuns = async (flowId: number) => {
    if (!auth) return
    try {
      const r = await fetch(`/api/flows/${flowId}/runs`, { headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) {
        setRuns([])
        return
      }
      const d = await r.json()
      setRuns(Array.isArray(d) ? d : [])
    } catch (e) {
      setRuns([])
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup" aria-label="MediaForge">
          <span className="brand-mark">MF</span>
          <div>
            <h1>MediaForge</h1>
            <p>Downloads, Komprimierung und wiederholbare Medien-Flows</p>
          </div>
        </div>
        <div className="topbar-actions">
          <div className="health-pill">
            <span className={`health-dot ${getStatusTone(health)}`} />
            API {health}
          </div>
          <div className="auth-box">
            <input
              aria-label="Benutzer"
              placeholder="user"
              value={user}
              onChange={(e) => setUser(e.target.value)}
            />
            <input
              aria-label="Passwort"
              placeholder="password"
              type="password"
              value={pass}
              onChange={(e) => setPass(e.target.value)}
            />
            <button className="button secondary" onClick={login}>Login</button>
          </div>
        </div>
      </header>

      <section className="stats-grid" aria-label="Ubersicht">
        <div className="metric-card">
          <span>Jobs</span>
          <strong>{jobs.length}</strong>
          <small>{activeJobs} aktiv</small>
        </div>
        <div className="metric-card">
          <span>Flows</span>
          <strong>{flows.length}</strong>
          <small>{auth ? 'Synchronisiert' : 'Login erforderlich'}</small>
        </div>
        <div className="metric-card">
          <span>Preset</span>
          <strong>{presetSel}</strong>
          <small>{presetNames.length || 0} verfugbar</small>
        </div>
      </section>

      <div className="workspace-grid">
        <section className="panel create-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Neuer Auftrag</p>
              <h2>Job erstellen</h2>
            </div>
            <button className="button ghost" onClick={loadJobs}>Jobs aktualisieren</button>
          </div>

          <div className="input-line">
            <input
              className="url-input"
              placeholder="url"
              aria-label="Download URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <select value={presetSel} onChange={(e) => setPresetSel(e.target.value)} aria-label="Preset">
              {(presetNames.length ? presetNames : ['default']).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button className="button primary" data-testid="create-job" onClick={() => createJob()}>Create Job</button>
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
          {jobMessage ? <div className="message">{jobMessage}</div> : null}
        </section>

        <section className="panel list-panel">
          <div className="panel-header compact">
            <div>
              <p className="eyebrow">Warteschlange</p>
              <h2>Jobs</h2>
            </div>
            <span className="count-label">{jobs.length}</span>
          </div>
          {jobs.length === 0 ? (
            <EmptyState title="Noch keine Jobs" text="Erstelle einen Job, danach erscheint er hier." />
          ) : (
            <div className="item-list">
              {jobs.map((job) => (
                <button
                  className={`list-item ${selected === job.id ? 'selected' : ''}`}
                  key={job.id}
                  onClick={() => setSelected(job.id)}
                >
                  <span className="item-main">
                    <strong>#{job.id} {job.type}</strong>
                    <small>{job.output_path || job.current_step || 'Wartet auf Verarbeitung'}</small>
                  </span>
                  <StatusBadge status={job.status} />
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="detail-grid">
        <JobDetail id={selected} auth={auth} />

        <section className="panel flow-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Automatisierung</p>
              <h2>Flows</h2>
            </div>
            <button className="button ghost" onClick={loadFlows}>Flows aktualisieren</button>
          </div>

          <div className="flow-create">
            <input placeholder="Flow name" value={flowName} onChange={(e) => setFlowName(e.target.value)} />
            <input placeholder="Download URL" value={flowUrl} onChange={(e) => setFlowUrl(e.target.value)} />
            <button className="button primary" onClick={createFlow}>Create Flow</button>
          </div>
          {flowMessage ? <div className="message">{flowMessage}</div> : null}

          {flows.length === 0 ? (
            <EmptyState title="Noch keine Flows" text="Speichere wiederkehrende Downloads als Flow." />
          ) : (
            <div className="flow-list">
              {flows.map((flow) => (
                <article className={`flow-card ${selectedFlow?.id === flow.id ? 'selected' : ''}`} key={flow.id}>
                  <div>
                    <h3>{flow.name}</h3>
                    <p>{flow.description || `${flow.steps?.length || 0} Schritt(e)`}</p>
                  </div>
                  <div className="card-actions">
                    <button
                      className="button secondary"
                      onClick={() => {
                        setSelectedFlow(flow)
                        loadRuns(flow.id)
                      }}
                    >
                      Details
                    </button>
                    <button className="button primary" onClick={() => runFlow(flow.id)}>Run</button>
                  </div>
                </article>
              ))}
            </div>
          )}

          {selectedFlow ? (
            <div className="flow-detail">
              <div className="panel-header compact">
                <div>
                  <p className="eyebrow">Flow-Details</p>
                  <h3>{selectedFlow.name}</h3>
                </div>
                <button className="button ghost" onClick={() => setSelectedFlow(null)}>Schliessen</button>
              </div>

              <div className="steps-list">
                {(Array.isArray(selectedFlow.steps) ? selectedFlow.steps : []).map((step, i) => (
                  <div className="step-row" key={`${step.action || 'step'}-${i}`}>
                    <span>{i + 1}</span>
                    <strong>{step.action || 'Aktion'}</strong>
                    <small>{String(step.input?.url || step.input?.preset || '')}</small>
                  </div>
                ))}
              </div>

              <div className="split-logs">
                <div>
                  <div className="mini-header">
                    <strong>Live Flow Log</strong>
                    <button className="button secondary" onClick={() => runFlow(selectedFlow.id)}>Run Flow</button>
                  </div>
                  <pre ref={flowLogRef} className="log-panel small">{flowLog || 'Noch keine Flow-Logs vorhanden.'}</pre>
                </div>
                <div>
                  <div className="mini-header">
                    <strong>Runs</strong>
                    <button className="button secondary" onClick={() => loadRuns(selectedFlow.id)}>Anzeigen</button>
                  </div>
                  {runs.length === 0 ? (
                    <EmptyState title="Keine Runs" text="Starte den Flow, um Runs zu sehen." />
                  ) : (
                    <div className="run-list">
                      {runs.map((run) => (
                        <button className="run-row" key={run.id} onClick={() => setSelectedRun(run)}>
                          <span>
                            <strong>Run #{run.id}</strong>
                            <small>{run.started_at ? new Date(run.started_at).toLocaleString() : 'ohne Startzeit'}</small>
                          </span>
                          <StatusBadge status={run.status} />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {selectedRun ? (
                <div className="run-detail">
                  <div className="mini-header">
                    <strong>Run #{selectedRun.id}</strong>
                    <StatusBadge status={selectedRun.status} />
                  </div>
                  <div className="job-chip-row">
                    {(selectedRun.job_ids || []).length === 0 ? (
                      <span className="muted">Keine verknupften Jobs</span>
                    ) : (
                      (selectedRun.job_ids || []).map((jobId) => (
                        <button className="job-chip" key={jobId} onClick={() => setSelected(jobId)}>Job #{jobId}</button>
                      ))
                    )}
                  </div>
                  <pre ref={runLogRef} className="log-panel small">{runLog || 'Noch kein Run-Log vorhanden.'}</pre>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      {pendingWarning ? (
        <Modal
          title={compressionLang === 'de' ? 'Qualitatswarnung' : 'Quality warning'}
          onClose={() => setPendingWarning(null)}
          onConfirm={() => createJob(true)}
          cancelLabel={compressionLang === 'de' ? 'Abbrechen' : 'Cancel'}
          confirmLabel={compressionLang === 'de' ? 'Bestatigen' : 'Confirm'}
        >
          <p>{compressionLang === 'de' ? 'Das gewahlte Profil kann Qualitatsverluste verursachen:' : 'The selected profile may cause quality loss:'}</p>
          <p><strong>{pendingWarning}</strong></p>
          <p>{compressionLang === 'de' ? 'Mochtest du trotzdem fortfahren?' : 'Do you want to continue?'}</p>
        </Modal>
      ) : null}
    </main>
  )
}

export default App
