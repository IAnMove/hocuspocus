import { useState, useEffect, useCallback } from 'react'
import { X, HardDrive, Loader2, Trash2, RefreshCw, Copy, Boxes, FolderOpen, Film } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import {
  fetchStorageUsage, fetchStorageDuplicates, reclaimDuplicate, removeLinkedDuplicate,
  deleteModel, deleteLoraFile, deleteWorkspace as apiDeleteWorkspace,
  type StorageUsage, type StorageDuplicate,
} from '../../api/client'
import { formatBytes } from '../../lib/format'

/** Full-screen storage manager: usage analytics backfilled from every
 *  generation sidecar, plus a linked-install duplicate finder. Every row
 *  action reuses the deletion endpoints shipped in phases A/B, with the
 *  same two-click confirm convention. */
export function StorageDashboard() {
  const { t } = useUiTranslation('settings')
  const { t: tCommon } = useUiTranslation('common')
  const open = useStore(s => s.storageDashboardOpen)
  const setOpen = useStore(s => s.setStorageDashboardOpen)
  const loadWorkspaces = useStore(s => s.loadWorkspaces)
  const allowLinkedRemoval = useStore(s => s.servicesConfig?.storage_allow_linked_removal ?? false)
  const updateServicesConfig = useStore(s => s.updateServicesConfig)
  const [usage, setUsage] = useState<StorageUsage | null>(null)
  const [usageLoading, setUsageLoading] = useState(false)
  const [dupes, setDupes] = useState<{ duplicates: StorageDuplicate[]; conflicts: StorageDuplicate[]; total_reclaimable_bytes: number } | null>(null)
  const [dupesLoading, setDupesLoading] = useState(false)
  const [confirmKey, setConfirmKey] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadUsage = useCallback(async () => {
    setUsageLoading(true)
    try {
      setUsage(await fetchStorageUsage())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUsageLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) loadUsage()
  }, [open, loadUsage])

  const scanDupes = useCallback(async () => {
    setDupesLoading(true)
    setError(null)
    try {
      setDupes(await fetchStorageDuplicates())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setDupesLoading(false)
    }
  }, [])

  /** Two-click confirm + action runner shared by every row. */
  const confirmAndRun = useCallback(async (key: string, action: () => Promise<void>) => {
    if (confirmKey !== key) {
      setConfirmKey(key)
      setTimeout(() => setConfirmKey(c => (c === key ? null : c)), 4000)
      return
    }
    setConfirmKey(null)
    setBusyKey(key)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }, [confirmKey])

  if (!open) return null

  const fmtWhen = (ts: number | null) => ts ? new Date(ts * 1000).toLocaleDateString() : t('storage.never')
  // Server-side deduped total — per-model sizes overlap on shared weights.
  const totalModels = usage ? usage.models_total_bytes : 0
  const totalLoras = usage ? usage.loras.reduce((a, l) => a + l.size_bytes, 0) : 0
  const totalMedia = usage ? usage.workspaces.reduce((a, w) => a + w.size_bytes, 0) : 0

  const rowBtn = (key: string, label: string, onRun: () => Promise<void>) => (
    <button
      onClick={() => confirmAndRun(key, onRun)}
      disabled={busyKey === key}
      className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded border transition-colors shrink-0 ${
        confirmKey === key
          ? 'bg-red-500/20 border-red-500/50 text-red-400'
          : 'border-border text-text-muted hover:text-red-400 hover:border-red-500/40'
      }`}
    >
      {busyKey === key ? <Loader2 size={9} className="animate-spin" /> : <Trash2 size={9} />}
      {confirmKey === key ? t('storage.confirm') : label}
    </button>
  )

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-bg-primary">
      <div className="px-4 py-3 border-b border-border flex items-center gap-3 shrink-0">
        <HardDrive size={16} className="text-accent-blue" />
        <h1 className="text-sm font-semibold text-text-primary">{t('storage.title')}</h1>
        {usage && (
          <span className="text-[10px] text-text-muted">
            {t('storage.usageFrom', { count: usage.scanned_sidecars })}
          </span>
        )}
        {usageLoading && <Loader2 size={13} className="animate-spin text-accent-blue" />}
        <button onClick={() => setOpen(false)} className="ml-auto p-1.5 rounded-lg hover:bg-bg-hover transition-colors">
          <X size={16} className="text-text-muted" />
        </button>
      </div>

      {error && (
        <div className="mx-4 mt-3 px-3 py-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg">{error}</div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Summary tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: t('storage.modelsOnDisk'), value: formatBytes(totalModels), icon: Boxes },
            { label: t('storage.lorasOnDisk'), value: formatBytes(totalLoras), icon: HardDrive },
            { label: t('storage.generatedMedia'), value: formatBytes(totalMedia), icon: Film },
            { label: t('storage.reclaimable'), value: dupes ? formatBytes(dupes.total_reclaimable_bytes) : t('storage.scanBelow'), icon: Copy },
          ].map(t => (
            <div key={t.label} className="rounded-lg border border-border bg-bg-secondary px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-text-muted uppercase tracking-wider"><t.icon size={10} />{t.label}</div>
              <div className="text-lg text-text-primary font-semibold mt-0.5">{t.value}</div>
            </div>
          ))}
        </div>

        {/* Duplicates */}
        <section>
          <div className="flex items-center gap-2 mb-2">
            <h2 className="text-xs font-medium text-text-primary uppercase tracking-wider">{t('storage.duplicatesTitle')}</h2>
            <button
              onClick={scanDupes}
              disabled={dupesLoading}
              className="flex items-center gap-1 px-2 py-1 text-[10px] rounded border border-border text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
            >
              {dupesLoading ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
              {t('storage.scan')}
            </button>
            <span className="text-[10px] text-text-muted">
              {t('storage.duplicatesHint')}
            </span>
            <label className="ml-auto flex items-center gap-1.5 text-[10px] text-text-secondary cursor-pointer shrink-0" title={t('storage.allowLinkedTitle')}>
              <input
                type="checkbox"
                checked={allowLinkedRemoval}
                onChange={e => updateServicesConfig({ storage_allow_linked_removal: e.target.checked })}
                className="w-3 h-3 rounded border-border bg-bg-tertiary accent-accent-blue"
              />
              {t('storage.allowLinked')}
            </label>
          </div>
          {dupes && dupes.duplicates.length === 0 && (
            <div className="text-xs text-text-muted py-2">{t('storage.noDuplicates')}</div>
          )}
          {dupes && dupes.duplicates.length > 0 && (
            <div className="rounded-lg border border-border overflow-hidden">
              {dupes.duplicates.map(d => (
                <div key={d.primary_path} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border last:border-b-0 hover:bg-bg-hover">
                  <span className="text-[9px] px-1 py-0.5 rounded bg-bg-tertiary text-text-muted uppercase shrink-0">{d.kind}</span>
                  <span className="truncate text-text-primary flex-1 min-w-0" title={d.primary_path}>{d.rel_path}</span>
                  <span className="text-text-muted shrink-0" title={`Also in ${d.linked_path}`}>in {d.linked_install}</span>
                  <span className="text-text-secondary tabular-nums shrink-0">{formatBytes(d.size_bytes)}</span>
                  {rowBtn(`dup:${d.primary_path}`, t('storage.reclaim'), async () => {
                    await reclaimDuplicate(d.primary_path)
                    setDupes(prev => prev ? {
                      ...prev,
                      duplicates: prev.duplicates.filter(x => x.primary_path !== d.primary_path),
                      total_reclaimable_bytes: prev.total_reclaimable_bytes - d.size_bytes,
                    } : prev)
                  })}
                  {allowLinkedRemoval && rowBtn(`dupl:${d.linked_path}`, t('storage.removeLinked'), async () => {
                    await removeLinkedDuplicate(d.linked_path)
                    // Pair broken the other way: Maestro's copy stays, the
                    // linked one is in that install's Recycle Bin.
                    setDupes(prev => prev ? {
                      ...prev,
                      duplicates: prev.duplicates.filter(x => x.primary_path !== d.primary_path),
                      total_reclaimable_bytes: prev.total_reclaimable_bytes - d.size_bytes,
                    } : prev)
                  })}
                </div>
              ))}
            </div>
          )}
          {dupes && dupes.conflicts.length > 0 && (
            <div className="mt-2 text-[10px] text-indicator-warning">
              {t('storage.conflicts', { count: dupes.conflicts.length })}
            </div>
          )}
        </section>

        {/* Models by size/usage */}
        <section>
          <h2 className="text-xs font-medium text-text-primary uppercase tracking-wider mb-2">{t('storage.modelsTitle')}</h2>
          {usage && (
            <div className="rounded-lg border border-border overflow-hidden">
              {usage.models.filter(m => m.size_bytes > 0).map(m => (
                <div key={m.model_type} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border last:border-b-0 hover:bg-bg-hover">
                  <span className="truncate text-text-primary flex-1 min-w-0">{m.name}</span>
                  <span className={`shrink-0 ${m.use_count === 0 ? 'text-indicator-warning' : 'text-text-muted'}`}>
                    {m.use_count === 0 ? t('storage.neverUsed') : t('storage.usesLast', { count: m.use_count, when: fmtWhen(m.last_used) })}
                  </span>
                  <span className="text-text-secondary tabular-nums shrink-0" title={m.primary_bytes < m.size_bytes ? t('storage.modelSizeTitle', { primary: formatBytes(m.primary_bytes) }) : undefined}>
                    {formatBytes(m.size_bytes)}
                  </span>
                  {m.primary_bytes > 0 ? rowBtn(`model:${m.model_type}`, tCommon('actions.delete'), async () => {
                    await deleteModel(m.model_type)
                    loadUsage()
                  }) : m.alias_of ? (
                    <span
                      className="text-[9px] px-1.5 py-0.5 rounded bg-bg-tertiary text-text-muted shrink-0"
                      title={t('storage.sharesWeightsTitle', { name: m.alias_of })}
                    >
                      {t('storage.sharesWeights')}
                    </span>
                  ) : m.size_bytes > 0 ? (
                    <span
                      className="text-[9px] px-1.5 py-0.5 rounded bg-bg-tertiary text-text-muted shrink-0"
                      title={t('storage.linkedOnlyTitle')}
                    >
                      {t('storage.linkedOnly')}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* LoRAs by size/usage */}
        <section>
          <h2 className="text-xs font-medium text-text-primary uppercase tracking-wider mb-2">{t('storage.lorasTitle')}</h2>
          {usage && (
            <div className="rounded-lg border border-border overflow-hidden">
              {usage.loras.map(l => (
                <div key={`${l.directory}/${l.filename}`} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border last:border-b-0 hover:bg-bg-hover">
                  <span className="truncate text-text-primary flex-1 min-w-0">{l.filename}</span>
                  {l.linked && (
                    <span
                      className="text-[9px] px-1 py-0.5 rounded bg-accent-blue/20 text-accent-blue shrink-0"
                      title={t('storage.linkedLoraTitle')}
                    >
                      {t('storage.linked')}
                    </span>
                  )}
                  <span className={`shrink-0 ${l.use_count === 0 ? 'text-indicator-warning' : 'text-text-muted'}`}>
                    {l.use_count === 0 ? t('storage.neverUsed') : t('storage.usesLast', { count: l.use_count, when: fmtWhen(l.last_used) })}
                  </span>
                  <span className="text-text-secondary tabular-nums shrink-0">{formatBytes(l.size_bytes)}</span>
                  {!l.linked && rowBtn(`lora:${l.directory}/${l.filename}`, tCommon('actions.delete'), async () => {
                    await deleteLoraFile(l.directory, l.filename)
                    setUsage(prev => prev ? { ...prev, loras: prev.loras.filter(x => !(x.directory === l.directory && x.filename === l.filename)) } : prev)
                  })}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Workspaces */}
        <section>
          <h2 className="text-xs font-medium text-text-primary uppercase tracking-wider mb-2">{t('storage.workspacesTitle')}</h2>
          {usage && (
            <div className="rounded-lg border border-border overflow-hidden">
              {usage.workspaces.map(w => (
                <div key={w.name} className="flex items-center gap-2 px-3 py-1.5 text-xs border-b border-border last:border-b-0 hover:bg-bg-hover">
                  <FolderOpen size={11} className="text-text-muted shrink-0" />
                  <span className="truncate text-text-primary flex-1 min-w-0">{w.name}</span>
                  <span className="text-text-muted shrink-0">{t('storage.files', { count: w.file_count })}</span>
                  <span className="text-text-secondary tabular-nums shrink-0">{formatBytes(w.size_bytes)}</span>
                  {w.name !== 'default' && rowBtn(`ws:${w.name}`, tCommon('actions.delete'), async () => {
                    await apiDeleteWorkspace(w.name)
                    loadWorkspaces()
                    loadUsage()
                  })}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
