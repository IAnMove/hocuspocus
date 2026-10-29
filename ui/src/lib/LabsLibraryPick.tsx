import { useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { AssetExplorerDialog } from '../components/common/AssetExplorerDialog'
import { useUiTranslation } from '../i18n'
import type { ApiOutput } from '../api/outputs'
import { fileFromOutput, loadWorkspaceImages } from './labsImagePick'

export function LabsLibraryPick({
  workspace,
  disabled,
  title,
  onFile,
  onError,
}: {
  workspace: string
  disabled?: boolean
  title?: string
  onFile: (file: File) => void
  onError?: (message: string) => void
}) {
  const { t } = useUiTranslation('common')
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<ApiOutput[]>([])
  const openLibrary = () => {
    setOpen(true)
    if (items.length) return
    void loadWorkspaceImages(workspace).then(setItems).catch(() => setItems([]))
  }
  return (
    <>
      <button type="button" disabled={disabled} title={disabled ? title : undefined} onClick={openLibrary} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary disabled:opacity-40">
        <FolderOpen size={10} />{t('picker.fromLibrary')}
      </button>
      <AssetExplorerDialog
        open={open}
        title={t('picker.fromLibrary')}
        items={items}
        constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
        onClose={() => setOpen(false)}
        onChoose={item => {
          setOpen(false)
          if (!item) return
          void fileFromOutput(item).then(onFile).catch(cause => {
            onError?.(cause instanceof Error ? cause.message : t('picker.uploadFailed'))
          })
        }}
      />
    </>
  )
}
