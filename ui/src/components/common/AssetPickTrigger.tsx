import { FolderOpen } from 'lucide-react'
import type { ApiOutput } from '../../api/outputs'
import { outputToPickerItem } from '../../features/asset-picker/adapters.ts'
import { assetPreviewUrl, formatAssetDate } from './assetExplorer.ts'
import { ImagePreview } from './ImagePreview'

export function AssetPickTrigger({
  label,
  selected,
  placeholder,
  onOpen,
  disabled,
}: {
  label: string
  selected?: ApiOutput
  placeholder: string
  onOpen: () => void
  disabled?: boolean
}) {
  const preview = selected ? assetPreviewUrl(selected) : ''
  const picked = selected ? outputToPickerItem(selected, '') : null
  return (
    <div className="block text-[9px] text-text-muted">
      {label}
      <div className="mt-0.5 flex w-full items-center gap-2 rounded border border-border bg-bg-primary px-1.5 py-1 text-left text-[10px] text-text-primary">
        {selected?.type === 'image' && preview ? <ImagePreview image={selected} className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded bg-bg-active">
          <img src={preview} alt={selected.name} className="h-full w-full object-contain" />
        </ImagePreview> : <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded bg-bg-active">
          {preview ? <img src={preview} alt="" className="h-full w-full object-cover" /> : <FolderOpen size={14} className="text-text-muted" />}
        </span>}
        <button type="button" disabled={disabled} onClick={onOpen} className="min-w-0 flex-1 text-left disabled:opacity-40">
          <span className="block truncate">{picked?.title ?? placeholder}</span>
          {picked && <span className="block truncate text-[8px] text-text-muted">{picked.filename}</span>}
          {selected && <span className="block text-[8px] text-text-muted">{formatAssetDate(selected)}</span>}
        </button>
      </div>
    </div>
  )
}
