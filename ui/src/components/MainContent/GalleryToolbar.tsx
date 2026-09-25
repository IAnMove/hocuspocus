import { useState } from 'react'
import { CheckCheck, CheckSquare, Columns2, FolderInput, Heart, HeartOff, History, Loader2, Search, Trash2, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { GalleryViewSwitcher } from './GalleryViewSwitcher'
import { MediaMoveDialog } from './MediaMoveDialog'
import { ConfirmDialog } from '../common/ConfirmDialog'
import type { GalleryBatchAction } from './galleryBatch'
import { useStore } from '../../stores/useStore'
import type { GalleryOrder } from '../../api/outputs'
import { useIsMobile } from '../../lib/useIsMobile'
import { GallerySearch } from './GallerySearch'

const iconButton = 'flex h-10 min-w-10 shrink-0 items-center justify-center gap-1.5 rounded-md px-2 text-text-secondary transition-colors hover:bg-white/[0.07] hover:text-text-primary disabled:opacity-40'

/** The gallery column's own bar: history on phones, multi-select for the
 *  dense views, and the layout switcher. While selecting it becomes the
 *  selection's action bar. */
export function GalleryToolbar({
  view, hasItems, selecting, picked, busy, error, moveTargets,
  onOpenHistory, onStartSelecting, onSelectAll, onAction, onDone, onCompare,
}: {
  view: 'feed' | 'grid' | 'masonry'
  hasItems: boolean
  selecting: boolean
  picked: number
  busy: boolean
  error: string | null
  moveTargets: string[]
  onOpenHistory: () => void
  onStartSelecting: () => void
  onSelectAll: () => void
  onAction: (action: GalleryBatchAction) => void
  onDone: () => void
  /** Set when exactly two images are picked. */
  onCompare?: () => void
}) {
  const { t } = useUiTranslation('activity')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [moving, setMoving] = useState(false)

  if (selecting) {
    const none = picked === 0 || busy
    return (
      <div role="toolbar" aria-label={t('selection.count', { count: picked })} className="flex min-w-0 flex-1 items-center gap-1">
        <span className="mr-auto truncate pl-1 text-xs text-text-secondary" aria-live="polite">
          {busy ? t('selection.working') : error || (picked ? t('selection.count', { count: picked }) : t('selection.none'))}
        </span>
        {busy && <Loader2 size={16} className="shrink-0 animate-spin text-accent-blue" />}
        <button type="button" className={iconButton} onClick={onSelectAll} disabled={busy} title={t('selection.all')} aria-label={t('selection.all')}><CheckCheck size={17} /></button>
        <button type="button" className={iconButton} onClick={() => onAction({ kind: 'favorite', favorite: true })} disabled={none} title={t('selection.favorite')} aria-label={t('selection.favorite')}><Heart size={16} /></button>
        <button type="button" className={iconButton} onClick={() => onAction({ kind: 'favorite', favorite: false })} disabled={none} title={t('selection.unfavorite')} aria-label={t('selection.unfavorite')}><HeartOff size={16} /></button>
        {onCompare && <button type="button" className={iconButton} onClick={onCompare} disabled={busy} title={t('selection.compare')} aria-label={t('selection.compare')}><Columns2 size={16} /></button>}
        <button type="button" className={iconButton} onClick={() => setMoving(true)} disabled={none} title={t('selection.move')} aria-label={t('selection.move')}><FolderInput size={16} /></button>
        <button type="button" className={`${iconButton} hover:text-red-400`} onClick={() => setConfirmDelete(true)} disabled={none} title={t('selection.delete')} aria-label={t('selection.delete')}><Trash2 size={16} /></button>
        <button type="button" className={iconButton} onClick={onDone} disabled={busy} title={t('selection.done')} aria-label={t('selection.done')}><X size={17} /></button>
        {confirmDelete && <ConfirmDialog
          title={t('selection.confirmDeleteTitle', { count: picked })}
          message={t('selection.confirmDelete', { count: picked })}
          confirmLabel={t('selection.confirmDeleteAction')}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => { setConfirmDelete(false); onAction({ kind: 'delete' }) }} />}
        {moving && <MediaMoveDialog workspaces={moveTargets} onClose={() => setMoving(false)}
          onMove={workspace => { setMoving(false); onAction({ kind: 'move', workspace }) }} />}
      </div>
    )
  }

  return <BrowseBar view={view} hasItems={hasItems} onOpenHistory={onOpenHistory} onStartSelecting={onStartSelecting} />
}

/** The toolbar while browsing: history (phones), selection, search, order
 *  and layout. On a phone the search opens over the whole bar. */
function BrowseBar({ view, hasItems, onOpenHistory, onStartSelecting }: {
  view: 'feed' | 'grid' | 'masonry'
  hasItems: boolean
  onOpenHistory: () => void
  onStartSelecting: () => void
}) {
  const { t } = useUiTranslation('activity')
  const order = useStore(s => s.galleryOrder)
  const setOrder = useStore(s => s.setGalleryOrder)
  const searching = useStore(s => Boolean(s.outputSearchQuery.trim()))
  const isMobile = useIsMobile()
  const browsingUploads = useStore(s => s.browsingUploads)
  const [searchOpen, setSearchOpen] = useState(false)
  // Uploads are browse-only; history is the phone's stand-in for the strip.
  const canSelect = hasItems && !browsingUploads
  const showHistory = hasItems && isMobile && view === 'feed'

  if (isMobile && (searchOpen || searching)) {
    return <div className="flex min-w-0 flex-1 items-center gap-1"><GallerySearch autoFocus={searchOpen} onClose={() => setSearchOpen(false)} /></div>
  }
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      {showHistory && (
        <button type="button" className={iconButton} onClick={onOpenHistory}>
          <History size={16} /><span className="text-xs">{t('view.history')}</span>
        </button>
      )}
      {canSelect && view !== 'feed' && (
        <button type="button" className={iconButton} onClick={onStartSelecting}>
          <CheckSquare size={16} /><span className="text-xs">{t('view.select')}</span>
        </button>
      )}
      {isMobile
        ? <button type="button" className={iconButton} onClick={() => setSearchOpen(true)} aria-label={t('gallerySearch.open')} title={t('gallerySearch.open')}><Search size={16} /></button>
        : <GallerySearch />}
      <select aria-label={t('order.label')} title={t('order.label')} value={order} onChange={event => setOrder(event.target.value as GalleryOrder)}
        className="ml-auto h-10 min-w-0 max-w-[9.5rem] shrink rounded-md border border-border/70 bg-bg-secondary px-2 text-xs text-text-secondary">
        <option value="newest">{t('order.newest')}</option>
        <option value="oldest">{t('order.oldest')}</option>
        <option value="favorites">{t('order.favorites')}</option>
      </select>
      <GalleryViewSwitcher />
    </div>
  )
}
