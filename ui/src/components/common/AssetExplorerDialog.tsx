import { useMemo, useState } from 'react'
import { FolderOpen, X } from 'lucide-react'
import type { ApiOutput } from '../../api/outputs'
import type { AssetKind } from '../../api/assets'
import { checkCompatibility, outputToPickerItem, pickerItemToOutput } from '../../features/asset-picker/adapters.ts'
import { assetRefKey, isSameRef, type AssetConstraints, type CatalogSort, type PickerItem } from '../../features/asset-picker/types.ts'
import {
  confirmExplorerItem,
  explorerCanConfirm,
  explorerListModel,
  resolveExplorerSelection,
  useRemoteCatalogPage,
} from '../../features/asset-picker/remoteCatalog.ts'
import { useUiTranslation } from '../../i18n'
import { ExplorerFooter, ExplorerGallery, ExplorerPreview, ExplorerToolbar } from './AssetExplorerChrome.tsx'
import { ModalShell } from './ModalShell'

type BodyProps = {
  title: string
  subtitle?: string
  items: ApiOutput[]
  selected?: ApiOutput
  selectedName?: string
  allowNone?: boolean
  noneLabel?: string
  workspaceId?: string
  remote?: boolean
  constraints?: AssetConstraints
  status?: 'ready' | 'loading' | 'error'
  onRetry?: () => void
  onChoose: (item: ApiOutput | null) => void
  onChooseMany?: (items: ApiOutput[]) => void
  onClose: () => void
}

function AssetExplorerBody({
  title,
  subtitle,
  items,
  selected: selectedOutput,
  selectedName,
  allowNone,
  noneLabel,
  workspaceId,
  remote,
  constraints,
  status = 'ready',
  onRetry,
  onChoose,
  onChooseMany,
  onClose,
}: BodyProps) {
  const { t } = useUiTranslation('common')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [sort, setSort] = useState<CatalogSort>('created_desc')
  const [kind, setKind] = useState<AssetKind | ''>('')
  const [retry, setRetry] = useState(0)
  const [checked, setChecked] = useState<PickerItem[]>([])
  const catalogRemote = Boolean(remote && workspaceId)
  const remotePage = useRemoteCatalogPage({
    enabled: catalogRemote,
    workspaceId,
    query,
    sort,
    kind,
    page,
    retry,
    constraints,
  })
  const localItems = useMemo(
    () => items.map(item => outputToPickerItem(item, workspaceId || '')),
    [items, workspaceId],
  )
  const list = explorerListModel({
    remote: catalogRemote,
    remoteItems: remotePage.items,
    remoteTotal: remotePage.total,
    remoteStatus: remotePage.status,
    localItems,
    query,
    kind,
    sort,
    page,
    constraints,
    fallbackStatus: status,
  })
  const [picked, setPicked] = useState<{ workspaceId: string; item: PickerItem } | null>(null)
  const scopedPicked = picked && picked.workspaceId === (workspaceId || '') ? picked.item : null
  const selected = resolveExplorerSelection({
    remote: catalogRemote,
    pickerItems: list.pickerItems,
    scopedPicked,
    selectedOutput,
    selectedName,
    workspaceId: workspaceId || '',
  })
  const compatibility = selected && constraints ? checkCompatibility(selected, constraints, 0) : { allowed: true as const }
  const stillInCatalog = explorerCanConfirm(catalogRemote, list.pickerItems, selected)
  const selectedStillVisible = selected
    ? list.visible.some(item => isSameRef(item.ref, selected.ref) && item.url === selected.url)
    : true
  const emptyLabel = list.emptyLabelIsNoResults ? t('explorer.noResults') : t('explorer.empty')
  const canConfirmMany = checked.length > 0 && checked.every((item, index) =>
    (!constraints || checkCompatibility(item, constraints, index).allowed)
    && (catalogRemote || localItems.some(current => isSameRef(current.ref, item.ref) && current.url === item.url)),
  )
  const confirm = (item: PickerItem | null) => {
    confirmExplorerItem(catalogRemote, items, list.pickerItems, item, workspaceId || '', constraints, onChoose, onClose)
  }

  return (
    <div
      data-testid="asset-explorer"
      className="flex h-full min-h-0 w-full min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
      onMouseDown={event => event.stopPropagation()}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <FolderOpen size={15} className="text-accent-blue" />
          <div>
            <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
            <p className="text-[10px] text-text-muted">{subtitle ?? t('explorer.subtitle')}</p>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label={t('explorer.closeAria')} className="rounded border border-border p-1.5 text-text-muted hover:text-text-primary">
          <X size={13} />
        </button>
      </div>
      <ExplorerToolbar
        query={query}
        kind={kind}
        kinds={list.toolbarKinds}
        sort={sort}
        allowNone={allowNone}
        noneLabel={noneLabel}
        onQuery={value => { setQuery(value); setPage(0) }}
        onKind={value => { setKind(value); setPage(0) }}
        onSort={value => { setSort(value); setPage(0) }}
        onClear={() => confirm(null)}
      />
      <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto p-4 md:overflow-hidden md:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-h-40 overflow-y-auto md:min-h-0">
          <ExplorerGallery
            status={list.galleryStatus}
            visible={list.visible}
            selected={selected}
            emptyLabel={emptyLabel}
            onRetry={catalogRemote ? () => setRetry(value => value + 1) : onRetry}
            onPick={item => setPicked({ workspaceId: workspaceId || '', item })}
            checked={new Set(checked.map(item => assetRefKey(item.ref)))}
            onToggle={onChooseMany ? item => setChecked(previous => {
              if (previous.some(value => isSameRef(value.ref, item.ref))) return previous.filter(value => !isSameRef(value.ref, item.ref))
              if (constraints && !checkCompatibility(item, constraints, previous.length).allowed) return previous
              return [...previous, item]
            }) : undefined}
          />
        </div>
        <aside className="flex min-h-[200px] flex-col overflow-y-auto rounded-lg border border-border bg-bg-tertiary p-2">
          <ExplorerPreview
            selected={selected}
            selectedStillVisible={selectedStillVisible}
            compatibility={compatibility}
          />
        </aside>
      </div>
      <ExplorerFooter
        shown={list.visible.length}
        total={list.footerTotal}
        safePage={list.safePage}
        pages={list.pages}
        canConfirm={onChooseMany ? canConfirmMany : Boolean(selected) && compatibility.allowed && stillInCatalog}
        onCancel={onClose}
        onPage={setPage}
        onConfirm={() => {
          if (onChooseMany) {
            if (!canConfirmMany) return
            onChooseMany(checked.map(pickerItemToOutput).filter((item): item is ApiOutput => item !== null))
            onClose()
          } else if (selected) confirm(selected)
        }}
      />
      {onChooseMany && <p role="status" className="px-4 pb-2 text-xs text-text-secondary">{t('explorer.selectedCount', { count: checked.length })}</p>}
    </div>
  )
}

export function AssetExplorerDialog({
  open,
  title,
  onClose,
  ...body
}: BodyProps & { open: boolean }) {
  return (
    <ModalShell
      open={open}
      title={title}
      onClose={onClose}
      className="fixed inset-0 z-[130] flex items-center justify-center bg-black/70 p-2 sm:p-4"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
    >
      {open ? (
        <AssetExplorerBody
          key={`${body.workspaceId || ''}:${title}:${body.selected?.asset_id || body.selected?.url || body.selectedName || ''}`}
          title={title}
          onClose={onClose}
          {...body}
        />
      ) : null}
    </ModalShell>
  )
}
