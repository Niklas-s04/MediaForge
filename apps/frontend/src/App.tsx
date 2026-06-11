import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Modal from './Modal'

type Job = {
  id: number
  type: 'download' | 'convert' | string
  status: string
  progress?: number
  current_step?: string | null
  output_path?: string | null
  created_at?: string | null
  finished_at?: string | null
  expires_at?: string | null
}

type ActiveTab = 'download' | 'convert'
type MediaFamily = 'video' | 'audio' | 'image' | 'document' | 'spreadsheet' | 'presentation' | 'pdf' | 'text'
type QualityPreset = 'high' | 'balanced' | 'small'

type FormatDef = {
  value: string
  label: string
  family: MediaFamily
  text: string
}

type TransferPhase = 'upload' | 'download' | 'convert'

type TransferState = {
  phase: TransferPhase
  jobId?: number
  loaded: number
  total?: number
  startedAt: number
  progress: number
  etaSeconds?: number | null
  indeterminate?: boolean
  label: string
}

type OptionsResponse = {
  download?: {
    formats?: Partial<Record<MediaFamily, string[]>>
  }
  convert?: {
    formats?: Partial<Record<MediaFamily, string[]>>
  }
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

const terminalStatuses = ['success', 'failed', 'cancelled', 'expired', 'deleted', 'notfound']

const formatCatalog: Record<MediaFamily, FormatDef[]> = {
  video: [
    { family: 'video', value: 'mp4', label: 'MP4', text: 'Universell, Web, TV und mobile Geräte' },
    { family: 'video', value: 'webm', label: 'WebM', text: 'Modern, klein und browserfreundlich' },
    { family: 'video', value: 'mkv', label: 'MKV', text: 'Flexible Datei für Archiv und NAS' },
    { family: 'video', value: 'mov', label: 'MOV', text: 'Gut für Apple-Workflows und Schnitt' },
    { family: 'video', value: 'm4v', label: 'M4V', text: 'MP4-Variante für Apple-Geräte' },
    { family: 'video', value: 'avi', label: 'AVI', text: 'Älterer Container für Legacy-Software' },
    { family: 'video', value: 'mpg', label: 'MPG', text: 'MPEG-2 für ältere Player und DVD-Tools' },
    { family: 'video', value: 'mpeg', label: 'MPEG', text: 'Kompatibler MPEG-2-Container' },
    { family: 'video', value: 'flv', label: 'FLV', text: 'Flash-Container für ältere Web-Archive' },
    { family: 'video', value: 'wmv', label: 'WMV', text: 'Windows-Media-Container für Legacy-Geräte' },
    { family: 'video', value: 'ogv', label: 'OGV', text: 'Offenes Ogg-Videoformat' },
    { family: 'video', value: 'ts', label: 'TS', text: 'MPEG-Transportstream für Broadcasts' },
    { family: 'video', value: 'vob', label: 'VOB', text: 'DVD-kompatibler MPEG-Container' },
  ],
  audio: [
    { family: 'audio', value: 'mp3', label: 'MP3', text: 'Maximale Kompatibilität' },
    { family: 'audio', value: 'm4a', label: 'M4A', text: 'Gute Qualität bei kleiner Datei' },
    { family: 'audio', value: 'aac', label: 'AAC', text: 'Effizient für Web, Handy und Streaming' },
    { family: 'audio', value: 'ogg', label: 'OGG', text: 'Offen und gut für Web-Audio' },
    { family: 'audio', value: 'opus', label: 'Opus', text: 'Sehr effizient für Sprache und Musik' },
    { family: 'audio', value: 'wav', label: 'WAV', text: 'Unkomprimiert für Schnittprogramme' },
    { family: 'audio', value: 'flac', label: 'FLAC', text: 'Verlustfrei komprimiert' },
    { family: 'audio', value: 'aiff', label: 'AIFF', text: 'Unkomprimiert für Audio-Workstations' },
    { family: 'audio', value: 'alac', label: 'ALAC', text: 'Apple Lossless für Musikarchive' },
    { family: 'audio', value: 'wma', label: 'WMA', text: 'Windows-Media-Audio für ältere Geräte' },
    { family: 'audio', value: 'oga', label: 'OGA', text: 'Ogg-Audio mit Vorbis-Codec' },
  ],
  image: [
    { family: 'image', value: 'webp', label: 'WebP', text: 'Klein, modern und webfreundlich' },
    { family: 'image', value: 'jpg', label: 'JPG', text: 'Fotos und breite Kompatibilität' },
    { family: 'image', value: 'png', label: 'PNG', text: 'Grafiken und Transparenz' },
    { family: 'image', value: 'avif', label: 'AVIF', text: 'Sehr effizient für moderne Browser' },
    { family: 'image', value: 'gif', label: 'GIF', text: 'Einzelbild oder einfache Web-Grafik' },
    { family: 'image', value: 'bmp', label: 'BMP', text: 'Unkomprimiert für ältere Anwendungen' },
    { family: 'image', value: 'tiff', label: 'TIFF', text: 'Druck, Scan und Archiv' },
    { family: 'image', value: 'ico', label: 'ICO', text: 'Icon-Datei für Apps und Websites' },
    { family: 'image', value: 'svg', label: 'SVG', text: 'Vektorisierte Grafik für Skalierung' },
  ],
  document: [
    { family: 'document', value: 'docx', label: 'DOCX', text: 'Modernes Word-Dokument' },
    { family: 'document', value: 'doc', label: 'DOC', text: 'Älteres Word-Dokument' },
    { family: 'document', value: 'odt', label: 'ODT', text: 'OpenDocument-Textdatei' },
    { family: 'document', value: 'rtf', label: 'RTF', text: 'Rich-Text-Dokument' },
    { family: 'document', value: 'txt', label: 'TXT', text: 'Einfacher Text' },
    { family: 'document', value: 'html', label: 'HTML', text: 'Web-/Archivansicht' },
    { family: 'document', value: 'pdf', label: 'PDF', text: 'Dokument als PDF exportieren' },
  ],
  spreadsheet: [
    { family: 'spreadsheet', value: 'xlsx', label: 'XLSX', text: 'Moderne Excel-Arbeitsmappe' },
    { family: 'spreadsheet', value: 'xls', label: 'XLS', text: 'Ältere Excel-Arbeitsmappe' },
    { family: 'spreadsheet', value: 'ods', label: 'ODS', text: 'OpenDocument-Tabelle' },
    { family: 'spreadsheet', value: 'csv', label: 'CSV', text: 'Kommagetrennte Werte' },
    { family: 'spreadsheet', value: 'html', label: 'HTML', text: 'Tabelle als HTML' },
    { family: 'spreadsheet', value: 'pdf', label: 'PDF', text: 'Tabelle als PDF exportieren' },
  ],
  presentation: [
    { family: 'presentation', value: 'pptx', label: 'PPTX', text: 'Moderne PowerPoint-Datei' },
    { family: 'presentation', value: 'ppt', label: 'PPT', text: 'Ältere PowerPoint-Datei' },
    { family: 'presentation', value: 'odp', label: 'ODP', text: 'OpenDocument-Präsentation' },
    { family: 'presentation', value: 'html', label: 'HTML', text: 'Präsentation als HTML' },
    { family: 'presentation', value: 'pdf', label: 'PDF', text: 'Folien als PDF exportieren' },
  ],
  pdf: [
    { family: 'pdf', value: 'pdf', label: 'PDF', text: 'PDF beibehalten' },
    { family: 'pdf', value: 'txt', label: 'TXT', text: 'Text aus PDF extrahieren' },
  ],
  text: [
    { family: 'text', value: 'txt', label: 'TXT', text: 'Einfacher Text' },
    { family: 'text', value: 'html', label: 'HTML', text: 'Text als HTML' },
    { family: 'text', value: 'pdf', label: 'PDF', text: 'Text als PDF exportieren' },
    { family: 'text', value: 'docx', label: 'DOCX', text: 'Text als Word-Dokument' },
    { family: 'text', value: 'odt', label: 'ODT', text: 'Text als OpenDocument' },
    { family: 'text', value: 'rtf', label: 'RTF', text: 'Text als Rich Text' },
  ],
}

const familyLabels: Record<MediaFamily, string> = {
  video: 'Video',
  audio: 'Audio',
  image: 'Bild',
  document: 'Dokument',
  spreadsheet: 'Tabelle',
  presentation: 'Präsentation',
  pdf: 'PDF',
  text: 'Text',
}

const mediaFamilies: MediaFamily[] = ['video', 'audio', 'image', 'document', 'spreadsheet', 'presentation', 'pdf', 'text']

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

function formatEta(seconds?: number | null) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return 'Berechne Restzeit'
  if (seconds < 1) return 'weniger als 1 Sek. verbleibend'
  const rounded = Math.ceil(seconds)
  const mins = Math.floor(rounded / 60)
  const secs = rounded % 60
  if (mins <= 0) return `${secs} Sek. verbleibend`
  const hours = Math.floor(mins / 60)
  const restMins = mins % 60
  if (hours > 0) return `${hours} Std. ${restMins} Min. verbleibend`
  return `${mins} Min. ${String(secs).padStart(2, '0')} Sek. verbleibend`
}

function expirySeconds(expiresAt?: string | null, now = Date.now()) {
  if (!expiresAt) return null
  const target = new Date(expiresAt).getTime()
  if (!Number.isFinite(target)) return null
  return Math.max(0, Math.ceil((target - now) / 1000))
}

function formatExpiry(expiresAt?: string | null, now = Date.now()) {
  const seconds = expirySeconds(expiresAt, now)
  if (seconds === null) return 'Löschzeit unbekannt'
  if (seconds <= 0) return 'Wird gelöscht'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  if (days > 0) return `Löscht in ${days} T ${hours} Std.`
  return `Löscht in ${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function estimateEta(loaded: number, total: number | undefined, startedAt: number) {
  if (!total || loaded <= 0) return null
  const elapsedSeconds = (Date.now() - startedAt) / 1000
  if (elapsedSeconds <= 0) return null
  const bytesPerSecond = loaded / elapsedSeconds
  if (bytesPerSecond <= 0) return null
  return Math.max(0, (total - loaded) / bytesPerSecond)
}

function ProgressMeter({
  progress,
  label,
  eta,
  indeterminate,
}: {
  progress?: number | null
  label: string
  eta?: string | null
  indeterminate?: boolean
}) {
  const safeProgress = Math.max(0, Math.min(100, Math.round(progress ?? 0)))
  return (
    <div className={`progress-meter ${indeterminate ? 'indeterminate' : ''}`} aria-label={indeterminate ? label : `${label}: ${safeProgress}%`}>
      <div className="progress-meta">
        <span>{label}</span>
        <strong>{indeterminate ? 'läuft' : `${safeProgress}%`}</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${safeProgress}%` }} />
      </div>
      {eta ? <small>{eta}</small> : null}
    </div>
  )
}

function inferFamily(file: File | null): MediaFamily {
  if (!file) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  if (file.type === 'application/pdf') return 'pdf'
  if (file.type.startsWith('text/')) return file.name.toLowerCase().endsWith('.csv') ? 'spreadsheet' : 'text'
  if (file.type.includes('wordprocessingml') || file.type.includes('msword') || file.type.includes('opendocument.text')) return 'document'
  if (file.type.includes('spreadsheetml') || file.type.includes('ms-excel') || file.type.includes('opendocument.spreadsheet')) return 'spreadsheet'
  if (file.type.includes('presentationml') || file.type.includes('ms-powerpoint') || file.type.includes('opendocument.presentation')) return 'presentation'
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (ext && ['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'oga', 'opus', 'aiff', 'aif', 'alac', 'wma'].includes(ext)) return 'audio'
  if (ext && ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tiff', 'tif', 'ico', 'svg', 'heic', 'heif'].includes(ext)) return 'image'
  if (ext && ['docx', 'doc', 'odt', 'rtf'].includes(ext)) return 'document'
  if (ext && ['xlsx', 'xls', 'ods', 'csv'].includes(ext)) return 'spreadsheet'
  if (ext && ['pptx', 'ppt', 'odp'].includes(ext)) return 'presentation'
  if (ext === 'pdf') return 'pdf'
  if (ext && ['txt', 'html', 'htm'].includes(ext)) return 'text'
  return 'video'
}

function fileExt(name?: string | null) {
  const ext = name?.split('.').pop()?.toUpperCase()
  return ext && ext.length <= 6 ? ext : 'MEDIA'
}

function allowedConvertFamilies(sourceFamily: MediaFamily): MediaFamily[] {
  if (sourceFamily === 'video') return ['video', 'audio']
  if (sourceFamily === 'audio') return ['audio']
  if (sourceFamily === 'image') return ['image', 'pdf']
  if (sourceFamily === 'document') return ['document', 'pdf', 'text']
  if (sourceFamily === 'spreadsheet') return ['spreadsheet', 'pdf', 'text']
  if (sourceFamily === 'presentation') return ['presentation', 'pdf']
  if (sourceFamily === 'pdf') return ['pdf', 'text', 'image']
  if (sourceFamily === 'text') return ['text', 'document', 'pdf']
  return [sourceFamily]
}

function canonicalFormatValue(family: MediaFamily, value: string) {
  const normalized = value.toLowerCase()
  if (family === 'image' && normalized === 'jpeg') return 'jpg'
  if (family === 'image' && normalized === 'tif') return 'tiff'
  return normalized
}

function findFormat(catalog: Record<MediaFamily, FormatDef[]>, family: MediaFamily, value: string): FormatDef {
  const normalized = canonicalFormatValue(family, value)
  return catalog[family]?.find((format) => format.value === normalized) || catalog[family]?.[0] || formatCatalog[family][0]
}

function buildCatalogFromOptions(options: OptionsResponse | null, scope: 'download' | 'convert') {
  const serverFormats = options?.[scope]?.formats
  if (!serverFormats) return formatCatalog
  const next = { ...formatCatalog } as Record<MediaFamily, FormatDef[]>
  mediaFamilies.forEach((family) => {
    const allowed = serverFormats[family]
    if (!allowed?.length) return
    const seen = new Set<string>()
    next[family] = allowed.flatMap((value) => {
      const normalized = canonicalFormatValue(family, value)
      if (seen.has(normalized)) return []
      seen.add(normalized)
      return (
        formatCatalog[family].find((format) => format.value === normalized) || {
          family,
          value: normalized,
          label: normalized.toUpperCase(),
          text: 'Vom Server unterstütztes Format',
        }
      )
    })
  })
  return next
}

function FormatPicker({
  catalog,
  families,
  selectedFamily,
  selectedFormat,
  open,
  onOpenChange,
  onSelect,
}: {
  catalog: Record<MediaFamily, FormatDef[]>
  families: MediaFamily[]
  selectedFamily: MediaFamily
  selectedFormat: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (family: MediaFamily, format: string) => void
}) {
  const [query, setQuery] = useState('')
  const [activeFamily, setActiveFamily] = useState<MediaFamily>(selectedFamily)
  const pickerRef = useRef<HTMLDivElement>(null)
  const selected = findFormat(catalog, selectedFamily, selectedFormat)
  const formats = catalog[activeFamily].filter((format) => {
    const haystack = `${format.label} ${format.text}`.toLowerCase()
    return haystack.includes(query.toLowerCase())
  })

  useEffect(() => {
    if (!families.includes(activeFamily)) setActiveFamily(families[0])
  }, [families, activeFamily])

  useEffect(() => {
    if (!open) return

    const closeOnOutsidePointerDown = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) onOpenChange(false)
    }

    document.addEventListener('pointerdown', closeOnOutsidePointerDown)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointerDown)
  }, [open, onOpenChange])

  return (
    <div className="format-picker" ref={pickerRef}>
      <button
        className="format-button"
        type="button"
        onClick={() => {
          if (!open) setActiveFamily(families.includes(selectedFamily) ? selectedFamily : families[0])
          onOpenChange(!open)
        }}
      >
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
              <option value="libaom-av1">AV1</option>
              <option value="libsvtav1">AV1 / SVT</option>
              <option value="librav1e">AV1 / rav1e</option>
              <option value="libvpx">VP8</option>
              <option value="libvpx-vp9">VP9</option>
              <option value="mpeg4">MPEG-4 Part 2</option>
              <option value="libxvid">Xvid</option>
              <option value="mpeg2video">MPEG-2</option>
              <option value="msmpeg4v3">MS MPEG-4</option>
            </select>
          </label>
          <label className="field">
            <span>Audio-Codec</span>
            <select value={values.audio_codec} onChange={(event) => update('audio_codec', event.target.value)}>
              <option value="">Automatisch</option>
              <option value="aac">AAC</option>
              <option value="libopus">Opus</option>
              <option value="libmp3lame">MP3</option>
              <option value="libvorbis">Vorbis</option>
              <option value="mp2">MP2</option>
              <option value="alac">ALAC</option>
              <option value="wmav2">WMA</option>
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
              <option value="libvorbis">Vorbis</option>
              <option value="flac">FLAC</option>
              <option value="alac">ALAC</option>
              <option value="wmav2">WMA</option>
              <option value="pcm_s16le">PCM WAV</option>
              <option value="pcm_s16be">PCM AIFF</option>
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
  catalog,
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
  catalog: Record<MediaFamily, FormatDef[]>
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
          catalog={catalog}
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
  onDelete,
  onExtend,
  onTerminal,
  now,
}: {
  job: Job | null
  onDownload: (job: Job) => void
  onDelete: (job: Job) => void
  onExtend: (job: Job) => void
  onTerminal: () => void
  now: number
}) {
  const [log, setLog] = useState<string>('')
  const [logOpen, setLogOpen] = useState(false)
  const [status, setStatus] = useState<string>('')
  const [progress, setProgress] = useState<number>(0)
  const [currentStep, setCurrentStep] = useState<string | null>(null)
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
    setProgress(job.progress ?? 0)
    setCurrentStep(job.current_step || null)
    setLogOpen(false)

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
                if (payload.progress !== undefined) setProgress(Number(payload.progress) || 0)
                if (payload.current_step !== undefined) setCurrentStep(payload.current_step || null)
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

  const isDownloadable = job.status === 'success' && !!job.output_path

  return (
    <section className="panel job-detail">
      <div className="panel-header compact">
        <div>
          <p className="eyebrow">Details</p>
          <h2>Auftrag #{job.id}</h2>
        </div>
        <div className="detail-actions">
          <StatusBadge status={status || job.status} />
          {isDownloadable ? (
            <button className="button primary" type="button" onClick={() => onDownload(job)}>
              Herunterladen
            </button>
          ) : null}
          {isDownloadable ? (
            <button className="button secondary" type="button" onClick={() => onExtend(job)}>
              Verlängern
            </button>
          ) : null}
          {job.output_path || ['success', 'failed', 'expired'].includes((job.status || '').toLowerCase()) ? (
            <button className="button ghost" type="button" onClick={() => onDelete(job)}>
              Löschen
            </button>
          ) : null}
        </div>
      </div>
      <div className="detail-meta">
        <span>{job.type === 'convert' ? 'Konvertierung' : 'Download'}</span>
        <span>{currentStep || job.current_step || (job.output_path ? fallbackDownloadName(job) : 'Wartet auf Verarbeitung')}</span>
        {isDownloadable ? <span>{formatExpiry(job.expires_at, now)}</span> : null}
      </div>
      <div className="detail-progress">
        <ProgressMeter
          progress={progress || job.progress || 0}
          label={(currentStep || job.current_step || status || job.status || 'Status').toString()}
          eta={null}
        />
      </div>
      <button className="button secondary detail-toggle" type="button" onClick={() => setLogOpen((open) => !open)}>
        {logOpen ? 'Details / Log ausblenden' : 'Details / Log anzeigen'}
      </button>
      {logOpen ? <pre ref={logRef} className="log-panel">{log || 'Noch keine Logs vorhanden.'}</pre> : null}
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
  const [transfer, setTransfer] = useState<TransferState | null>(null)
  const [downloadCatalog, setDownloadCatalog] = useState<Record<MediaFamily, FormatDef[]>>(formatCatalog)
  const [convertCatalog, setConvertCatalog] = useState<Record<MediaFamily, FormatDef[]>>(formatCatalog)
  const [now, setNow] = useState(Date.now())
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedId) || null, [jobs, selectedId])
  const finishedJobs = useMemo(() => jobs.filter((job) => job.status === 'success' && job.output_path), [jobs])
  const activeJobs = useMemo(
    () => jobs.filter((job) => ['queued', 'running'].includes((job.status || '').toLowerCase())).length,
    [jobs],
  )
  const convertFamilies = allowedConvertFamilies(sourceFamily)
  const visibleConvertCatalog = useMemo(() => {
    if (sourceFamily !== 'image') return convertCatalog
    return {
      ...convertCatalog,
      pdf: convertCatalog.pdf.filter((format) => format.value === 'pdf'),
    }
  }, [convertCatalog, sourceFamily])
  const activeQuality = activeTab === 'download' ? downloadQualityPreset : convertQualityPreset
  const activeWarningFamily = activeTab === 'download' ? downloadFamily : convertFamily

  const loadJobs = useCallback(async () => {
    try {
      const r = await fetch('/api/jobs')
      if (!r.ok) {
        setJobs([])
        return
      }
      const d = await r.json()
      setJobs(Array.isArray(d) ? d.filter((job) => !['expired', 'deleted'].includes((job.status || '').toLowerCase())) : [])
    } catch (e) {
      setJobs([])
    }
  }, [])

  useEffect(() => {
    loadJobs()
  }, [loadJobs])

  useEffect(() => {
    fetch('/api/options')
      .then((r) => (r.ok ? r.json() : null))
      .then((data: OptionsResponse | null) => {
        setDownloadCatalog(buildCatalogFromOptions(data, 'download'))
        setConvertCatalog(buildCatalogFromOptions(data, 'convert'))
      })
      .catch(() => {
        setDownloadCatalog(formatCatalog)
        setConvertCatalog(formatCatalog)
      })
  }, [])

  useEffect(() => {
    const interval = window.setInterval(loadJobs, 5000)
    return () => window.clearInterval(interval)
  }, [loadJobs])

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!transfer?.jobId || transfer.phase === 'download') return
    const job = jobs.find((item) => item.id === transfer.jobId)
    if (!job) return
    if (terminalStatuses.includes((job.status || '').toLowerCase())) {
      setTransfer(null)
      return
    }
    setTransfer((current) => {
      if (!current || current.jobId !== job.id || current.phase === 'download') return current
      const nextProgress = job.progress || current.progress
      const nextLabel = `${job.type === 'convert' ? 'Konvertierung' : 'Download'}: Auftrag #${job.id}`
      if (current.progress === nextProgress && current.label === nextLabel) return current
      return {
        ...current,
        progress: nextProgress,
        label: nextLabel,
      }
    })
  }, [jobs, transfer])

  useEffect(() => {
    const allowed = downloadCatalog[downloadFamily].map((format) => format.value)
    if (!allowed.includes(downloadFormat)) {
      setDownloadFormat(downloadCatalog[downloadFamily][0].value)
    }
  }, [downloadFamily, downloadFormat, downloadCatalog])

  useEffect(() => {
    const nextSource = inferFamily(selectedFile)
    setSourceFamily(nextSource)
    const allowed = allowedConvertFamilies(nextSource)
    const nextFamily = allowed.includes(convertFamily) ? convertFamily : allowed[0]
    setConvertFamily(nextFamily)
    if (!visibleConvertCatalog[nextFamily].some((format) => format.value === convertFormat)) {
      setConvertFormat(visibleConvertCatalog[nextFamily][0].value)
    }
  }, [selectedFile, convertFamily, convertFormat, convertCatalog, visibleConvertCatalog])

  useEffect(() => {
    if (!convertFamilies.includes(convertFamily)) {
      setConvertFamily(convertFamilies[0])
      setConvertFormat(visibleConvertCatalog[convertFamilies[0]][0].value)
      return
    }
    if (!visibleConvertCatalog[convertFamily].some((format) => format.value === convertFormat)) {
      setConvertFormat(visibleConvertCatalog[convertFamily][0].value)
    }
  }, [convertFamily, convertFormat, convertFamilies, visibleConvertCatalog])

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
        setTransfer({
          phase: 'convert',
          jobId: created.id,
          loaded: 0,
          startedAt: Date.now(),
          progress: created.progress || 0,
          etaSeconds: null,
          label: `Download: Auftrag #${created.id}`,
        })
        loadJobs()
      } else if (r.status === 409) {
        const data = await r.json().catch(() => null)
        setTransfer(null)
        setPendingAction('download')
        setPendingWarning(data?.detail?.warning || data?.warning || compressionWarning || 'Qualitätswarnung')
      } else {
        setTransfer(null)
        setMessage('Download konnte nicht gestartet werden.')
      }
    } catch (e) {
      setTransfer(null)
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
      const startedAt = Date.now()
      setTransfer({
        phase: 'upload',
        loaded: 0,
        total: selectedFile.size,
        startedAt,
        progress: 0,
        etaSeconds: null,
        label: `Upload: ${selectedFile.name}`,
      })
      const xhrResult = await new Promise<{ status: number; body: any }>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `/api/jobs/convert-upload${suffix}`)
        xhr.upload.onprogress = (event) => {
          const total = event.lengthComputable ? event.total : selectedFile.size
          const loaded = event.loaded
          const complete = total > 0 && loaded >= total
          setTransfer({
            phase: 'upload',
            loaded,
            total,
            startedAt,
            progress: total ? Math.round((loaded / total) * 100) : 0,
            etaSeconds: complete ? 0 : estimateEta(loaded, total, startedAt),
            label: complete ? 'Upload wird verarbeitet' : `Upload: ${selectedFile.name}`,
          })
        }
        xhr.onload = () => {
          setTransfer((current) => current?.phase === 'upload' ? {
            ...current,
            progress: 100,
            etaSeconds: 0,
            label: 'Upload wird verarbeitet',
          } : current)
          let body: any = null
          try {
            body = xhr.responseText ? JSON.parse(xhr.responseText) : null
          } catch (e) {
            body = null
          }
          resolve({ status: xhr.status, body })
        }
        xhr.onerror = () => reject(new Error('upload_failed'))
        xhr.send(data)
      })
      if (xhrResult.status >= 200 && xhrResult.status < 300) {
        const created = xhrResult.body
        setSelectedFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
        setPendingWarning(null)
        setMessage(`Konvertierung gestartet: Auftrag #${created.id}`)
        setSelectedId(created.id)
        setTransfer({
          phase: 'convert',
          jobId: created.id,
          loaded: 0,
          startedAt: Date.now(),
          progress: created.progress || 0,
          etaSeconds: null,
          label: `Konvertierung: Auftrag #${created.id}`,
        })
        loadJobs()
      } else if (xhrResult.status === 409) {
        const warning = xhrResult.body
        setTransfer(null)
        setPendingAction('convert')
        setPendingWarning(warning?.detail?.warning || warning?.warning || compressionWarning || 'Qualitätswarnung')
      } else if (xhrResult.status === 413) {
        setTransfer(null)
        setMessage('Die Datei ist größer als das erlaubte Upload-Limit.')
      } else {
        setTransfer(null)
        setMessage('Konvertierung konnte nicht gestartet werden.')
      }
    } catch (e) {
      setTransfer(null)
      setMessage('Konvertierung konnte nicht gestartet werden.')
    }
  }

  const downloadJob = async (job: Job) => {
    try {
      const startedAt = Date.now()
      setTransfer({
        phase: 'download',
        jobId: job.id,
        loaded: 0,
        startedAt,
        progress: 0,
        etaSeconds: null,
        indeterminate: true,
        label: `Download: Auftrag #${job.id}`,
      })
      const r = await fetch(`/api/jobs/${job.id}/download`)
      if (!r.ok) {
        setTransfer(null)
        setMessage('Datei ist noch nicht herunterladbar.')
        return
      }
      const totalHeader = r.headers.get('Content-Length')
      const total = totalHeader ? Number(totalHeader) : undefined
      let blob: Blob
      if (r.body) {
        const reader = r.body.getReader()
        const chunks: BlobPart[] = []
        let loaded = 0
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          if (value) {
            chunks.push(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer)
            loaded += value.length
            setTransfer({
              phase: 'download',
              jobId: job.id,
              loaded,
              total,
              startedAt,
              progress: total ? Math.round((loaded / total) * 100) : 0,
              etaSeconds: estimateEta(loaded, total, startedAt),
              indeterminate: !total,
              label: `Download: Auftrag #${job.id}`,
            })
          }
        }
        blob = new Blob(chunks, { type: r.headers.get('Content-Type') || 'application/octet-stream' })
      } else {
        blob = await r.blob()
      }
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = filenameFromDisposition(r.headers.get('Content-Disposition')) || fallbackDownloadName(job)
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
      setTransfer({
        phase: 'download',
        jobId: job.id,
        loaded: total || blob.size,
        total: total || blob.size,
        startedAt,
        progress: 100,
        etaSeconds: 0,
        indeterminate: false,
        label: `Download: Auftrag #${job.id}`,
      })
      window.setTimeout(() => setTransfer((current) => (current?.phase === 'download' && current.jobId === job.id ? null : current)), 1800)
    } catch (e) {
      setTransfer(null)
      setMessage('Download der fertigen Datei fehlgeschlagen.')
    }
  }

  const extendJob = async (job: Job) => {
    try {
      const r = await fetch(`/api/jobs/${job.id}/extend`, { method: 'POST' })
      if (!r.ok) {
        setMessage('Auftrag konnte nicht verlängert werden.')
        return
      }
      const updated = await r.json()
      setJobs((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setMessage(`Auftrag #${job.id} wurde um 24h verlängert.`)
    } catch (e) {
      setMessage('Auftrag konnte nicht verlängert werden.')
    }
  }

  const deleteJob = async (job: Job) => {
    try {
      const r = await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' })
      if (!r.ok) {
        setMessage('Auftrag konnte nicht gelöscht werden.')
        return
      }
      setJobs((current) => current.filter((item) => item.id !== job.id))
      setSelectedId((current) => (current === job.id ? null : current))
      setMessage(`Auftrag #${job.id} wurde gelöscht.`)
    } catch (e) {
      setMessage('Auftrag konnte nicht gelöscht werden.')
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
                  catalog={downloadCatalog}
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
                    <span>{selectedFile ? `${formatBytes(selectedFile.size)} - ${familyLabels[sourceFamily]} erkannt` : 'Audio, Video, Bild oder Dokument hochladen'}</span>
                  </label>
                </div>
                <ConversionCard
                  catalog={visibleConvertCatalog}
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
            {transfer ? (
              <div className="transfer-progress">
                <ProgressMeter
                  progress={transfer.progress}
                  label={transfer.label}
                  eta={transfer.phase === 'convert' ? 'Restzeit wird im Auftrag berechnet' : formatEta(transfer.etaSeconds)}
                  indeterminate={transfer.indeterminate}
                />
              </div>
            ) : null}
            {message ? <div className="message">{message}</div> : null}
          </section>

          <JobDetail job={selectedJob} onDownload={downloadJob} onDelete={deleteJob} onExtend={extendJob} onTerminal={loadJobs} now={now} />
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
                      {['queued', 'running'].includes((job.status || '').toLowerCase()) ? (
                        <span className="list-progress" aria-label={`Fortschritt ${job.progress || 0}%`}>
                          <i
                            className={(job.progress || 0) <= 0 ? 'indeterminate' : ''}
                            style={{ width: `${Math.max(0, Math.min(100, job.progress || 0))}%` }}
                          />
                        </span>
                      ) : null}
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
                      <small>{formatExpiry(job.expires_at, now)}</small>
                    </span>
                    <button className="button secondary" type="button" onClick={() => downloadJob(job)}>Download</button>
                    <button className="button secondary" type="button" onClick={() => extendJob(job)}>Verlängern</button>
                    <button className="button ghost" type="button" onClick={() => deleteJob(job)}>Löschen</button>
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


