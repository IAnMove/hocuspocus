import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'

type Collection = { id: string; download_size: number; size: number; installed: boolean; cached: boolean; archive_size: number; gallery: boolean; dependencies: string[] }
type Job = { id: string; status: string; received: number; total: number; error: string | null }
type Catalog = { collections: Collection[]; job: Job | null }
const bytes = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MiB`

async function request(path: string, options?: RequestInit) {
  const response = await fetch(`/api/v1/examples${path}`, options)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

function selection(catalog: Catalog | undefined, required: string[] | undefined, selected: string) {
  const chosen = required ?? (selected ? [selected] : [])
  const packs = catalog?.collections.filter(p => chosen.includes(p.id)) ?? []
  const ready = chosen.length > 0 && packs.length === chosen.length && packs.every(p => p.installed)
  const needed = new Set(packs.flatMap(p => p.dependencies))
  // Each dependency is counted once across the selection.
  const size = catalog?.collections.filter(p => needed.has(p.id) && !p.cached)
    .reduce((sum, p) => sum + p.archive_size, 0) ?? 0
  return { chosen, packs, ready, size }
}

function DownloadStatus({ job, onError }: { job: Job | null | undefined; onError: () => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  if (job?.status === 'cancelled') return <p role="status">{t('examples.cancelled')}</p>
  if (job?.status !== 'running') return null
  return <div role="status">
    {t('examples.progress', { size: bytes(job.received), total: bytes(job.total) })}
    <button type="button" className="ml-3 underline" onClick={() => void request(`/install/${job.id}`, { method: 'DELETE', headers: { 'X-Hocus-Action': 'install-examples' } }).catch(onError)}>{t('examples.cancel')}</button>
  </div>
}

/** Metadata-only until the user explicitly presses Download. */
export function ExampleDownloads({ required, disabled = false, onInstalled }: {
  required?: string[]; disabled?: boolean; onInstalled?: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [catalog, setCatalog] = useState<Catalog>()
  const [selected, setSelected] = useState('')
  const [error, setError] = useState(false)
  const [starting, setStarting] = useState(false)
  const [retry, setRetry] = useState(0)
  const active = required === undefined || required.length > 0
  const callback = useRef(onInstalled)
  const lastJob = useRef<string | undefined>(undefined)
  useEffect(() => { callback.current = onInstalled }, [onInstalled])
  useEffect(() => {
    if (!active) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try {
        const result = await request('') as Catalog
        if (cancelled) return
        setCatalog(result); setError(false)
        if (result.job?.status === 'complete' && result.job.id !== lastJob.current) {
          if (lastJob.current !== undefined) callback.current?.()
        }
        if (result.job?.status === 'complete') lastJob.current = result.job.id
        else if (lastJob.current === undefined) lastJob.current = ''
      } catch { if (!cancelled) setError(true) }
      if (!cancelled) timer = setTimeout(() => void refresh(), 2000)
    }
    void refresh()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [active, retry])
  if (!active) return null
  const { chosen, packs, ready, size } = selection(catalog, required, selected)
  const busy = starting || catalog?.job?.status === 'running'
  const install = async () => {
    setStarting(true); setError(false)
    try {
      const job = await request('/install', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hocus-Action': 'install-examples' }, body: JSON.stringify({ collections: chosen }) }) as Job
      lastJob.current = ''
      setCatalog(before => before && { ...before, job })
      setRetry(n => n + 1)
    } catch { setError(true) }
    finally { setStarting(false) }
  }
  return <section className="space-y-2 rounded-lg border border-border bg-bg-primary p-3 text-xs" aria-label={t('examples.title')}>
    <p className="font-semibold">{t('examples.title')}</p>
    <p className="text-text-muted">{t('examples.help')}</p>
    {required === undefined ? <select aria-label={t('examples.collection')} value={selected} onChange={event => setSelected(event.target.value)} className="rounded border border-border bg-bg-secondary p-2">
      <option value="">{t('examples.choose')}</option>
      {catalog?.collections.map(p => <option key={p.id} value={p.id}>{p.id} · {bytes(p.download_size)}</option>)}
    </select> : <p>{required.join(', ')}</p>}
    {ready ? <p role="status">{t('examples.installed')}</p> : <button type="button" disabled={disabled || busy || !catalog || !chosen.length || packs.length !== chosen.length}
      onClick={() => void install()} className="rounded border border-cyan-400/50 px-3 py-2 disabled:opacity-40">{t('examples.download', { size: bytes(size) })}</button>}
    <DownloadStatus job={catalog?.job} onError={() => setError(true)} />
    {(error || catalog?.job?.status === 'failed') && <p role="alert">{t('examples.error')} <button type="button" className="underline" onClick={() => setRetry(n => n + 1)}>{t('examples.retry')}</button></p>}
    {ready && packs.filter(p => p.gallery).map(p => <a key={p.id} className="mr-3 inline-block underline" href={`/examples/${encodeURIComponent(p.id)}/`} target="_blank" rel="noopener noreferrer">{t('examples.open', { name: p.id })}</a>)}
  </section>
}
