import type { ComponentProps, LiHTMLAttributes } from 'react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { EditableImageReference } from './EditableImageReference'

const rowButton = 'min-h-11 rounded border border-border px-3 text-xs text-text-secondary'

type ReferenceItemProps = {
  file: File
  index: number
  count: number
  /** Row number for the aria labels of the extra rows ("2 "); empty for the first row. */
  prefix?: string
  badge?: string
  workspace: string
  canClone: boolean
  highlighted?: boolean
  liProps?: LiHTMLAttributes<HTMLLIElement>
  onMove: (to: number) => void
  onClone: () => void
  onReplace: () => void
  onLibrary: () => void
  onRemove: () => void
}

export function ReferenceItem(props: ReferenceItemProps) {
  const { file, index, count, prefix = '', badge, workspace, canClone, highlighted, liProps } = props
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const label = (text: string) => `${text} ${prefix}${index + 1}`
  return (
    <li {...liProps} className={`rounded-lg border p-2 ${highlighted ? 'border-accent-blue' : 'border-border'}`}>
      <div className="flex items-center gap-2">
        <span className="w-6 text-center text-sm text-text-primary">{index + 1}</span>
        <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded">
          <EditableImageReference key={`${workspace}:${file.name}:${file.lastModified}`} file={file} />
        </div>
        <span className="min-w-0 flex-1 truncate text-xs text-text-secondary">
          {badge ? `${badge} · ` : ''}
          {file.name}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <button type="button" className={rowButton} disabled={index === 0} aria-label={label(t('imageRef.up'))} onClick={() => props.onMove(index - 1)}>{t('imageRef.up')}</button>
        <button type="button" className={rowButton} disabled={index === count - 1} aria-label={label(t('imageRef.down'))} onClick={() => props.onMove(index + 1)}>{t('imageRef.down')}</button>
        <button type="button" className={rowButton} disabled={!canClone} aria-label={label(t('imageRef.clone'))} onClick={props.onClone}>{t('imageRef.clone')}</button>
        <button type="button" className={rowButton} aria-label={label(t('imageRef.replace'))} onClick={props.onReplace}>{t('imageRef.replace')}</button>
        <button type="button" className={rowButton} aria-label={label(t('imageRef.library'))} onClick={props.onLibrary}>{t('imageRef.library')}</button>
        <button type="button" className={rowButton} aria-label={label(tCommon('picker.remove'))} onClick={props.onRemove}>{tCommon('picker.remove')}</button>
      </div>
    </li>
  )
}

type ExtraRowsProps = {
  maxRefs: number | null
  workspace: string
  items: ComponentProps<typeof AssetInput>['items']
  onChoose: (row: number, item: ApiOutput) => void
  onReplace: (row: number, index: number) => void
  onLibrary: (row: number, index: number) => void
}

/** Rows 2…n: each one is its own generation. Row 1 stays in ImageRefSection. */
export function ExtraReferenceRows({ maxRefs, workspace, items, onChoose, onReplace, onLibrary }: ExtraRowsProps) {
  const { t } = useUiTranslation('studio')
  const rows = useStore(s => s.imageRefRows) || []
  const removeRow = useStore(s => s.removeImageRefRow)
  const removeFromRow = useStore(s => s.removeImageRefFromRow)
  const reorderInRow = useStore(s => s.reorderImageRefInRow)
  const cloneInRow = useStore(s => s.cloneImageRefInRow)
  return <>
    {rows.map((files, row) => {
      const room = maxRefs == null || files.length < maxRefs
      return (
        <section key={`row-${row}`} className="space-y-2 rounded-lg border border-border p-2" aria-label={t('imageRef.row', { count: row + 2 })}>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-text-primary">{t('imageRef.row', { count: row + 2 })}</p>
            <button type="button" className={rowButton} onClick={() => removeRow(row)}>{t('imageRef.removeRow')}</button>
          </div>
          <ul className="space-y-2">
            {files.map((file, i) => (
              <ReferenceItem
                key={`${row}-${i}-${file.name}-${file.lastModified}`}
                file={file} index={i} count={files.length} prefix={`${row + 2} `}
                workspace={workspace} canClone={room}
                onMove={to => reorderInRow(row, i, to)}
                onClone={() => cloneInRow(row, i)}
                onReplace={() => onReplace(row, i)}
                onLibrary={() => onLibrary(row, i)}
                onRemove={() => removeFromRow(row, i)}
              />
            ))}
          </ul>
          {room && (
            <AssetInput
              label={t('imageRef.add')}
              placeholder={t('imageRef.add')}
              items={items}
              accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
              workspaceId={workspace}
              keepLocal
              constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
              onChoose={item => { if (item) onChoose(row, item) }}
            />
          )}
        </section>
      )
    })}
  </>
}
