import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ParseKeys } from 'i18next'
import { Box, FileText, Film, Image as ImageIcon, Info, Loader2, Music2, RefreshCw, Search } from 'lucide-react'
import { fetchAsset, fetchAssets, type AssetCatalogItem, type AssetKind } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

const PAGE_SIZE = 100
const KIND_FILTERS: Array<{ value: AssetKind | ''; labelKey: ParseKeys<'navigation'> }> = [
  { value: '', labelKey: 'tabs.all' },
  { value: 'image', labelKey: 'tabs.images' },
  { value: 'video', labelKey: 'tabs.videos' },
  { value: 'audio', labelKey: 'tabs.audio' },
  { value: 'model3d', labelKey: 'tabs.model3d' },
  { value: 'scene', labelKey: 'tabs.scenes' },
  { value: 'document', labelKey: 'tabs.documents' },
]

function icon(kind: AssetKind) {
  if (kind === 'image') return <ImageIcon size={16} />
  if (kind === 'video') return <Film size={16} />
  if (kind === 'audio') return <Music2 size={16} />
  if (kind === 'model3d') return <Box size={16} />
  return <FileText size={16} />
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1 }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

function AssetPreview({ asset }: { asset: AssetCatalogItem }) {
  if (asset.kind === 'image') {
    return <img src={asset.url} alt="" loading="lazy" className="h-full w-full object-contain" />
  }
  if (asset.kind === 'video') {
    return <video src={asset.url} preload="metadata" controls className="h-full w-full object-contain" />
  }
  if (asset.kind === 'audio') {
    return (
      <div className="flex h-full w-full items-center justify-center px-4">
        <audio src={asset.url} preload="metadata" controls className="w-full" />
      </div>
    )
  }
  return <div className="flex h-full items-center justify-center text-text-muted">{icon(asset.kind)}</div>
}

export function AssetsPanel() {
  const { t } = useUiTranslation('navigation')
  const { t: tActivity } = useUiTranslation('activity')
  const { t: tCommon } = useUiTranslation('common')
  const workspaces = useStore(state => state.workspaces)
  const loadWorkspaces = useStore(state => state.loadWorkspaces)
  const [assets, setAssets] = useState<AssetCatalogItem[]>([])
  const [total, setTotal] = useState(0)
  const [kind, setKind] = useState<AssetKind | ''>('')
  const [workspace, setWorkspace] = useState('')
  const [draftSearch, setDraftSearch] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const requestRef = useRef(0)

  const load = useCallback(async (append = false, offset = 0) => {
    const request = ++requestRef.current
    if (append) setLoadingMore(true)
    else setLoading(true)
    setError('')
    try {
      const result = await fetchAssets({
        search, kind: kind || undefined,
        workspace: workspace && workspace !== '__legacy__' ? workspace : undefined,
        collection: workspace === '__legacy__' ? 'inbox_legacy' : undefined,
        limit: PAGE_SIZE, offset,
      })
      if (request !== requestRef.current) return
      setAssets(current => append ? [...current, ...result.assets.filter(
        candidate => !current.some(item => item.id === candidate.id),
      )] : result.assets)
      setTotal(result.total)
    } catch (reason) {
      if (request === requestRef.current) {
        setError(reason instanceof Error ? reason.message : tActivity('catalog.loadFailed'))
      }
    } finally {
      if (request === requestRef.current) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [kind, search, tActivity, workspace])

  useEffect(() => { void loadWorkspaces() }, [loadWorkspaces])
  useEffect(() => { void load(false) }, [kind, load, search, workspace])
  useEffect(() => () => { requestRef.current += 1 }, [])

  const workspaceOptions = useMemo(() => [
    { name: '', label: t('filters.allWorkspaces') },
    ...workspaces.map(item => ({ name: item.name, label: item.name })),
    { name: '__uploads__', label: t('outputFolder.uploads') },
    { name: '__legacy__', label: tActivity('inboxLegacy') },
  ], [t, tActivity, workspaces])
  const [inspecting, setInspecting] = useState<AssetCatalogItem | null>(null)
  const [inspectorLoading, setInspectorLoading] = useState(false)

  const inspect = async (asset: AssetCatalogItem) => {
    setInspectorLoading(true); setError('')
    try { setInspecting(await fetchAsset(asset.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : tActivity('inspector.loadFailed')) }
    finally { setInspectorLoading(false) }
  }

  return (
    <section aria-label={t('headings.assets')} className="flex h-full min-h-0 flex-col bg-bg-primary">
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <Box size={16} className="text-accent-blue" /> {t('headings.assets')}
        </div>
        <span className="text-[10px] text-text-muted">{tActivity('catalog.itemsAcrossLocations', { count: total })}</span>
        <div className="min-w-0 flex-1" />
        <form
          className="flex items-center gap-1 rounded-md border border-border bg-bg-secondary px-2"
          onSubmit={event => { event.preventDefault(); setSearch(draftSearch.trim()) }}
        >
          <Search size={12} className="text-text-muted" />
          <input
            value={draftSearch}
            onChange={event => setDraftSearch(event.target.value)}
            placeholder={tActivity('catalog.searchPlaceholder')}
            aria-label={tCommon('actions.search')}
            className="w-52 bg-transparent py-1.5 text-xs text-text-primary outline-none"
          />
        </form>
        <select
          aria-label={tActivity('catalog.kindFilter')}
          value={kind}
          onChange={event => setKind(event.target.value as AssetKind | '')}
          className="rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary"
        >
          {KIND_FILTERS.map(item => <option key={item.value} value={item.value}>{t(item.labelKey)}</option>)}
        </select>
        <select
          aria-label={tActivity('catalog.workspaceFilter')}
          value={workspace}
          onChange={event => setWorkspace(event.target.value)}
          className="rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-xs text-text-primary"
        >
          {workspaceOptions.map(item => <option key={item.name} value={item.name}>{item.label}</option>)}
        </select>
        <button
          type="button"
          onClick={() => void load(false)}
          className="rounded-md border border-border bg-bg-secondary p-1.5 text-text-muted hover:text-text-primary"
          title={tActivity('catalog.reload')}
          aria-label={tCommon('actions.reload')}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {error && <div role="alert" className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{error}</div>}
        {loading && !assets.length ? (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-text-muted"><Loader2 size={16} className="animate-spin" /> {tActivity('catalog.reading')}</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {assets.map(asset => (
              <article key={asset.id} className="overflow-hidden rounded-lg border border-border bg-bg-secondary">
                <div className="aspect-video bg-black/30"><AssetPreview asset={asset} /></div>
                <div className="space-y-2 p-3">
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 text-accent-blue">{icon(asset.kind)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-text-primary" title={asset.filename}>{asset.filename}</div>
                      <div className="mt-0.5 text-[10px] text-text-muted">{formatBytes(asset.size_bytes)} · {asset.origin.tool}</div>
                    </div>
                    <span className={`rounded px-1.5 py-0.5 text-[9px] ${asset.metadata_status === 'canonical' ? 'bg-green-500/15 text-green-300' : 'bg-amber-500/15 text-amber-300'}`}>
                      {asset.metadata_status}
                    </span>
                  </div>
                  {asset.prompt_preview && <p className="line-clamp-3 text-[10px] leading-relaxed text-text-secondary" title={asset.prompt_preview}>{asset.prompt_preview}</p>}
                  <div className="flex flex-wrap gap-1">
                    {asset.workspace_ids.map(name => <span key={name} className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[9px] text-text-muted">{name}</span>)}
                    {asset.model.id && <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[9px] text-violet-200">{asset.model.id}</span>}
                  </div>
                  <button type="button" className="inline-flex items-center gap-1 text-[10px] text-accent-blue hover:underline" onClick={() => void inspect(asset)}><Info size={11} /> {tActivity('extraInfo')}</button>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && !assets.length && !error && <p className="p-8 text-center text-xs text-text-muted">{tActivity('catalog.empty')}</p>}
        {assets.length < total && (
          <button
            type="button"
            disabled={loadingMore}
            onClick={() => void load(true, assets.length)}
            className="mx-auto mt-4 flex items-center gap-2 rounded-md border border-border bg-bg-secondary px-4 py-2 text-xs text-text-secondary disabled:opacity-50"
          >
            {loadingMore && <Loader2 size={13} className="animate-spin" />} {tActivity('catalog.loadMore')}
          </button>
        )}
      </div>
      {(inspecting || inspectorLoading) && <AssetExtraInfoDialog asset={inspecting} loading={inspectorLoading} onClose={() => setInspecting(null)} />}
    </section>
  )
}

function formatTimingMs(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
  const seconds = value / 1000
  return Number.isInteger(seconds) ? `${seconds}s` : `${seconds.toFixed(1)}s`
}

function AssetExtraInfoDialog({ asset, loading, onClose }: { asset: AssetCatalogItem | null; loading: boolean; onClose: () => void }) {
  const { t: tActivity } = useUiTranslation('activity')
  const { t: tCommon } = useUiTranslation('common')
  const { t: tNav } = useUiTranslation('navigation')
  const manifest = asset?.manifest || {}
  const prompts = (manifest.generation as { prompts?: Record<string, unknown> } | undefined)?.prompts || {}
  const timing = (manifest.timing as Record<string, unknown> | undefined) || {}
  const origin = (manifest.origin as Record<string, unknown> | undefined) || {}
  const execution = (manifest.execution as Record<string, unknown> | undefined) || {}
  const generation = (manifest.generation as { model?: Record<string, unknown> } | undefined) || {}
  const model = generation.model || {}
  const raw = asset ? JSON.stringify(manifest, null, 2) : ''
  const copy = async (value: string) => { await navigator.clipboard?.writeText(value) }
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="asset-extra-info-title"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl">
        <header className="flex items-center justify-between border-b border-border p-3">
          <div>
            <h2 id="asset-extra-info-title" className="text-sm font-semibold text-text-primary">{tActivity('extraInfo')}</h2>
            <p className="text-[10px] text-text-muted">{asset?.filename || tActivity('inspector.loadingAsset')}</p>
          </div>
          <button onClick={onClose} className="rounded px-2 py-1 text-xs text-text-muted hover:bg-bg-hover">{tCommon('actions.close')}</button>
        </header>
        {loading || !asset ? (
          <div className="flex items-center justify-center gap-2 p-12 text-xs text-text-muted">
            <Loader2 size={15} className="animate-spin" /> {tActivity('inspector.readingManifest')}
          </div>
        ) : (
          <div className="space-y-4 overflow-y-auto p-4 text-xs">
            <InfoSection
              title={tActivity('inspector.identity')}
              values={{ asset_id: asset.id, kind: asset.kind, metadata_status: asset.metadata_status, locations: asset.workspace_ids.join(', ') }}
            />
            <InfoSection
              title={tActivity('inspector.initiator')}
              values={{
                [tActivity('inspector.actor')]: origin.actor || asset.origin.actor,
                tool: origin.tool || asset.origin.tool,
                capability: origin.capability || asset.origin.capability,
              }}
            />
            <InfoSection
              title={tActivity('inspector.origin')}
              values={{
                [tNav('entities.workspace')]: origin.workspace_id || asset.origin.workspace_id,
                [tNav('entities.outputFolder')]: origin.output_folder || asset.origin.output_folder,
                command_id: execution.command_id || asset.execution.command_id,
                workflow_id: execution.workflow_id || asset.execution.workflow_id,
                run_id: execution.run_id || asset.execution.run_id,
                task_id: execution.task_id || asset.execution.task_id,
                job_id: execution.job_id || asset.execution.job_id,
                pipeline_id: execution.pipeline_id || asset.execution.pipeline_id,
                status: execution.status || asset.execution.status,
              }}
            />
            <InfoSection
              title={tActivity('inspector.modelTiming')}
              values={{
                [tActivity('inspector.provider')]: model.provider || asset.model.provider,
                model: model.id || asset.model.id,
                created_at: timing.created_at,
                queued_at: timing.queued_at,
                started_at: timing.started_at,
                completed_at: timing.completed_at,
                [tActivity('inspector.queue')]: formatTimingMs(timing.queue_ms),
                [tActivity('inspector.inference')]: formatTimingMs(timing.inference_ms),
                [tActivity('inspector.totalTime')]: formatTimingMs(timing.total_ms),
              }}
            />
            {Object.entries(prompts).map(([name, value]) => typeof value === 'string' && value ? (
              <section key={name} className="rounded-lg border border-border bg-bg-primary p-3">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="font-semibold text-text-primary">{tActivity('inspector.prompt', { name })}</h3>
                  <button onClick={() => void copy(value)} className="text-[10px] text-accent-blue">{tActivity('inspector.copy')}</button>
                </div>
                <pre className="whitespace-pre-wrap break-words text-[11px] text-text-secondary">{value}</pre>
              </section>
            ) : null)}
            <section className="rounded-lg border border-border bg-bg-primary p-3">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-semibold text-text-primary">{tActivity('inspector.fullJson')}</h3>
                <button onClick={() => void copy(raw)} className="text-[10px] text-accent-blue">{tActivity('inspector.copyJson')}</button>
              </div>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-[10px] text-text-muted">{raw || tActivity('inspector.unavailable')}</pre>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

function InfoSection({ title, values }: { title: string; values: Record<string, unknown> }) {
  const { t: tActivity } = useUiTranslation('activity')
  return (
    <section className="rounded-lg border border-border bg-bg-primary p-3">
      <h3 className="mb-2 font-semibold text-text-primary">{title}</h3>
      <dl className="grid gap-1 sm:grid-cols-2">
        {Object.entries(values).map(([name, value]) => (
          <div key={name} className="grid grid-cols-[7rem_1fr] gap-2">
            <dt className="text-text-muted">{name}</dt>
            <dd className="break-all text-text-secondary">{value == null || value === '' ? tActivity('inspector.unavailable') : String(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
