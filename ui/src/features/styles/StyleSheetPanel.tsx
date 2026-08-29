import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Download,
  ExternalLink,
  Film,
  Loader2,
  Palette,
  Search,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import {
  cancelStyleImport,
  deleteStyle,
  fetchStyleImport,
  fetchStyleLibrary,
  fetchStyleSources,
  startMiniMaxStyleImport,
  type StyleImportJob,
  type StyleLibraryItem,
  type StyleLibraryPage,
  type StyleSource,
} from '../../api/client'


const PAGE_SIZE = 60

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)))
  return `${(value / 1024 ** exponent).toFixed(exponent >= 3 ? 2 : 1)} ${units[exponent]}`
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

function SourceAttribution({ source }: { source: StyleSource }) {
  return (
    <div className="rounded-xl border border-border bg-bg-secondary p-3 md:p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">{source.name}</span>
            <span className="rounded-full border border-border bg-bg-tertiary px-2 py-0.5 text-[10px] text-text-muted">
              {source.styleCount.toLocaleString()} estilos instalados
            </span>
            {source.revision && (
              <span className="font-mono text-[10px] text-text-muted" title={source.revision}>
                rev. {source.revision.slice(0, 10)}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-text-secondary">{source.description}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-text-muted">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-accent-blue hover:underline"
            >
              Fuente: {source.repoId} · Hugging Face <ExternalLink size={10} />
            </a>
            <span>Autor: {source.author}</span>
            <span>{formatBytes(source.expectedBytes)}</span>
            <span className="inline-flex items-center gap-1 text-indicator-warning">
              <AlertTriangle size={10} /> {source.license || source.licenseNotice || 'Licencia no especificada'}
            </span>
            {source.storagePath && (
              <span className="max-w-full truncate font-mono" title={source.storagePath}>
                Storage: {source.storagePath}
              </span>
            )}
          </div>
          {source.storageNotice && <p className="mt-2 text-[10px] text-accent-blue">{source.storageNotice}</p>}
        </div>
      </div>
    </div>
  )
}

function ImportProgress({
  job,
  onCancel,
  cancelling,
}: {
  job: StyleImportJob
  onCancel: () => void
  cancelling: boolean
}) {
  const usingBytes = job.stage === 'downloading' && job.expectedBytes > 0
  const ratio = usingBytes
    ? job.downloadedBytes / job.expectedBytes
    : (job.total > 0 ? job.current / job.total : 0)
  const progress = Math.max(0, Math.min(100, ratio * 100))
  const active = ['queued', 'running', 'cancelling'].includes(job.status)
  const attention = ['failed', 'cancelled', 'interrupted'].includes(job.status)
  return (
    <div className={`rounded-xl border p-3 ${attention ? 'border-indicator-warning/40 bg-indicator-warning/5' : 'border-accent-blue/30 bg-accent-blue/5'}`}>
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="flex min-w-0 items-center gap-2 text-text-secondary">
          {attention ? <AlertTriangle size={13} className="text-indicator-warning" /> : active ? <Loader2 size={13} className="animate-spin text-accent-blue" /> : <Check size={13} className="text-accent-green" />}
          <span className="truncate">{job.message}</span>
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-[10px] text-text-muted">
            {usingBytes ? `${formatBytes(job.downloadedBytes)} / ${formatBytes(job.expectedBytes)}` : `${job.current} / ${job.total}`}
          </span>
          {active && (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling || job.status === 'cancelling'}
              className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-[10px] text-red-300 hover:bg-red-500/10 disabled:opacity-50"
            >
              {cancelling || job.status === 'cancelling' ? <Loader2 size={10} className="animate-spin" /> : <Square size={9} />}
              Cancelar
            </button>
          )}
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg-tertiary">
        <div className="h-full rounded-full bg-accent-blue transition-all" style={{ width: `${progress}%` }} />
      </div>
      {job.error && <p className="mt-2 text-[11px] text-red-300">{job.error}</p>}
      {job.preflight && (
        <p className="mt-2 text-[10px] text-text-muted">
          Libre: {formatBytes(job.preflight.freeBytes)} · Necesario ahora: {formatBytes(job.preflight.requiredBytes)}
          {job.resumed ? ` · Reanudación ${job.resumeCount || 1}` : ''}
        </p>
      )}
    </div>
  )
}

function StyleCard({
  style,
  onOpen,
  onDelete,
}: {
  style: StyleLibraryItem
  onOpen: (style: StyleLibraryItem) => void
  onDelete: (style: StyleLibraryItem) => void
}) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async (event: React.MouseEvent) => {
    event.stopPropagation()
    await copyText(style.prompt)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }
  return (
    <article
      className="group overflow-hidden rounded-xl border border-border bg-bg-secondary transition-colors hover:border-accent-blue/50"
    >
      <button type="button" className="block w-full text-left" onClick={() => onOpen(style)}>
        <div className="relative aspect-video bg-black">
          <img
            src={style.previewUrl}
            alt={`Preview ${style.title}`}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-contain"
          />
          <span className="absolute left-2 top-2 rounded-md bg-black/75 px-1.5 py-1 font-mono text-[9px] text-white">
            #{String(style.sourceOrder).padStart(4, '0')}
          </span>
          <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition-all group-hover:bg-black/25 group-hover:opacity-100">
            <span className="flex h-11 w-11 items-center justify-center rounded-full border border-white/30 bg-black/65"><Film size={18} /></span>
          </span>
        </div>
        <div className="p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="truncate text-xs font-medium text-text-primary">{style.title}</h3>
            <span className="shrink-0 rounded-full bg-bg-tertiary px-2 py-0.5 text-[9px] text-text-muted">{style.group}</span>
          </div>
          <p className="mt-2 line-clamp-4 text-[11px] leading-relaxed text-text-secondary" title={style.prompt}>{style.prompt}</p>
          <p className="mt-2 truncate text-[9px] text-text-muted" title={style.source.url}>Fuente: {style.source.repoId}</p>
        </div>
      </button>
      <div className="flex items-center gap-1 border-t border-border px-2 py-1.5">
        <button
          type="button"
          onClick={handleCopy}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[10px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
        >
          {copied ? <Check size={12} className="text-accent-green" /> : <Clipboard size={12} />}
          {copied ? 'Copiado' : 'Copiar prompt'}
        </button>
        <button
          type="button"
          onClick={() => onDelete(style)}
          className="rounded-lg p-1.5 text-text-muted hover:bg-red-500/10 hover:text-red-400"
          title="Eliminar estilo"
          aria-label={`Eliminar ${style.title}`}
        >
          <Trash2 size={12} />
        </button>
      </div>
    </article>
  )
}

export function StyleSheetPanel() {
  const [sources, setSources] = useState<StyleSource[]>([])
  const [page, setPage] = useState<StyleLibraryPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [collection, setCollection] = useState('')
  const [group, setGroup] = useState('')
  const [sort, setSort] = useState('source_order')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<StyleLibraryItem | null>(null)
  const [deleteCandidate, setDeleteCandidate] = useState<StyleLibraryItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [importJob, setImportJob] = useState<StyleImportJob | null>(null)
  const [startingImport, setStartingImport] = useState(false)
  const [cancellingImport, setCancellingImport] = useState(false)
  const [modalCopied, setModalCopied] = useState(false)

  const source = sources.find(item => item.id === 'huggingface:ostris/minimax_h3_1k')

  const loadSources = useCallback(async () => {
    const next = await fetchStyleSources()
    setSources(next)
    const matchingSource = next.find(item => item.id === 'huggingface:ostris/minimax_h3_1k')
    const visibleJob = matchingSource?.activeJob || matchingSource?.latestJob
    if (visibleJob) setImportJob(visibleJob)
  }, [])

  const loadStyles = useCallback(async () => {
    const result = await fetchStyleLibrary({
      modelFamily: 'minimax',
      collection: collection || undefined,
      group: group || undefined,
      query: query || undefined,
      sort,
      offset,
      limit: PAGE_SIZE,
    })
    setPage(result)
  }, [collection, group, offset, query, sort])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setOffset(0)
      setQuery(queryInput.trim())
    }, 300)
    return () => window.clearTimeout(timer)
  }, [queryInput])

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([loadSources(), loadStyles()])
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [loadSources, loadStyles])

  const importJobId = importJob?.jobId
  const importJobStatus = importJob?.status
  useSerializedPoll({
    enabled: Boolean(importJobId && importJobStatus && ['queued', 'running', 'cancelling'].includes(importJobStatus)),
    intervalMs: 1500,
    ownerKey: importJobId,
    poll: () => fetchStyleImport(importJobId!),
    onValue: next => {
      setImportJob(next)
      if (next.stage === 'previews' || ['completed', 'failed', 'interrupted', 'cancelled'].includes(next.status)) {
        void Promise.all([loadSources(), loadStyles()])
      }
    },
    onError: err => setError(err instanceof Error ? err.message : String(err)),
  })

  const startImport = async () => {
    setStartingImport(true)
    setError(null)
    try {
      const job = await startMiniMaxStyleImport()
      setImportJob(job)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStartingImport(false)
    }
  }

  const cancelImport = async () => {
    if (!importJob || !['queued', 'running', 'cancelling'].includes(importJob.status)) return
    setCancellingImport(true)
    setError(null)
    try {
      setImportJob(await cancelStyleImport(importJob.jobId))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCancellingImport(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleteCandidate) return
    setDeleting(true)
    setError(null)
    try {
      await deleteStyle(deleteCandidate.id)
      if (selected?.id === deleteCandidate.id) setSelected(null)
      setDeleteCandidate(null)
      await Promise.all([loadSources(), loadStyles()])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  const pageNumber = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((page?.total || 0) / PAGE_SIZE))
  const collections = page?.facets.collections || []
  const groups = page?.facets.groups || []
  const importBusy = !!importJob && ['queued', 'running', 'cancelling'].includes(importJob.status)
  const sourceLabel = importJob?.resumeAvailable
    ? 'Reanudar descarga de estilos'
    : source?.installed ? 'Sincronizar fuente' : 'Descargar estilos de ostris/minimax_h3_1k'

  const activeFilters = useMemo(() => [collection, group, query].filter(Boolean).length, [collection, group, query])

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-bg-primary">
      <header className="border-b border-border bg-bg-secondary px-3 py-3 md:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Palette size={17} className="text-accent-blue" />
              <h1 className="text-base font-semibold text-text-primary">Hoja de estilos</h1>
            </div>
            <p className="mt-1 text-xs text-text-muted">Biblioteca visual de prompts con ejemplos reproducibles y fuente trazable.</p>
          </div>
          <button
            type="button"
            onClick={startImport}
            disabled={startingImport || importBusy}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-blue px-3 py-2 text-xs font-medium text-white hover:bg-accent-blue-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {startingImport || importBusy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            {sourceLabel}
          </button>
        </div>
        <div className="mt-3 flex gap-1" role="tablist" aria-label="Modelos de hoja de estilos">
          <button type="button" role="tab" aria-selected="true" className="rounded-lg bg-bg-active px-3 py-1.5 text-xs font-medium text-text-primary">
            MiniMax
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 md:p-5">
        <div className="space-y-3">
          {source && <SourceAttribution source={source} />}
          {importJob && importJob.status !== 'completed' && (
            <ImportProgress job={importJob} onCancel={() => { void cancelImport() }} cancelling={cancellingImport} />
          )}
          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-300">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
            </div>
          )}

          <div className="sticky top-0 z-10 rounded-xl border border-border bg-bg-secondary/95 p-2.5 backdrop-blur">
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_180px_180px_170px_auto]">
              <label className="flex items-center gap-2 rounded-lg border border-border bg-bg-primary px-2.5">
                <Search size={13} className="text-text-muted" />
                <input
                  value={queryInput}
                  onChange={event => setQueryInput(event.target.value)}
                  placeholder="Buscar en prompts, nombres o tags…"
                  className="min-w-0 flex-1 bg-transparent py-2 text-xs text-text-primary outline-none placeholder:text-text-muted"
                />
                {queryInput && <button type="button" onClick={() => setQueryInput('')} className="text-text-muted hover:text-text-primary"><X size={12} /></button>}
              </label>
              <select value={collection} onChange={event => { setCollection(event.target.value); setOffset(0) }} className="rounded-lg border border-border bg-bg-primary px-2.5 py-2 text-xs text-text-secondary">
                <option value="">Todas las colecciones</option>
                {collections.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
              <select value={group} onChange={event => { setGroup(event.target.value); setOffset(0) }} className="rounded-lg border border-border bg-bg-primary px-2.5 py-2 text-xs text-text-secondary">
                <option value="">Todos los grupos</option>
                {groups.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
              <select value={sort} onChange={event => { setSort(event.target.value); setOffset(0) }} className="rounded-lg border border-border bg-bg-primary px-2.5 py-2 text-xs text-text-secondary">
                <option value="source_order">Orden de la fuente</option>
                <option value="newest">Más recientes</option>
                <option value="oldest">Más antiguos</option>
                <option value="prompt_asc">Prompt A → Z</option>
                <option value="prompt_desc">Prompt Z → A</option>
              </select>
              <div className="flex items-center justify-end gap-2 px-1 text-[10px] text-text-muted">
                {activeFilters > 0 && <span>{activeFilters} filtros</span>}
                <span>{(page?.total || 0).toLocaleString()} estilos</span>
              </div>
            </div>
          </div>

          {loading ? (
            <div className="flex min-h-[260px] items-center justify-center gap-2 text-xs text-text-muted"><Loader2 size={17} className="animate-spin" /> Cargando estilos…</div>
          ) : page && page.styles.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {page.styles.map(style => <StyleCard key={style.id} style={style} onOpen={setSelected} onDelete={setDeleteCandidate} />)}
            </div>
          ) : (
            <div className="flex min-h-[300px] flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-bg-secondary px-6 text-center">
              <Palette size={30} className="text-text-muted" />
              <h2 className="mt-3 text-sm font-medium text-text-primary">Aún no hay estilos MiniMax instalados</h2>
              <p className="mt-1 max-w-lg text-xs text-text-muted">Descarga la fuente de Hugging Face para importar sus 1.000 prompts, vídeos y previews ligeras.</p>
            </div>
          )}

          {page && page.total > 0 && (
            <div className="flex items-center justify-center gap-3 py-3">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="rounded-lg border border-border p-2 text-text-secondary hover:bg-bg-hover disabled:opacity-30" aria-label="Página anterior"><ChevronLeft size={14} /></button>
              <span className="text-[11px] text-text-muted">Página {pageNumber} de {pageCount}</span>
              <button type="button" disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)} className="rounded-lg border border-border p-2 text-text-secondary hover:bg-bg-hover disabled:opacity-30" aria-label="Página siguiente"><ChevronRight size={14} /></button>
            </div>
          )}
        </div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-3 md:p-8" onClick={() => setSelected(null)}>
          <div className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border bg-bg-secondary shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="min-w-0"><h2 className="truncate text-sm font-semibold text-text-primary">{selected.title}</h2><p className="mt-0.5 truncate text-[10px] text-text-muted">Fuente: {selected.source.repoId} · #{selected.sourceOrder}</p></div>
              <button type="button" onClick={() => setSelected(null)} className="rounded-lg p-2 text-text-muted hover:bg-bg-hover hover:text-text-primary"><X size={16} /></button>
            </div>
            <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.85fr)]">
              <div className="flex min-h-[260px] items-center justify-center bg-black">
                <video key={selected.videoUrl} src={selected.videoUrl} poster={selected.previewUrl} controls autoPlay preload="metadata" className="max-h-[72vh] w-full object-contain" />
              </div>
              <div className="min-h-0 overflow-y-auto border-t border-border p-4 lg:border-l lg:border-t-0">
                <div className="flex flex-wrap gap-1.5">{selected.tags.map(tag => <span key={tag} className="rounded-full bg-bg-tertiary px-2 py-1 text-[9px] text-text-muted">{tag}</span>)}</div>
                <p className="mt-4 whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{selected.prompt}</p>
                <div className="mt-4 space-y-2 border-t border-border pt-4 text-[10px] text-text-muted">
                  <a href={selected.source.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-accent-blue hover:underline">Ver fuente original <ExternalLink size={10} /></a>
                  <p>Autor: {selected.source.author}</p>
                  <p>Revisión: <span className="font-mono">{selected.source.revision || 'no registrada'}</span></p>
                  <p className="text-indicator-warning">{selected.source.license || selected.source.licenseNotice}</p>
                </div>
                <button type="button" onClick={() => { void copyText(selected.prompt).then(() => { setModalCopied(true); window.setTimeout(() => setModalCopied(false), 1400) }) }} className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-accent-blue px-3 py-2 text-xs font-medium text-white hover:bg-accent-blue-hover">
                  {modalCopied ? <Check size={14} /> : <Clipboard size={14} />} {modalCopied ? 'Prompt copiado' : 'Copiar prompt'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {deleteCandidate && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/70 p-4" onClick={() => !deleting && setDeleteCandidate(null)}>
          <div className="w-full max-w-md rounded-2xl border border-red-500/30 bg-bg-secondary p-5 shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="flex items-start gap-3"><div className="rounded-full bg-red-500/10 p-2 text-red-400"><Trash2 size={18} /></div><div><h2 className="text-sm font-semibold text-text-primary">¿Eliminar este estilo?</h2><p className="mt-1 text-xs text-text-muted">Se eliminarán su prompt, vídeo y preview locales. Las sincronizaciones posteriores respetarán esta decisión y no lo restaurarán automáticamente.</p><p className="mt-2 truncate text-[10px] text-text-secondary">{deleteCandidate.title}</p></div></div>
            <div className="mt-5 flex justify-end gap-2"><button type="button" disabled={deleting} onClick={() => setDeleteCandidate(null)} className="rounded-lg border border-border px-3 py-2 text-xs text-text-secondary hover:bg-bg-hover">Cancelar</button><button type="button" disabled={deleting} onClick={confirmDelete} className="flex items-center gap-2 rounded-lg bg-red-500 px-3 py-2 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50">{deleting && <Loader2 size={13} className="animate-spin" />} Eliminar</button></div>
          </div>
        </div>
      )}
    </section>
  )
}

export default StyleSheetPanel
