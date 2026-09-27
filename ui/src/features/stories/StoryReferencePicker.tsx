import { X } from 'lucide-react'
import type { ApiOutput } from '../../api/outputs'
import { ModalShell } from '../../components/common/ModalShell'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../asset-picker/AssetInput'

/** Keep the existing upload/library flow visible even on long character cards. */
export function StoryReferencePicker({ items, workspace, disabled, onChoose, onClose }: {
  items: ApiOutput[]
  workspace: string
  disabled: boolean
  onChoose: (item: ApiOutput) => void
  onClose: () => void
}) {
  const { t } = useUiTranslation('storyLab')
  const { t: common } = useUiTranslation('common')
  const title = t('world.addReference')
  return (
    <ModalShell open title={title} onClose={onClose}
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <div className="w-full max-w-lg rounded-xl border border-border bg-bg-primary p-4 shadow-xl">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
          <button type="button" aria-label={common('actions.close')} onClick={onClose}
            className="rounded p-1 text-text-secondary hover:bg-bg-tertiary"><X size={18} /></button>
        </div>
        <AssetInput label={title} placeholder={title} items={items} workspaceId={workspace}
          accept="image/*" constraints={{ kinds: ['image'], maxCount: 1, optional: true }}
          disabled={disabled} onChoose={item => { if (item) onChoose(item) }} />
      </div>
    </ModalShell>
  )
}
