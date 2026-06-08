import React, { useEffect, useState, useRef } from 'react'
import ProfileSelector from './ProfileSelector'
import Modal from './Modal'

function JobDetail({ id, auth }: { id: number | null, auth: string | null }) {
  const [log, setLog] = useState<string>('')
  const [status, setStatus] = useState<string>('')
  const logRef = React.useRef<HTMLPreElement | null>(null)

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
          let parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find(l => l.startsWith('id:'))
            const dataLine = lines.find(l => l.startsWith('data:'))
            if (idLine) {
              try { lastEventId = Number(idLine.replace(/^id:\s*/, '')) } catch (e) {}
            }
            if (dataLine) {
              try {
                const payload = JSON.parse(dataLine.replace(/^data:\s*/, ''))
                if (!mounted) break
                if (payload.chunk !== undefined) setLog((prev) => (prev || '') + payload.chunk)
                if (payload.status !== undefined) setStatus(payload.status)
                if (['success', 'failed', 'cancelled', 'notfound'].includes(payload.status)) terminal = true
                setTimeout(() => {
                  if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
                }, 50)
              } catch (e) {
                // ignore parse errors
              }
            }
          }
        }
      } catch (e) {
        // ignore
      }

      if (!mounted || terminal) return
      reconnectTimer = window.setTimeout(() => { backoff = Math.min(maxBackoff, backoff * 2); connect() }, backoff)
    }

    connect()
    return () => {
      mounted = false
      controller?.abort()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [id, auth])

  if (!id) return null
  return (
    <div style={{ marginTop: 12 }}>
      <h3>Job {id} — {status}</h3>
      <pre ref={logRef} style={{ background: '#111', color: '#0f0', padding: 12, height: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{log || 'No logs yet'}</pre>
    </div>
  )
}

function App() {
  const [health, setHealth] = useState<string>('unknown')
  const [jobs, setJobs] = useState<any[]>([])
  const [presets, setPresets] = useState<Record<string, any>>({})
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

  // Flow UI state
  const [flows, setFlows] = useState<any[]>([])
  const [flowName, setFlowName] = useState('')
  const [flowUrl, setFlowUrl] = useState('')
  const [selectedFlow, setSelectedFlow] = useState<any | null>(null)
  const [flowLog, setFlowLog] = useState<string>('')
  const flowLogRef = React.useRef<HTMLPreElement | null>(null)
  const [runs, setRuns] = useState<any[]>([])
  const [selectedRun, setSelectedRun] = useState<any | null>(null)
  const [runLog, setRunLog] = useState<string>('')
  const runLogRef = React.useRef<HTMLPreElement | null>(null)

  useEffect(() => {
    if (!selectedFlow || !auth) return
    let mounted = true
    setFlowLog('')
    // SSE with resume support using Last-Event-ID and exponential backoff
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
          let parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find(l => l.startsWith('id:'))
            const dataLine = lines.find(l => l.startsWith('data:'))
            if (idLine) {
              try { lastEventId = Number(idLine.replace(/^id:\s*/, '')) } catch (e) {}
            }
            if (dataLine) {
              try {
                const payload = JSON.parse(dataLine.replace(/^data:\s*/, ''))
                if (!mounted) break
                if (payload.chunk) setFlowLog((prev) => (prev || '') + payload.chunk)
                if (['disabled', 'notfound', 'error'].includes(payload.status)) terminal = true
                if (typeof payload.chunk === 'string' && (payload.chunk.includes('completed') || payload.chunk.includes('failed') || payload.chunk.includes('unexpected error'))) terminal = true
                setTimeout(() => { if (flowLogRef.current) flowLogRef.current.scrollTop = flowLogRef.current.scrollHeight }, 50)
              } catch (e) {
                // ignore
              }
            }
          }
        }
      } catch (e) {
        // failed to connect or stream broke
      }

      // reconnect with backoff if still mounted
      if (!mounted || terminal) return
      reconnectTimer = window.setTimeout(() => { backoff = Math.min(maxBackoff, backoff * 2); connect() }, backoff)
    }

    connect()
    return () => {
      mounted = false
      controller?.abort()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [selectedFlow?.id, auth])

  useEffect(() => {
    fetch('/health')
      .then(r => r.json())
      .then(d => setHealth(d.status))
      .catch(() => setHealth('error'))
  }, [])

  const loadJobs = async () => {
    try {
      const h: Record<string, string> = auth ? { Authorization: `Basic ${auth}` } : {}
      const r = await fetch('/api/jobs', { headers: h })
      if (!r.ok) { setJobs([]); return }
      const d = await r.json()
      setJobs(d)
    } catch (e) {
      setJobs([])
    }
  }

  useEffect(() => { loadJobs() }, [auth])

  useEffect(() => {
    fetch('/api/presets')
      .then(r => r.json())
      .then(d => setPresets(d))
      .catch(() => setPresets({}))
  }, [])

  useEffect(() => {
    if (!auth) return
    fetch('/api/flows', { headers: { Authorization: `Basic ${auth}` } })
      .then(r => r.json())
      .then(d => setFlows(d))
      .catch(() => setFlows([]))
  }, [auth])

  const login = () => {
    const token = btoa(`${user}:${pass}`)
    setAuth(token)
    // reload jobs & flows immediately
    setTimeout(() => { loadJobs(); }, 100)
  }

  const createJob = async (force = false) => {
    if (!url) return
    const body = {
      type: 'download',
      input: {
        url,
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
        setJobMessage(`Job creation failed${txt ? `: ${txt}` : ''}`)
      }
    } catch (e) {
      setJobMessage('Job creation error')
    }
  }

  const createFlow = async () => {
    if (!auth) return alert('Please login')
    if (!flowName || !flowUrl) return alert('Name + URL required')
    const body = {
      name: flowName,
      steps: [{
        action: 'download',
        input: {
          url: flowUrl,
          preset: presetSel,
          compression_profile: compressionProfile,
          lang: compressionLang,
          mime_type: `${compressionFamily}/x-mediaforge`,
        },
      }],
    }
    try {
      const r = await fetch('/api/flows', { method: 'POST', headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!r.ok) return alert('Flow creation failed')
      const f = await r.json()
      setFlowName('')
      setFlowUrl('')
      setFlows((prev) => [f, ...prev])
    } catch (e) {
      console.error(e)
      alert('Flow creation error')
    }
  }

  const runFlow = async (flowId: string) => {
    if (!auth) return alert('Please login')
    try {
      const r = await fetch(`/api/flows/${flowId}/run`, { method: 'POST', headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) return alert('Run failed')
      const data = await r.json()
      // update flow metadata and set selected run for UI
      setFlows((prev) => prev.map((f) => (f.id === flowId ? { ...f, last_run_triggered: Date.now() } : f)))
      if (data.run_id) {
        setSelectedRun({ id: data.run_id, flow_id: data.flow_id, status: 'running' })
        // fetch runs list for the flow
        loadRuns(flowId)
      }
    } catch (e) {
      console.error(e)
      alert('Run failed')
    }
  }

  const loadRuns = async (flowId: number | string) => {
    if (!auth) return
    try {
      const r = await fetch(`/api/flows/${flowId}/runs`, { headers: { Authorization: `Basic ${auth}` } })
      if (!r.ok) { setRuns([]); return }
      const d = await r.json()
      setRuns(d)
    } catch (e) {
      setRuns([])
    }
  }

  useEffect(() => {
    if (!selectedRun || !auth) return
    let mounted = true
    // Poll run details
    const iv = setInterval(async () => {
      try {
        const r = await fetch(`/api/runs/${selectedRun.id}`, { headers: { Authorization: `Basic ${auth}` } })
        if (!r.ok) return
        const d = await r.json()
        if (!mounted) return
        setSelectedRun(d)
      } catch (e) {
        // ignore
      }
    }, 2000)
    return () => { mounted = false; clearInterval(iv) }
  }, [selectedRun?.id, auth])


  // Subscribe to per-run SSE for live run log
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
          let parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const p of parts) {
            if (!p) continue
            const lines = p.split('\n')
            const idLine = lines.find(l => l.startsWith('id:'))
            const dataLine = lines.find(l => l.startsWith('data:'))
            if (idLine) {
              try { lastEventId = Number(idLine.replace(/^id:\s*/, '')) } catch (e) {}
            }
            if (dataLine) {
              try {
                const payload = JSON.parse(dataLine.replace(/^data:\s*/, ''))
                if (!mounted) break
                if (payload.run_log) setRunLog((prev) => (prev || '') + payload.run_log)
                if (['completed', 'failed', 'cancelled', 'notfound'].includes(payload.status)) terminal = true
                setTimeout(() => { if (runLogRef.current) runLogRef.current.scrollTop = runLogRef.current.scrollHeight }, 50)
              } catch (e) {
                // ignore
              }
            }
          }
        }
      } catch (e) {
        // ignore
      }

      if (!mounted || terminal) return
      reconnectTimer = window.setTimeout(() => { backoff = Math.min(maxBackoff, backoff * 2); connect() }, backoff)
    }

    connect()
    return () => {
      mounted = false
      controller?.abort()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [selectedRun?.id, auth])

  return (
    <div style={{ padding: 20, fontFamily: 'Arial, sans-serif' }}>
      <h1>NAS Convert Hub — Dashboard</h1>
      <p><strong>API Health:</strong> {health}</p>

      <div style={{ marginBottom: 12 }}>
        <input placeholder="user" value={user} onChange={e => setUser(e.target.value)} />
        <input placeholder="password" type="password" value={pass} onChange={e => setPass(e.target.value)} style={{ marginLeft: 8 }} />
        <button onClick={login} style={{ marginLeft: 8 }}>Login</button>
      </div>

      <h2>Jobs</h2>
      <div style={{ marginBottom: 12 }}>
        <input placeholder="url" value={url} onChange={e => setUrl(e.target.value)} style={{ width: 400 }} />
        <select value={presetSel} onChange={e => setPresetSel(e.target.value)} style={{ marginLeft: 8 }}>
          {Object.keys(presets || {}).map(k => <option key={k} value={k}>{k}</option>)}
        </select>
        <button onClick={() => createJob()} style={{ marginLeft: 8 }}>Create Job</button>
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
      {jobMessage ? <div style={{ marginBottom: 12 }}>{jobMessage}</div> : null}
      <button onClick={loadJobs}>Refresh Jobs</button>
      {(!Array.isArray(jobs) || jobs.length === 0) ? (
        <p>No jobs yet</p>
      ) : (
        <ul>
          {jobs.map((j: any) => (
            <li key={j.id} style={{ cursor: 'pointer' }} onClick={() => setSelected(j.id)}>
              <strong>#{j.id}</strong> {j.type} — {j.status} — {j.output_path ?? ''}
            </li>
          ))}
        </ul>
      )}

      <JobDetail id={selected} auth={auth} />

      <hr style={{ marginTop: 20, marginBottom: 20 }} />

      <h2>Flows</h2>
      <div style={{ marginBottom: 8 }}>
        <input placeholder="Flow name" value={flowName} onChange={e => setFlowName(e.target.value)} />
        <input placeholder="Download URL" value={flowUrl} onChange={e => setFlowUrl(e.target.value)} style={{ width: 420, marginLeft: 8 }} />
        <button onClick={createFlow} style={{ marginLeft: 8 }}>Create Flow</button>
      </div>

      <div style={{ marginBottom: 12 }}>
        <button onClick={() => { if (auth) { fetch('/api/flows', { headers: { Authorization: `Basic ${auth}` } }).then(r => r.json()).then(d => setFlows(d)) } }}>Refresh Flows</button>
      </div>

      {flows.length === 0 ? (
        <div>No flows yet.</div>
      ) : (
        <div>
          {(Array.isArray(flows) ? flows : []).map(f => (
            <div key={f.id} style={{ border: '1px solid #ddd', padding: 8, marginBottom: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <div>
                  <strong>{f.name}</strong>
                  <div style={{ fontSize: 12, color: '#666' }}>{f.description || ''}</div>
                </div>
                <div>
                  <button onClick={() => setSelectedFlow(f)} style={{ marginRight: 8 }}>Details</button>
                  <button onClick={() => runFlow(f.id)}>Run</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedFlow && (
        <div style={{ marginTop: 12 }}>
          <h3>Flow: {selectedFlow.name}</h3>
          <div>
            <strong>Steps</strong>
              <ol>
              {(selectedFlow && Array.isArray(selectedFlow.steps) ? selectedFlow.steps : []).map((s: any, i: number) => (
                <li key={i}>{s.action} — {JSON.stringify(s.input)}</li>
              ))}
              </ol>
            <div>
              <button onClick={() => runFlow(selectedFlow.id)} style={{ marginRight: 8 }}>Run Flow</button>
              <button onClick={() => loadRuns(selectedFlow.id)} style={{ marginRight: 8 }}>Show Runs</button>
              <button onClick={() => setSelectedFlow(null)}>Close</button>
            </div>
            <div style={{ marginTop: 12 }}>
              <h4>Live Flow Log</h4>
              <pre ref={flowLogRef} style={{ background: '#111', color: '#0ff', padding: 12, height: 240, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{flowLog || 'No flow logs yet'}</pre>
            </div>
            <div style={{ marginTop: 12 }}>
              <h4>Runs</h4>
                  {(!Array.isArray(runs) || runs.length === 0) ? <div>No runs yet</div> : (
                <ul>
                  {runs.map(r => (
                    <li key={r.id} style={{ marginBottom: 6 }}>
                      <strong>Run #{r.id}</strong> — {r.status} — {r.started_at ? new Date(r.started_at).toLocaleString() : ''} {r.finished_at ? `(finished ${new Date(r.finished_at).toLocaleString()})` : ''}
                      <div style={{ marginTop: 4 }}>
                        <button onClick={() => setSelectedRun(r)} style={{ marginRight: 8 }}>View</button>
                        <button onClick={() => { if (r.job_ids && Array.isArray(r.job_ids) && r.job_ids.length) setSelected(r.job_ids[0]) }}>Open first job</button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {selectedRun && (
                <div style={{ marginTop: 12, borderTop: '1px solid #333', paddingTop: 8 }}>
                  <h5>Selected Run #{selectedRun.id} — {selectedRun.status}</h5>
                  <div>Jobs: {selectedRun.job_ids?.length ?? 0}</div>
                    <ul>
                    {(selectedRun && Array.isArray(selectedRun.job_ids) ? selectedRun.job_ids : []).map((jid: number) => (
                      <li key={jid}>
                        Job #{jid} <button onClick={() => setSelected(jid)} style={{ marginLeft: 8 }}>Open</button>
                      </li>
                    ))}
                    </ul>
                  <div style={{ marginTop: 8 }}>
                    <h5>Run Log</h5>
                    <pre ref={runLogRef} style={{ background: '#111', color: '#ff8', padding: 12, height: 180, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{runLog || 'No run log yet'}</pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {pendingWarning ? (
        <Modal
          title={compressionLang === 'de' ? 'Achtung: Qualitätswarnung' : 'Warning: quality impact'}
          onClose={() => setPendingWarning(null)}
          onConfirm={() => createJob(true)}
          cancelLabel={compressionLang === 'de' ? 'Abbrechen' : 'Cancel'}
          confirmLabel={compressionLang === 'de' ? 'Bestätigen' : 'Confirm'}
        >
          <p>{compressionLang === 'de' ? 'Das gewählte Profil kann Qualitätsverluste verursachen:' : 'The selected profile may cause quality loss:'}</p>
          <p><strong>{pendingWarning}</strong></p>
          <p>{compressionLang === 'de' ? 'Möchtest du trotzdem fortfahren?' : 'Do you want to continue?'}</p>
        </Modal>
      ) : null}
    </div>
  )
}

export default App
