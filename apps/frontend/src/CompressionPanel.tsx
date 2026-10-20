import React, { useRef, useState } from 'react'
import { diagnosticFetch as fetch } from './diagnostics'

type Family = 'video' | 'audio' | 'image' | 'pdf' | 'other'
type Entry = { id: number; file: File; family: Family; output_format: string; quality_preset: string; strip_metadata: boolean; [key: string]: unknown }
const formats: Record<Family, string[]> = { video: ['mp4', 'webm', 'mkv'], audio: ['opus', 'mp3', 'm4a', 'flac'], image: ['webp', 'avif', 'jpg', 'png'], pdf: ['pdf'], other: [] }
const archives = ['zip', 'gz', 'xz']
const office = ['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp', 'docm', 'xlsm', 'pptm', 'epub']
const nativeFormat = (file: File) => office.includes(file.name.split('.').pop()?.toLowerCase() || '') ? file.name.split('.').pop()!.toLowerCase() : null
const labels: Record<Family, string> = { video: 'Video', audio: 'Audio', image: 'Bild', pdf: 'PDF', other: 'Datei / Archiv' }
function family(file: File): Family {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if ('mp4 mkv mov webm avi m4v mpg mpeg flv wmv ogv ts m2ts mts vob 3gp 3g2'.split(' ').includes(ext)) return 'video'
  if ('mp3 m4a aac wav flac ogg oga opus weba mka aiff aif alac wma'.split(' ').includes(ext)) return 'audio'
  if ('jpg jpeg png avif bmp tiff tif ico svg heic heif jp2 j2k jpf jpx tga'.split(' ').includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'other'
}
const bytes = (n: number) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1024).toFixed(1)} KB`

export default function CompressionPanel({ onCreated, jobs }: { onCreated: (ids: number[]) => void; jobs: { id: number; status: string }[] }) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [drag, setDrag] = useState(false)
  const [batch, setBatch] = useState<{ id: string; ids: number[] } | null>(null)
  const [downloading, setDownloading] = useState(false)
  const sequence = useRef(0)
  const fields = useRef<HTMLFieldSetElement>(null)
  const update = (id: number, key: string, value: unknown) => setEntries(items => items.map(item => item.id !== id ? item : key === 'output_format'
    ? { id: item.id, file: item.file, family: item.family, output_format: String(value), quality_preset: item.quality_preset, strip_metadata: false }
    : { ...item, [key]: value }))
  const batchJobs = batch ? jobs.filter(job => batch.ids.includes(job.id)) : []
  const finished = Boolean(batch && batchJobs.length === batch.ids.length && batchJobs.every(job => ['success', 'failed', 'cancelled', 'expired', 'deleted'].includes(job.status)))
  const succeeded = batchJobs.filter(job => job.status === 'success').length
  async function downloadBatch() {
    if (!batch || downloading) return
    setDownloading(true)
    try {
      const response = await fetch(`/api/batches/${encodeURIComponent(batch.id)}/download`)
      if (!response.ok) throw new Error('Das ZIP konnte nicht geladen werden. Bitte erneut versuchen.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url; link.download = 'mediaforge-komprimiert.zip'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Download fehlgeschlagen.') }
    finally { setDownloading(false) }
  }
  function add(files: File[]) {
    setMessage('')
    if (entries.length + files.length > 100) { setMessage('Bitte höchstens 100 Dateien pro Batch auswählen.'); return }
    setEntries(items => [...items, ...files.map(file => {
      const kind = family(file)
      return { id: ++sequence.current, file, family: kind, output_format: (nativeFormat(file) || formats[kind][0] || 'zip'), quality_preset: 'balanced', strip_metadata: false }
    })])
  }
  async function start() {
    if (!entries.length || busy) return
    for (const input of Array.from(fields.current?.querySelectorAll('input') || [])) {
      if (!input.reportValidity()) return
    }
    setBusy(true); setMessage('Dateien werden hochgeladen und geprüft …')
    const form = new FormData()
    form.set('operation', 'compress')
    form.set('settings', JSON.stringify(entries.map(({ file, family: kind, id, ...settings }) => settings)))
    entries.forEach(entry => form.append('files', entry.file))
    try {
      const response = await fetch('/api/jobs/convert-batch', { method: 'POST', body: form })
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Komprimierung konnte nicht gestartet werden.')
      onCreated(result.jobs.map((job: { id: number }) => job.id))
      setBatch({ id: result.batch_id, ids: result.jobs.map((job: { id: number }) => job.id) })
      setEntries([])
      setMessage(`${result.jobs.length} Komprimierungsaufträge gestartet. Ergebnisse erscheinen rechts in der Auftragsliste.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Upload fehlgeschlagen. Bitte erneut versuchen.') }
    finally { setBusy(false) }
  }
  return <div className={`tab-content compression-panel ${entries.length ? 'has-files' : ''}`}>
    <div className="panel-header"><h2>Dateien komprimieren</h2></div>
    <p className="compression-intro">Bilder, Videos, Audio, PDF und Office optimieren oder beliebige Dateien als Archiv speichern.</p>
    <fieldset ref={fields} disabled={busy} className="compression-fieldset">
      <div className="upload-area">
        <input id="compress-upload" type="file" multiple onChange={event => { add(Array.from(event.target.files || [])); event.target.value = '' }} />
        <label htmlFor="compress-upload" className={drag ? 'drag-active' : ''} onDragOver={event => { event.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={event => { event.preventDefault(); setDrag(false); if (!busy) add(Array.from(event.dataTransfer.files)) }}>
          <strong>{entries.length ? 'Weitere Dateien hinzufügen' : 'Dateien auswählen oder hier ablegen'}</strong><span>Bis zu 100 Dateien · Einstellungen für jede Datei einzeln</span>
        </label>
      </div>
      {entries.length > 0 && <div className="compression-summary"><strong>{entries.length} Dateien / {bytes(entries.reduce((sum, entry) => sum + entry.file.size, 0))}</strong><button className="link-button" onClick={() => setEntries([])}>Auswahl leeren</button></div>}
      {entries.map((entry) => {
        const archive = archives.includes(entry.output_format)
        const native = office.includes(entry.output_format)
        const media = !archive && ['audio', 'video', 'image'].includes(entry.family)
        const number = (key: string, title: string, min: number, max: number, placeholder: string) => <label className="field"><span>{title}</span><input type="number" min={min} max={max} placeholder={placeholder} value={String(entry[key] ?? '')} onChange={event => update(entry.id, key, event.target.value)} /></label>
        return <article className="compression-entry" key={entry.id}>
          <div className="compression-file-heading"><div><h3>{entry.file.name}</h3><span>{labels[entry.family]} · {bytes(entry.file.size)}</span></div><button className="button ghost" aria-label={`${entry.file.name} entfernen`} onClick={() => setEntries(items => items.filter(item => item.id !== entry.id))}>Entfernen</button></div>
          <div className="compression-settings">
            <label className="field"><span>Zielformat</span><select value={entry.output_format} onChange={event => update(entry.id, 'output_format', event.target.value)}>{[...(nativeFormat(entry.file) ? [nativeFormat(entry.file)!] : formats[entry.family]), ...archives].map(fmt => <option key={fmt} value={fmt}>{fmt.toUpperCase()}{archives.includes(fmt) ? ' · verlustfreies Archiv' : office.includes(fmt) ? ' · Dokument optimieren' : ''}</option>)}</select></label>
            {archive || native ? <label className="field"><span>Kompressionsstufe</span><select value={String(entry.level || 6)} onChange={event => update(entry.id, 'level', event.target.value)}><option value="1">Schnell · Stufe 1</option><option value="6">Ausgewogen · Stufe 6</option><option value="9">Maximum · Stufe 9</option></select></label> : <label className="field"><span>Qualitätsziel</span><select value={entry.quality_preset} onChange={event => update(entry.id, 'quality_preset', event.target.value)}><option value="high">Originalnah</option><option value="balanced">Ausgewogen</option><option value="small">Kleinste Datei</option></select></label>}
          </div>
          <p className="method-note">{native ? 'Optimiert die interne Paketkomprimierung. Texte, Bilder, Formatierungen und eingebettete Inhalte bleiben erhalten. Bereits optimierte Dokumente werden kaum kleiner.' : archive ? 'Originalinhalt bleibt unverändert. Code und Text eignen sich gut; bei ZIP, JPEG und anderen bereits komprimierten Dateien kann das Archiv größer werden.' : entry.family === 'pdf' ? 'Optimiert eingebettete Bilder. Signaturen und interaktive PDF-Funktionen können verloren gehen. Für unveränderte Dokumente ZIP wählen.' : entry.output_format === 'flac' ? 'Verlustfreies Audio. Bereits verlustbehaftete Quellen gewinnen dadurch keine Qualität zurück.' : 'Neukodierung kann Details verändern. Bilder werden als Einzelbild ausgegeben. Die tatsächliche Ersparnis hängt von der Quelldatei ab.'}</p>
          {!archive && !native && <details className="compression-advanced"><summary>Feineinstellungen</summary><div className="compression-settings">
            {['image', 'video'].includes(entry.family) && number('max_width', 'Maximale Breite (px)', 16, 7680, 'Automatisch')}
            {entry.family === 'video' && <>{number('crf', 'CRF · kleiner = mehr Qualität', 18, 40, 'Automatisch')}{number('max_fps', 'Bildrate (fps)', 1, 120, 'Automatisch')}</>}
            {entry.family === 'image' && number('image_quality', 'Bildqualität (1–100)', 1, 100, 'Automatisch')}
            {['audio', 'video'].includes(entry.family) && entry.output_format !== 'flac' && <label className="field"><span>Audio-Bitrate</span><select value={String(entry.audio_bitrate || '')} onChange={event => update(entry.id, 'audio_bitrate', event.target.value)}><option value="">Automatisch</option>{['48k', '64k', '96k', '128k', '192k', '256k', '320k'].map(rate => <option key={rate}>{rate}</option>)}</select></label>}
            {entry.family === 'audio' && <><label className="field"><span>Kanäle</span><select value={String(entry.audio_channels || '')} onChange={event => update(entry.id, 'audio_channels', event.target.value)}><option value="">Original</option><option value="1">Mono</option><option value="2">Stereo</option></select></label><label className="field"><span>Abtastrate (Hz)</span><select value={String(entry.sample_rate || '')} onChange={event => update(entry.id, 'sample_rate', event.target.value)}><option value="">Automatisch</option>{(entry.output_format === 'opus' ? [8000, 12000, 16000, 24000, 48000] : [8000, 16000, 22050, 24000, 32000, 44100, 48000]).map(rate => <option key={rate}>{rate}</option>)}</select></label></>}
            {entry.family === 'pdf' && number('pdf_dpi', 'Bildauflösung (DPI)', 72, 300, 'Je nach Qualitätsziel')}
            {media && <label className="check-field"><input type="checkbox" checked={entry.strip_metadata} onChange={event => update(entry.id, 'strip_metadata', event.target.checked)} /><span>Metadaten entfernen</span></label>}
          </div></details>}
        </article>
      })}
      <div className="panel-footer"><button className="button primary" disabled={!entries.length || busy} onClick={start}>{busy ? 'Upload läuft …' : `${entries.length || ''} Dateien komprimieren`}</button><span className="muted">Die Originaldateien bleiben unverändert.</span></div>
    </fieldset>
    {batch && <div className="panel-footer"><button className="button secondary" disabled={!finished || !succeeded || downloading} onClick={downloadBatch}>{downloading ? 'ZIP wird geladen …' : finished ? `Batch als ZIP laden (${succeeded})` : `Batch in Arbeit (${succeeded}/${batch.ids.length})`}</button></div>}
    {message && <div className="message" role="status">{message}</div>}
  </div>
}
