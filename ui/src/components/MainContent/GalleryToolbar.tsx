import { useState } from 'react'
import { CheckCheck, CheckSquare, FolderInput, Heart, HeartOff, History, Loader2, Trash2, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { GalleryViewSwitcher } from './GalleryViewSwitcher'
import { MediaMoveDialog } from './MediaMoveDialog'
import type { GalleryBatchAction } from './galleryBatch'

const iconButton = 'flex h-10 min-w-10 shrink-0 items-center justify-center gap-1.5 rounded-md px-2 text-text-secondary transition-colors hover:bg-white/[0.07] hover:text-text-primary disabled:opacity-40'

/** The gallery column's own bar: history on phones, multi-select for the
 *  dense views, and the layout switcher. While selecting it becomes the
 *  selection's action bar. */
export function GalleryToolbar({
  view, canSelect, showHistory, selecting, picked, busy, error, moveTargets,
  onOpenHistory, onStartSelecting, onSelectAll, onAction, onDone,
}: {
  view: 'feed' | 'grid' | 'masonry'
  canSelect: boolean
  showHistory: boolean
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
        <button type="button" className={iconButton} onClick={() => setMoving(true)} disabled={none} title={t('selection.move')} aria-label={t('selection.move')}><FolderInput size={16} /></button>
        {confirmDelete ? (
          <button type="button" className={`${iconButton} bg-red-600/90 text-white hover:bg-red-600`} disabled={none}
            onClick={() => { setConfirmDelete(false); onAction({ kind: 'delete' }) }} onBlur={() => setConfirmDelete(false)}>
            <Trash2 size={15} /><span className="text-xs">{t('selection.confirmDelete', { count: picked })}</span>
          </button>
        ) : (
          <button type="button" className={`${iconButton} hover:text-red-400`} onClick={() => setConfirmDelete(true)} disabled={none} title={t('selection.delete')} aria-label={t('selection.delete')}><Trash2 size={16} /></button>
        )}
        <button type="button" className={iconButton} onClick={onDone} disabled={busy} title={t('selection.done')} aria-label={t('selection.done')}><X size={17} /></button>
        {moving && <MediaMoveDialog workspaces={moveTargets} onClose={() => setMoving(false)}
          onMove={workspace => { setMoving(false); onAction({ kind: 'move', workspace }) }} />}
      </div>
    )
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
      <div className="ml-auto"><GalleryViewSwitcher /></div>
    </div>
  )
}
