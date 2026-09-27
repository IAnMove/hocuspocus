import { Box, ChevronLeft, ChevronRight, FileAudio, Image as ImageIcon, Video } from 'lucide-react'
import type { AssetKind } from '../../api/assets'
import {
  assetRefKey,
  formatCreatedDate,
  isSameRef,
  type CatalogSort,
  type Compatibility,
  type PickerItem,
} from '../../features/asset-picker'
import { AssetPreviewPlayer } from '../../features/asset-picker/previewPlayer.tsx'
import { useUiTranslation } from '../../i18n'

const EXPLORER_SORTS: CatalogSort[] = ['created_desc', 'created_asc', 'name_asc', 'name_desc']
const EXPLORER_KIND_LABEL: Record<AssetKind, 'explorer.typeImage' | 'explorer.typeVideo' | 'explorer.typeModel' | 'explorer.typeAudio' | 'explorer.typeScene' | 'explorer.typeDocument'> = {
  image: 'explorer.typeImage',
  video: 'explorer.typeVideo',
  model3d: 'explorer.typeModel',
  audio: 'explorer.typeAudio',
  scene: 'explorer.typeScene',
  document: 'explorer.typeDocument',
  other: 'explorer.typeDocument',
}

function explorerSortKey(sort: CatalogSort) {
  if (sort === 'created_desc') return 'explorer.sortCreatedDesc' as const
  if (sort === 'created_asc') return 'explorer.sortCreatedAsc' as const
  if (sort === 'name_asc') return 'explorer.sortNameAsc' as const
  return 'explorer.sortNameDesc' as const
}

function KindGlyph({ kind, size }: { kind: AssetKind; size: number }) {
  if (kind === 'model3d') return <Box size={size} className="text-cyan-200" />
  if (kind === 'video') return <Video size={size} className="text-text-muted" />
  if (kind === 'audio') return <FileAudio size={size} className="text-amber-200" />
  return <ImageIcon size={size} className="text-text-muted" />
}

export function ExplorerToolbar({
  query,
  kind,
  kinds,
  sort,
  allowNone,
  noneLabel,
  onQuery,
  onKind,
  onSort,
  onClear,
}: {
  query: string
  kind: AssetKind | ''
  kinds: AssetKind[]
  sort: CatalogSort
  allowNone?: boolean
  noneLabel?: string
  onQuery: (value: string) => void
  onKind: (value: AssetKind | '') => void
  onSort: (value: CatalogSort) => void
  onClear: () => void
}) {
  const { t } = useUiTranslation('common')
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
      <input
        type="search"
        value={query}
        onChange={event => onQuery(event.target.value)}
        placeholder={t('explorer.search')}
        className="min-w-48 flex-1 rounded border border-border bg-bg-primary px-2 py-1.5 text-xs text-text-primary"
      />
      {kinds.length > 1 && (
        <label className="flex items-center gap-1 text-[10px] text-text-muted">
          {t('explorer.kindFilter')}
          <select
            aria-label={t('explorer.kindFilter')}
            value={kind}
            onChange={event => onKind(event.target.value as AssetKind | '')}
            className="rounded border border-border bg-bg-primary px-1 py-1 text-[10px] text-text-primary"
          >
            <option value="">{t('explorer.kindAll')}</option>
            {kinds.map(value => <option key={value} value={value}>{t(EXPLORER_KIND_LABEL[value])}</option>)}
          </select>
        </label>
      )}
      <label className="flex items-center gap-1 text-[10px] text-text-muted">
        {t('explorer.sortLabel')}
        <select
          aria-label={t('explorer.sortLabel')}
          value={sort}
          onChange={event => onSort(event.target.value as CatalogSort)}
          className="rounded border border-border bg-bg-primary px-1 py-1 text-[10px] text-text-primary"
        >
          {EXPLORER_SORTS.map(value => <option key={value} value={value}>{t(explorerSortKey(value))}</option>)}
        </select>
      </label>
      {allowNone && (
        <button type="button" onClick={onClear} className="rounded border border-border px-2 py-1 text-[10px] text-text-secondary">
          {noneLabel ?? t('explorer.none')}
        </button>
      )}
    </div>
  )
}

export function ExplorerGallery({
  status,
  visible,
  selected,
  emptyLabel,
  onRetry,
  onPick,
  checked,
  onToggle,
}: {
  status: 'ready' | 'loading' | 'error'
  visible: PickerItem[]
  selected: PickerItem | null
  emptyLabel: string
  onRetry?: () => void
  onPick: (item: PickerItem) => void
  checked?: ReadonlySet<string>
  onToggle?: (item: PickerItem) => void
}) {
  const { t } = useUiTranslation('common')
  if (status === 'loading') {
    return <p className="py-16 text-center text-[11px] text-text-muted">{t('explorer.loading')}</p>
  }
  if (status === 'error') {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center">
        <p className="text-[11px] text-text-muted">{t('explorer.loadFailed')}</p>
        {onRetry && <button type="button" onClick={onRetry} className="rounded border border-border px-2 py-1 text-[10px]">{t('explorer.retry')}</button>}
      </div>
    )
  }
  if (!visible.length) {
    return <p className="py-16 text-center text-[11px] text-text-muted">{emptyLabel}</p>
  }
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {visible.map(item => {
        const active = selected ? isSameRef(selected.ref, item.ref) && selected.url === item.url : false
        return (
          <div key={`${assetRefKey(item.ref)}:${item.url}`}>
          <button
            key={`${assetRefKey(item.ref)}:${item.url}`}
            type="button"
            title={item.filename}
            aria-pressed={active}
            onClick={() => onPick(item)}
            className={`w-full overflow-hidden rounded-lg border text-left ${active ? 'border-accent-blue ring-1 ring-accent-blue/40' : 'border-border hover:border-accent-blue/50'}`}
          >
            <div className="flex aspect-square items-center justify-center bg-black/40">
              {item.thumbnailUrl ? (
                <img src={item.thumbnailUrl} alt="" className="h-full w-full object-cover" loading="lazy" decoding="async" />
              ) : (
                <KindGlyph kind={item.kind} size={22} />
              )}
            </div>
            <div className="truncate px-1.5 pt-1 text-[9px] text-text-secondary">{item.title}</div>
            <div className="truncate px-1.5 pb-1 text-[8px] text-text-muted">{formatCreatedDate(item.createdAt)}</div>
          </button>
          {onToggle && <label className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label={item.filename} checked={checked?.has(assetRefKey(item.ref)) ?? false} onChange={() => onToggle(item)} />{t('explorer.selectItem')}</label>}
          </div>
        )
      })}
    </div>
  )
}

export function ExplorerPreview({
  selected,
  selectedStillVisible,
  compatibility,
}: {
  selected: PickerItem | null
  selectedStillVisible: boolean
  compatibility: Compatibility
}) {
  const { t } = useUiTranslation('common')
  if (!selected) {
    return <p className="m-auto text-center text-[10px] text-text-muted">{t('explorer.selectHint')}</p>
  }
  return (
    <>
      <div className="flex aspect-video items-center justify-center overflow-hidden rounded bg-black/50">
        <AssetPreviewPlayer item={selected} />
      </div>
      <div className="mt-2 break-all text-[11px] font-medium text-text-primary" title={selected.filename}>{selected.title}</div>
      <div className="mt-0.5 break-all text-[9px] text-text-muted">{selected.filename}</div>
      <div className="mt-0.5 text-[9px] text-text-muted">
        {t(EXPLORER_KIND_LABEL[selected.kind])} · {t('explorer.created', { date: formatCreatedDate(selected.createdAt) })}
      </div>
      {!selectedStillVisible && <p className="mt-1 text-[9px] text-amber-200">{t('explorer.filteredHidden')}</p>}
      {!compatibility.allowed && <p className="mt-1 text-[9px] text-red-300">{t(compatibility.reasonKey)}</p>}
    </>
  )
}

export function ExplorerFooter({
  shown,
  total,
  safePage,
  pages,
  canConfirm,
  onCancel,
  onPage,
  onConfirm,
}: {
  shown: number
  total: number
  safePage: number
  pages: number
  canConfirm: boolean
  onCancel: () => void
  onPage: (page: number) => void
  onConfirm: () => void
}) {
  const { t } = useUiTranslation('common')
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2">
      <span className="text-[10px] text-text-muted">{t('explorer.page', { shown, total })}</span>
      <div className="flex gap-1">
        <button type="button" onClick={onCancel} className="rounded border border-border px-2 py-1 text-[10px] text-text-secondary">{t('actions.cancel')}</button>
        <button type="button" aria-label={t('explorer.previousPage')} disabled={safePage <= 0} onClick={() => onPage(Math.max(0, safePage - 1))} className="rounded border border-border p-1.5 disabled:opacity-30"><ChevronLeft size={13} /></button>
        <button type="button" aria-label={t('explorer.nextPage')} disabled={safePage + 1 >= pages} onClick={() => onPage(safePage + 1)} className="rounded border border-border p-1.5 disabled:opacity-30"><ChevronRight size={13} /></button>
        <button type="button" disabled={!canConfirm} onClick={onConfirm} className="rounded bg-accent-blue px-2 py-1.5 text-[10px] text-white disabled:opacity-40">
          {t('explorer.choose')}
        </button>
      </div>
    </div>
  )
}
