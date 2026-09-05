import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, FolderOpen, Loader2, X } from 'lucide-react'
import { fetchOutputMetadata, fetchOutputs, type ApiOutput } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { ModalShell } from '../common/ModalShell'
import { SCENE_LIBRARY_PAGE_SIZE, isCompositorVideo, sceneFromLibraryPayload, sceneLibraryTitle } from '../../lib/sceneLibrary'
import type { Scene } from '../../types'

type LibraryTab = 'scenes' | 'videos'

export function SceneLibraryDialog({
  open,
  workspace,
  onClose,
  onOpenScene,
  onPickFile,
}: {
  open: boolean
  workspace?: string
  onClose: () => void
  onOpenScene: (scene: Scene, label: string) => void
  onPickFile: () => void
}) {
  const { t } = useUiTranslation('scene3d')
  const [tab, setTab] = useState<LibraryTab>('scenes')
  const [page, setPage] = useState(0)
  const [items, setItems] = useState<ApiOutput[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [opening, setOpening] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<ApiOutput | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setOpening(null)
    const controller = new AbortController()
    setLoading(true)
    const load = async () => {
      try {
        if (tab === 'scenes') {
          const data = await fetchOutputs(SCENE_LIBRARY_PAGE_SIZE, page * SCENE_LIBRARY_PAGE_SIZE, {
            mediaType: 'scene',
            workspace,
            signal: controller.signal,
          })
          setItems(data.outputs)
          setTotal(data.total)
          setSelected(data.outputs[0] ?? null)
          return
        }
        const data = await fetchOutputs(0, 0, { mediaType: 'video', search: '_3d_', workspace, signal: controller.signal })
        const videos = data.outputs.filter(isCompositorVideo)
        setTotal(videos.length)
        const slice = videos.slice(page * SCENE_LIBRARY_PAGE_SIZE, (page + 1) * SCENE_LIBRARY_PAGE_SIZE)
        setItems(slice)
        setSelected(slice[0] ?? null)
      } catch (loadError) {
        if ((loadError as { name?: string }).name === 'AbortError') return
        setError(loadError instanceof Error ? loadError.message : t('library.listFailed'))
        setItems([])
        setTotal(0)
        setSelected(null)
      } finally {
        setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [open, page, tab, workspace, t])

  const pages = Math.max(1, Math.ceil(total / SCENE_LIBRARY_PAGE_SIZE))

  const openItem = async (file: ApiOutput) => {
    setOpening(file.name)
    setError(null)
    try {
      if (file.type === 'scene') {
        const response = await fetch(file.url)
        if (!response.ok) throw new Error(t('library.loadFailed'))
        onOpenScene(sceneFromLibraryPayload(await response.json()), sceneLibraryTitle(file.name))
        return
      }
      const metadata = await fetchOutputMetadata(file.name, workspace)
      onOpenScene(sceneFromLibraryPayload(metadata), sceneLibraryTitle(file.name))
    } catch (openError) {
      setError(openError instanceof Error ? openError.message : t('library.openFailed'))
    } finally {
      setOpening(null)
    }
  }

  return (
    <ModalShell open={open} title={t('library.title')} onClose={onClose} className="fixed inset-0 z-[80] flex items-center justify-center bg-black/65 p-4" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <div className="flex max-h-[86vh] w-[760px] max-w-[96vw] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl" onMouseDown={event => event.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <FolderOpen size={15} className="text-accent-blue" />
            <div>
              <h2 className="text-sm font-semibold text-text-primary">{t('library.title')}</h2>
              <p className="text-[10px] text-text-muted">{t('library.subtitle')}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label={t('library.closeAria')} className="rounded border border-border p-1.5 text-text-muted hover:text-text-primary"><X size={13} /></button>
        </div>
        <div className="flex gap-1 border-b border-border px-4 py-2">
          {([['scenes', 'library.savedScenes'], ['videos', 'library.videos']] as const).map(([id, labelKey]) => (
            <button key={id} type="button" onClick={() => { setTab(id); setPage(0) }} className={`rounded px-2.5 py-1 text-[10px] ${tab === id ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:text-text-primary'}`}>{t(labelKey)}</button>
          ))}
          <button type="button" onClick={onPickFile} className="ml-auto rounded border border-border px-2 py-1 text-[10px] text-text-secondary hover:text-text-primary">{t('library.fromJson')}</button>
        </div>
        <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="min-h-0 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-16 text-[11px] text-text-muted"><Loader2 size={14} className="animate-spin" /> {t('library.loading')}</div>
            ) : items.length ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {items.map(file => (
                  <button
                    key={file.name}
                    type="button"
                    onClick={() => setSelected(file)}
                    onDoubleClick={() => void openItem(file)}
                    className={`overflow-hidden rounded-lg border text-left ${selected?.name === file.name ? 'border-accent-blue ring-1 ring-accent-blue/40' : 'border-border hover:border-accent-blue/50'}`}
                  >
                    <div className="aspect-video bg-black/40">
                      {file.thumbnail_url || file.type === 'video' ? (
                        <img src={file.thumbnail_url || file.url} alt="" className="h-full w-full object-cover" loading="lazy" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-[9px] text-text-muted">{t('library.noPreview')}</div>
                      )}
                    </div>
                    <div className="truncate px-1.5 py-1 text-[9px] text-text-secondary">{sceneLibraryTitle(file.name)}</div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="py-16 text-center text-[11px] text-text-muted">{tab === 'scenes' ? t('library.emptyScenes') : t('library.emptyVideos')}</p>
            )}
          </div>
          <aside className="flex min-h-[180px] flex-col rounded-lg border border-border bg-bg-tertiary p-2">
            {selected ? (
              <>
                <div className="aspect-video overflow-hidden rounded bg-black/50">
                  {selected.thumbnail_url || selected.type === 'video' ? (
                    <img src={selected.thumbnail_url || selected.url} alt="" className="h-full w-full object-cover" />
                  ) : null}
                </div>
                <div className="mt-2 text-[11px] font-medium text-text-primary">{sceneLibraryTitle(selected.name)}</div>
                <div className="mt-0.5 text-[9px] text-text-muted">{selected.type === 'scene' ? t('library.editableProject') : t('library.exportedClip')} · {new Date((selected.completed_at || selected.created_at) * 1000).toLocaleString()}</div>
                <button type="button" disabled={Boolean(opening)} onClick={() => void openItem(selected)} className="mt-auto rounded bg-accent-blue px-2 py-1.5 text-[10px] text-white disabled:opacity-40">
                  {opening === selected.name ? t('library.opening') : t('library.openIn')}
                </button>
              </>
            ) : (
              <p className="m-auto text-center text-[10px] text-text-muted">{t('library.selectPreview')}</p>
            )}
          </aside>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2">
          <span className="text-[10px] text-text-muted">{t('library.savedPage', { total, current: Math.min(page + 1, pages), pages })}</span>
          <div className="flex gap-1">
            <button type="button" aria-label={t('library.previousPage')} disabled={page <= 0} onClick={() => setPage(value => Math.max(0, value - 1))} className="rounded border border-border p-1.5 disabled:opacity-30"><ChevronLeft size={13} /></button>
            <button type="button" aria-label={t('library.nextPage')} disabled={page + 1 >= pages} onClick={() => setPage(value => value + 1)} className="rounded border border-border p-1.5 disabled:opacity-30"><ChevronRight size={13} /></button>
          </div>
        </div>
        {error && <p className="border-t border-border px-4 py-2 text-[10px] text-red-300">{error}</p>}
      </div>
    </ModalShell>
  )
}
