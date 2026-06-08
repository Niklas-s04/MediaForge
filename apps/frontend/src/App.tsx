import React, { useEffect, useMemo, useRef, useState } from 'react'
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
type MediaFamily = 'video' | 'audio' | 'image'
type QualityPreset = 'high' | 'balanced' | 'small'

type FormatDef = {
  value: string
  label: string
  family: MediaFamily
  text: string
}

type InspectInfo = {
  title?: string | null
  uploader?: string | null
  duration?: number | null
  thumbnail?: string | null
  formats?: { height?: number | null; ext?: string | null; fps?: number | null }[]
}

type AdvancedValues = {
  video_codec: string
  audio_codec: string
  audio_bitrate: string
  sample_rate: string
  audio_channels: string
  crf: string
  max_width: string
  max_height: string
  max_fps: string
  image_quality: string
}

const terminalStatuses = ['success', 'failed', 'cancelled', 'notfound']

const formatCatalog: Record<MediaFamily, FormatDef[]> = {
  video: [
    { family: 'video', value: 'mp4', label: 'MP4', text: 'Universell, Web, TV und mobile Geräte' },
    { family: 'video', value: 'webm', label: 'WebM', text: 'Modern, klein und browserfreundlich' },
    { family: 'video', value: 'mkv', label: 'MKV', text: 'Flexible Datei für Archiv und NAS' },
  ],
  audio: [
    { family: 'audio', value: 'mp3', label: 'MP3', text: 'Maximale Kompatibilität' },
    { family: 'audio', value: 'm4a', label: 'M4A', text: 'Gute Qualität bei kleiner Datei' },
    { family: 'audio', value: 'opus', label: 'Opus', text: 'Sehr effizient für Sprache und Musik' },
    { family: 'audio', value: 'wav', label: 'WAV', text: 'Unkomprimiert für Schnittprogramme' },
    { family: 'audio', value: 'flac', label: 'FLAC', text: 'Verlustfrei komprimiert' },
  ],
  image: [
    { family: 'image', value: 'webp', label: 'WebP', text: 'Klein, modern und webfreundlich' },
    { family: 'image', value: 'jpg', label: 'JPG', text: 'Fotos und breite Kompatibilität' },
    { family: 'image', value: 'png', label: 'PNG', text: 'Grafiken und Transparenz' },
  ],
}

const familyLabels: Record<MediaFamily, string> = {
  video: 'Video',
  audio: 'Audio',
  image: 'Bild',
}

const qualityOptions: { value: QualityPreset; label: string; text: string }[] = [
  { value: 'high', label: 'Originalnah', text: 'Mehr Qualität, größere Datei' },
  { value: 'balanced', label: 'Ausgewogen', text: 'Guter Standard für Alltag und NAS' },
  { value: 'small', label: 'Kleine Datei', text: 'Stark komprimiert für Speicherplatz' },
]

const downloadQualities = [
  { value: 'best', label: 'Beste verfügbare' },
  { value: '1080p', label: '1080p' },
  { value: '720p', label: '720p' },
  { value: '480p', label: '480p' },
  { value: '360p', label: '360p' },
]

const defaultAdvanced: AdvancedValues = {
  video_codec: '',
  audio_codec: '',
  audio_bitrate: '',
  sample_rate: '',
  audio_channels: '',
  crf: '',
  max_width: '',
  max_height: '',
  max_fps: '',
  image_quality: '',
}

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

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(bytes > 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function formatDuration(seconds?: number | null) {
  if (!seconds) return null
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}:${String(secs).padStart(2, '0')}`
}

function inferFamily(file: File | null): MediaFamily {
  if (!file) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (ext && ['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus'].includes(ext)) return 'audio'
  if (ext && ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff'].includes(ext)) return 'image'
  return 'video'
}

function fileExt(name?: string | null) {
  const ext = name?.split('.').pop()?.toUpperCase()
  return ext && ext.length <= 6 ? ext : 'MEDIA'
}

function allowedConvertFamilies(sourceFamily: MediaFamily): MediaFamily[] {
  if (sourceFamily === 'video') return ['video', 'audio']
  if (sourceFamily === 'audio') return ['audio']
  return ['image']
}

function findFormat(family: MediaFamily, value: string): FormatDef {
  return formatCatalog[family].find((format) => format.value === value) || formatCatalog[family][0]
}

function FormatPicker({
  families,
  selectedFamily,
  selectedFormat,
  open,
  onOpenChange,
  onSelect,
}: {
  families: MediaFamily[]
  selectedFamily: MediaFamily
  selectedFormat: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (family: MediaFamily, format: string) => void
}) {
  const [query, setQuery] = useState('')
  const [activeFamily, setActiveFamily] = useState<MediaFamily>(selectedFamily)
  const selected = findFormat(selectedFamily, selectedFormat)
  const formats = formatCatalog[activeFamily].filter((format) => {
    const haystack = `${format.label} ${format.text}`.toLowerCase()
    return haystack.includes(query.toLowerCase())
  })

  useEffect(() => {
    if (!families.includes(activeFamily)) setActiveFamily(families[0])
  }, [families, activeFamily])

  return (
    <div className="format-picker">
      <button className="format-button" type="button" onClick={() => onOpenChange(!open)}>
        <span>{selected.label}</span>
        <small>{familyLabels[selected.family]}</small>
      </button>
      {open ? (
        <div className="format-menu">
          <label className="format-search">
            <span>Search Format</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="z. B. mp4, mp3, webp" />
          </label>
          <div className="format-menu-body">
            <div className="format-categories">
              {families.map((family) => (
                <button
                  key={family}
                  className={activeFamily === family ? 'active' : ''}
                  type="button"
                  onClick={() => setActiveFamily(family)}
                >
                  {familyLabels[family]}
                </button>
              ))}
            </div>
            <div className="format-results">
              {formats.map((format) => (
                <button
                  key={`${format.family}-${format.value}`}
                  className={format.value === selectedFormat && format.family === selectedFamily ? 'active' : ''}
                  type="button"
                  onClick={() => {
                    onSelect(format.family, format.value)
                    onOpenChange(false)
                    setQuery('')
                  }}
                >
                  <strong>{format.label}</strong>
                  <span>{format.text}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function QualitySelector({
  value,
  onChange,
}: {
  value: QualityPreset
  onChange: (value: QualityPreset) => void
}) {
  return (
    <div className="quality-row">
      {qualityOptions.map((option) => (
        <button
          key={option.value}
          className={value === option.value ? 'active' : ''}
          data-testid={`quality-${option.value}`}
          type="button"
          onClick={() => onChange(option.value)}
        >
          <strong>{option.label}</strong>
          <span>{option.text}</span>
        </button>
      ))}
    </div>
  )
}

function AdvancedOptions({
  family,
  values,
  setValues,
  stripMetadata,
  setStripMetadata,
  isDownload,
  downloadQuality,
  setDownloadQuality,
}: {
  family: MediaFamily
  values: AdvancedValues
  setValues: React.Dispatch<React.SetStateAction<AdvancedValues>>
  stripMetadata: boolean
  setStripMetadata: (value: boolean) => void
  isDownload?: boolean
  downloadQuality?: string
  setDownloadQuality?: (value: string) => void
}) {
  const update = (key: keyof AdvancedValues, value: string) => {
    setValues((current) => ({ ...current, [key]: value }))
  }

  return (
    <div className="advanced-panel">
      {isDownload && family === 'video' ? (
        <label className="field">
          <span>Download-Auflösung</span>
          <select value={downloadQuality} onChange={(event) => setDownloadQuality?.(event.target.value)}>
            {downloadQualities.map((quality) => (
              <option key={quality.value} value={quality.value}>{quality.label}</option>
            ))}
          </select>
        </label>
      ) : null}

      {family === 'video' ? (
        <>
          <label className="field">
            <span>Video-Codec</span>
            <select value={values.video_codec} onChange={(event) => update('video_codec', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="libx264">H.264</option>
              <option value="libx265">H.265 / HEVC</option>
              <option value="libvpx-vp9">VP9</option>
            </select>
          </label>
          <label className="field">
            <span>Audio-Codec</span>
            <select value={values.audio_codec} onChange={(event) => update('audio_codec', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="aac">AAC</option>
              <option value="libopus">Opus</option>
              <option value="libmp3lame">MP3</option>
            </select>
          </label>
          <label className="field">
            <span>CRF</span>
            <input value={values.crf} onChange={(event) => update('crf', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
          <label className="field">
            <span>Max. Breite</span>
            <input value={values.max_width} onChange={(event) => update('max_width', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
          <label className="field">
            <span>Max. Höhe</span>
            <input value={values.max_height} onChange={(event) => update('max_height', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
          <label className="field">
            <span>Max. FPS</span>
            <input value={values.max_fps} onChange={(event) => update('max_fps', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
        </>
      ) : null}

      {family === 'audio' ? (
        <>
          <label className="field">
            <span>Audio-Codec</span>
            <select value={values.audio_codec} onChange={(event) => update('audio_codec', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="libmp3lame">MP3</option>
              <option value="aac">AAC</option>
              <option value="libopus">Opus</option>
              <option value="flac">FLAC</option>
              <option value="pcm_s16le">PCM WAV</option>
            </select>
          </label>
          <label className="field">
            <span>Bitrate</span>
            <select value={values.audio_bitrate} onChange={(event) => update('audio_bitrate', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="64k">64 kbit/s</option>
              <option value="96k">96 kbit/s</option>
              <option value="128k">128 kbit/s</option>
              <option value="160k">160 kbit/s</option>
              <option value="192k">192 kbit/s</option>
              <option value="256k">256 kbit/s</option>
              <option value="320k">320 kbit/s</option>
            </select>
          </label>
          <label className="field">
            <span>Sample-Rate</span>
            <select value={values.sample_rate} onChange={(event) => update('sample_rate', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="44100">44.1 kHz</option>
              <option value="48000">48 kHz</option>
              <option value="96000">96 kHz</option>
            </select>
          </label>
          <label className="field">
            <span>Kanäle</span>
            <select value={values.audio_channels} onChange={(event) => update('audio_channels', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="1">Mono</option>
              <option value="2">Stereo</option>
            </select>
          </label>
        </>
      ) : null}

      {family === 'image' ? (
        <>
          <label className="field">
            <span>Bildqualität</span>
            <input value={values.image_quality} onChange={(event) => update('image_quality', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
          <label className="field">
            <span>Max. Breite</span>
            <input value={values.max_width} onChange={(event) => update('max_width', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
          <label className="field">
            <span>Max. Höhe</span>
            <input value={values.max_height} onChange={(event) => update('max_height', event.target.value)} placeholder="Automatisch" inputMode="numeric" />
          </label>
        </>
      ) : null}

      <label className="toggle-row">
        <input type="checkbox" checked={stripMetadata} onChange={(event) => setStripMetadata(event.target.checked)} />
        <span>Metadaten entfernen</span>
      </label>
    </div>
  )
}

function ConversionCard({
  sourceTitle,
  sourceMeta,
  sourceFormat,
  families,
  selectedFamily,
  selectedFormat,
  pickerOpen,
  onPickerOpen,
  onSelect,
}: {
  sourceTitle: string
  sourceMeta: string
  sourceFormat: string
  families: MediaFamily[]
  selectedFamily: MediaFamily
  selectedFormat: string
  pickerOpen: boolean
  onPickerOpen: (open: boolean) => void
  onSelect: (family: MediaFamily, format: string) => void
}) {
  return (
    <div className="convert-card">
      <div className="source-file">
        <span className="file-icon">{sourceFormat.slice(0, 3)}</span>
        <div>
          <strong>{sourceTitle}</strong>
          <span>{sourceMeta}</span>
        </div>
      </div>
      <div className="convert-chain">
        <span>Convert</span>
        <span className="format-chip">{sourceFormat}</span>
        <span className="arrow">-&gt;</span>
        <FormatPicker
          families={families}
          selectedFamily={selectedFamily}
          selectedFormat={selectedFormat}
          open={pickerOpen}
          onOpenChange={onPickerOpen}
          onSelect={onSelect}
        />
      </div>
    </div>
  )
}

function JobDetail({
  job,
  onDownload,
  onTerminal,
}: {
  job: Job | null
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
      const hdrs: Record<string, string> = {}
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
  }, [job?.id, onTerminal])

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
            <button className="button primary" type="button" onClick={() => onDownload(job)}>
              Herunterladen
            </button>
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
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<ActiveTab>('download')
  const [url, setUrl] = useState('')
  const [downloadFamily, setDownloadFamily] = useState<MediaFamily>('video')
  const [downloadFormat, setDownloadFormat] = useState('mp4')
  const [downloadQuality, setDownloadQuality] = useState('best')
  const [downloadQualityPreset, setDownloadQualityPreset] = useState<QualityPreset>('balanced')
  const [downloadAdvanced, setDownloadAdvanced] = useState<AdvancedValues>(defaultAdvanced)
  const [downloadInfo, setDownloadInfo] = useState<InspectInfo | null>(null)
  const [isInspecting, setIsInspecting] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [message, setMessage] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [sourceFamily, setSourceFamily] = useState<MediaFamily>('video')
  const [convertFamily, setConvertFamily] = useState<MediaFamily>('video')
  const [convertFormat, setConvertFormat] = useState('mp4')
  const [convertQualityPreset, setConvertQualityPreset] = useState<QualityPreset>('balanced')
  const [convertAdvanced, setConvertAdvanced] = useState<AdvancedValues>(defaultAdvanced)
  const [stripMetadata, setStripMetadata] = useState(true)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState<ActiveTab | null>(null)
  const [compressionWarning, setCompressionWarning] = useState<string | null>(null)
  const [pendingWarning, setPendingWarning] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<ActiveTab>('download')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedId) || null, [jobs, selectedId])
  const finishedJobs = useMemo(() => jobs.filter((job) => job.status === 'success' && job.output_path), [jobs])
  const activeJobs = useMemo(
    () => jobs.filter((job) => ['queued', 'running'].includes((job.status || '').toLowerCase())).length,
    [jobs],
  )
  const convertFamilies = allowedConvertFamilies(sourceFamily)
  const activeQuality = activeTab === 'download' ? downloadQualityPreset : convertQualityPreset
  const activeWarningFamily = activeTab === 'download' ? downloadFamily : convertFamily

  const loadJobs = async () => {
    try {
      const r = await fetch('/api/jobs')
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
    loadJobs()
  }, [])

  useEffect(() => {
    const interval = window.setInterval(loadJobs, 5000)
    return () => window.clearInterval(interval)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const allowed = formatCatalog[downloadFamily].map((format) => format.value)
    if (!allowed.includes(downloadFormat)) {
      setDownloadFormat(formatCatalog[downloadFamily][0].value)
    }
  }, [downloadFamily, downloadFormat])

  useEffect(() => {
    const nextSource = inferFamily(selectedFile)
    setSourceFamily(nextSource)
    const allowed = allowedConvertFamilies(nextSource)
    const nextFamily = allowed.includes(convertFamily) ? convertFamily : allowed[0]
    setConvertFamily(nextFamily)
    if (!formatCatalog[nextFamily].some((format) => format.value === convertFormat)) {
      setConvertFormat(formatCatalog[nextFamily][0].value)
    }
  }, [selectedFile])

  useEffect(() => {
    if (!convertFamilies.includes(convertFamily)) {
      setConvertFamily(convertFamilies[0])
      setConvertFormat(formatCatalog[convertFamilies[0]][0].value)
      return
    }
    if (!formatCatalog[convertFamily].some((format) => format.value === convertFormat)) {
      setConvertFormat(formatCatalog[convertFamily][0].value)
    }
  }, [convertFamily, convertFormat, convertFamilies])

  useEffect(() => {
    const warningProfile = activeQuality === 'small' ? 'small' : 'balanced'
    fetch(
      `/api/compression/profile?family=${encodeURIComponent(activeWarningFamily)}&profile=${encodeURIComponent(warningProfile)}&lang=de`,
    )
      .then((r) => r.json())
      .then((data) => setCompressionWarning(data.warning || null))
      .catch(() => setCompressionWarning(null))
  }, [activeWarningFamily, activeQuality])

  const appendAdvanced = (target: FormData | Record<string, unknown>, values: AdvancedValues) => {
    Object.entries(values).forEach(([key, value]) => {
      if (!value) return
      if (target instanceof FormData) target.set(key, value)
      else target[key] = value
    })
  }

  const analyzeDownload = async () => {
    if (!url.trim()) {
      setMessage('Bitte eine Download-URL eintragen.')
      return
    }
    try {
      setIsInspecting(true)
      setMessage(null)
      const r = await fetch('/api/download/inspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })
      if (!r.ok) {
        setDownloadInfo(null)
        setMessage('Analyse nicht möglich. Du kannst den Download trotzdem starten.')
        return
      }
      setDownloadInfo(await r.json())
    } catch (e) {
      setDownloadInfo(null)
      setMessage('Analyse nicht möglich. Du kannst den Download trotzdem starten.')
    } finally {
      setIsInspecting(false)
    }
  }

  const createDownloadJob = async (force = false) => {
    if (!url.trim()) {
      setMessage('Bitte eine Download-URL eintragen.')
      return
    }
    const input: Record<string, unknown> = {
      url: url.trim(),
      preset: 'default',
      output_kind: downloadFamily,
      output_format: downloadFormat,
      download_quality: downloadFamily === 'video' ? downloadQuality : 'best',
      quality_preset: downloadQualityPreset,
      compression_profile: downloadQualityPreset === 'small' ? 'small' : 'balanced',
      lang: 'de',
      strip_metadata: stripMetadata,
    }
    appendAdvanced(input, downloadAdvanced)
    const body = { type: 'download', input }

    try {
      setMessage(null)
      const params = new URLSearchParams({ lang: 'de' })
      if (force) params.set('force', 'true')
      const r = await fetch(`/api/jobs?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (r.ok) {
        const created = await r.json()
        setUrl('')
        setDownloadInfo(null)
        setPendingWarning(null)
        setMessage(`Download gestartet: Auftrag #${created.id}`)
        setSelectedId(created.id)
        loadJobs()
      } else if (r.status === 409) {
        const data = await r.json().catch(() => null)
        setPendingAction('download')
      setPendingWarning(data?.detail?.warning || data?.warning || compressionWarning || 'Qualitätswarnung')
      } else {
        setMessage('Download konnte nicht gestartet werden.')
      }
    } catch (e) {
      setMessage('Download konnte nicht gestartet werden.')
    }
  }

  const createConvertJob = async (force = false) => {
    if (!selectedFile) {
      setMessage('Bitte eine Datei auswählen.')
      return
    }

    const data = new FormData()
    data.set('file', selectedFile)
    data.set('preset', 'default')
    data.set('compression_family', convertFamily)
    data.set('compression_profile', convertQualityPreset === 'small' ? 'small' : 'balanced')
    data.set('quality_preset', convertQualityPreset)
    data.set('output_format', convertFormat)
    data.set('strip_metadata', stripMetadata ? 'true' : 'false')
    data.set('lang', 'de')
    appendAdvanced(data, convertAdvanced)

    try {
      setMessage(null)
      const params = new URLSearchParams()
      if (force) params.set('force', 'true')
      const suffix = params.toString() ? `?${params.toString()}` : ''
      const r = await fetch(`/api/jobs/convert-upload${suffix}`, {
        method: 'POST',
        body: data,
      })
      if (r.ok) {
        const created = await r.json()
        setSelectedFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
        setPendingWarning(null)
        setMessage(`Konvertierung gestartet: Auftrag #${created.id}`)
        setSelectedId(created.id)
        loadJobs()
      } else if (r.status === 409) {
        const warning = await r.json().catch(() => null)
        setPendingAction('convert')
        setPendingWarning(warning?.detail?.warning || warning?.warning || compressionWarning || 'Qualitätswarnung')
      } else if (r.status === 413) {
        setMessage('Die Datei ist größer als das erlaubte Upload-Limit.')
      } else {
        setMessage('Konvertierung konnte nicht gestartet werden.')
      }
    } catch (e) {
      setMessage('Konvertierung konnte nicht gestartet werden.')
    }
  }

  const downloadJob = async (job: Job) => {
    try {
      const r = await fetch(`/api/jobs/${job.id}/download`)
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
    if (pendingAction === 'download') createDownloadJob(true)
    else createConvertJob(true)
  }

  const onDropFile = (event: React.DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (file) setSelectedFile(file)
  }

  const availableHeights = (downloadInfo?.formats || [])
    .map((format) => format.height)
    .filter((height): height is number => Boolean(height))

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup" aria-label="MediaForge">
          <span className="brand-mark">MF</span>
          <div>
            <h1>MediaForge</h1>
            <p>Downloads und Konvertierungen mit passenden Formaten und Feineinstellungen.</p>
          </div>
        </div>
        <button
          className="theme-toggle"
          type="button"
          aria-pressed={theme === 'dark'}
          onClick={() => setTheme((current) => (current === 'dark' ? 'light' : 'dark'))}
        >
          <span>{theme === 'dark' ? 'Dunkel' : 'Hell'}</span>
          <i aria-hidden="true" />
        </button>
      </header>

      <section className="main-layout">
        <div className="work-column">
          <div className="tab-bar" role="tablist" aria-label="Auftragstyp">
            <button className={`tab-button ${activeTab === 'download' ? 'active' : ''}`} role="tab" aria-selected={activeTab === 'download'} type="button" onClick={() => setActiveTab('download')}>Download</button>
            <button className={`tab-button ${activeTab === 'convert' ? 'active' : ''}`} role="tab" aria-selected={activeTab === 'convert'} type="button" onClick={() => setActiveTab('convert')}>Konvertieren</button>
          </div>

          <section className="panel work-panel">
            {activeTab === 'download' ? (
              <>
                <div className="panel-header">
                  <div>
                    <p className="eyebrow">Online-Quelle</p>
                    <h2>Medium herunterladen</h2>
                  </div>
                </div>
                <div className="url-row">
                  <label className="field">
                    <span>URL</span>
                    <input placeholder="https://..." value={url} onChange={(e) => { setUrl(e.target.value); setDownloadInfo(null) }} />
                  </label>
                  <button className="button secondary" type="button" onClick={analyzeDownload}>{isInspecting ? 'Analysiere...' : 'Analysieren'}</button>
                </div>
                {downloadInfo ? (
                  <div className="inspect-result">
                    {downloadInfo.thumbnail ? <img src={downloadInfo.thumbnail} alt="" /> : <span className="media-thumb">MF</span>}
                    <div>
                      <strong>{downloadInfo.title || 'Medium erkannt'}</strong>
                      <span>{[downloadInfo.uploader, formatDuration(downloadInfo.duration)].filter(Boolean).join(' - ') || 'Bereit für den Download'}</span>
                      {availableHeights.length ? <small>Videoqualitäten bis {Math.max(...availableHeights)}p erkannt</small> : null}
                    </div>
                  </div>
                ) : null}
                <ConversionCard
                  sourceTitle={downloadInfo?.title || 'Online-Medium'}
                  sourceMeta={url || 'URL einfügen und optional analysieren'}
                  sourceFormat="WEB"
                  families={['video', 'audio']}
                  selectedFamily={downloadFamily}
                  selectedFormat={downloadFormat}
                  pickerOpen={pickerOpen === 'download'}
                  onPickerOpen={(open) => setPickerOpen(open ? 'download' : null)}
                  onSelect={(family, format) => {
                    setDownloadFamily(family)
                    setDownloadFormat(format)
                  }}
                />
                <div className="options-block">
                  <div className="options-title">
                    <span>Qualität</span>
                    <button className="link-button" type="button" onClick={() => setAdvancedOpen((open) => !open)}>
                      {advancedOpen ? 'Optionen ausblenden' : 'Detaillierte Optionen'}
                    </button>
                  </div>
                  <QualitySelector value={downloadQualityPreset} onChange={setDownloadQualityPreset} />
                  {advancedOpen ? (
                    <AdvancedOptions
                      family={downloadFamily}
                      values={downloadAdvanced}
                      setValues={setDownloadAdvanced}
                      stripMetadata={stripMetadata}
                      setStripMetadata={setStripMetadata}
                      isDownload
                      downloadQuality={downloadQuality}
                      setDownloadQuality={setDownloadQuality}
                    />
                  ) : null}
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
                  <input id="file-upload" ref={fileInputRef} type="file" onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
                  <label htmlFor="file-upload" onDragOver={(event) => event.preventDefault()} onDrop={onDropFile}>
                    <strong>{selectedFile ? selectedFile.name : 'Datei auswählen oder hier ablegen'}</strong>
                    <span>{selectedFile ? `${formatBytes(selectedFile.size)} - ${familyLabels[sourceFamily]} erkannt` : 'Audio, Video oder Bild vom Computer hochladen'}</span>
                  </label>
                </div>
                <ConversionCard
                  sourceTitle={selectedFile?.name || 'Keine Datei ausgewählt'}
                  sourceMeta={selectedFile ? `${formatBytes(selectedFile.size)} - ${familyLabels[sourceFamily]}` : 'Datei hochladen, dann Ziel-Format wählen'}
                  sourceFormat={selectedFile ? fileExt(selectedFile.name) : 'FILE'}
                  families={convertFamilies}
                  selectedFamily={convertFamily}
                  selectedFormat={convertFormat}
                  pickerOpen={pickerOpen === 'convert'}
                  onPickerOpen={(open) => setPickerOpen(open ? 'convert' : null)}
                  onSelect={(family, format) => {
                    setConvertFamily(family)
                    setConvertFormat(format)
                  }}
                />
                <div className="options-block">
                  <div className="options-title">
                    <span>Qualität</span>
                    <button className="link-button" type="button" onClick={() => setAdvancedOpen((open) => !open)}>
                      {advancedOpen ? 'Optionen ausblenden' : 'Detaillierte Optionen'}
                    </button>
                  </div>
                  <QualitySelector value={convertQualityPreset} onChange={setConvertQualityPreset} />
                  {advancedOpen ? (
                    <AdvancedOptions
                      family={convertFamily}
                      values={convertAdvanced}
                      setValues={setConvertAdvanced}
                      stripMetadata={stripMetadata}
                      setStripMetadata={setStripMetadata}
                    />
                  ) : null}
                </div>
              </>
            )}

            {compressionWarning ? <div className="warning-inline"><strong>Hinweis:</strong> {compressionWarning}</div> : null}

            <div className="panel-footer">
              <button className="button primary" data-testid="create-job" type="button" onClick={() => (activeTab === 'download' ? createDownloadJob() : createConvertJob())}>
                {activeTab === 'download' ? 'Download starten' : 'Konvertierung starten'}
              </button>
            </div>
            {message ? <div className="message">{message}</div> : null}
          </section>

          <JobDetail job={selectedJob} onDownload={downloadJob} onTerminal={loadJobs} />
        </div>

        <aside className="side-column">
          <section className="panel queue-panel">
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">Aufträge</p>
                <h2>{jobs.length} insgesamt</h2>
              </div>
              <button className="button ghost" type="button" onClick={loadJobs}>Aktualisieren</button>
            </div>
            {jobs.length === 0 ? (
              <EmptyState title="Noch keine Aufträge" text="Starte einen Download oder lade eine Datei zur Konvertierung hoch." />
            ) : (
              <div className="item-list">
                {jobs.map((job) => (
                  <button key={job.id} className={`list-item ${selectedId === job.id ? 'selected' : ''}`} type="button" onClick={() => setSelectedId(job.id)}>
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
                <h2>Dateien</h2>
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
                    <button className="button secondary" type="button" onClick={() => downloadJob(job)}>Download</button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </section>

      {pendingWarning ? (
        <Modal title="Qualitätswarnung" onClose={() => setPendingWarning(null)} onConfirm={confirmPendingWarning} cancelLabel="Abbrechen" confirmLabel="Trotzdem starten">
          <p>Das gewählte Qualitätsziel kann sichtbare oder hörbare Verluste verursachen:</p>
          <p><strong>{pendingWarning}</strong></p>
          <p>Möchtest du trotzdem fortfahren?</p>
        </Modal>
      ) : null}
    </main>
  )
}

export default App


