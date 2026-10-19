import { useEffect, useRef, useState } from 'react'
import { fetchAsset, type AssetCatalogItem } from '../../api/assets'
import { AssetInput } from '../asset-picker/AssetInput.tsx'
import { catalogItemToOutput } from '../asset-picker/adapters.ts'
import { useUiTranslation } from '../../i18n'
import { acceptForSlotKinds, commitTemplateSlotChoice } from './templateSlotPick.ts'

type PickerKind = 'image' | 'model3d' | 'video'

export interface TemplateAssetPickerProps {
  workspace: string
  kinds: readonly PickerKind[]
  selectedId?: string
  selected?: AssetCatalogItem
  onPick: (asset: AssetCatalogItem) => void
  disabledReason?: (asset: AssetCatalogItem) => string | undefined
  optional?: boolean
  onClear?: () => void
}

export function TemplateAssetPicker({
  workspace,
  kinds,
  selectedId,
  selected,
  onPick,
  disabledReason,
  optional,
  onClear,
}: TemplateAssetPickerProps) {
  const { t } = useUiTranslation('scene3d')
  const generationRef = useRef(0)
  const workspaceRef = useRef(workspace)
  const [issue, setIssue] = useState('')
  useEffect(() => {
    if (workspaceRef.current !== workspace) generationRef.current += 1
    workspaceRef.current = workspace
  }, [workspace])

  const value = selected ? catalogItemToOutput(selected, workspace) ?? undefined : undefined
  const slotId = selectedId || kinds.join('-')

  return (
    <div className="space-y-1">
      <AssetInput
        label={t('composer.searchLibrary')}
        placeholder={t('composer.searchPlaceholder')}
        items={[]}
        value={value}
        optional={optional}
        accept={acceptForSlotKinds(kinds)}
        workspaceId={workspace}
        constraints={{ kinds, maxCount: 1, optional: Boolean(optional) }}
        onChoose={item => {
          const capture = { generation: generationRef.current, workspaceId: workspaceRef.current, slotId }
          void commitTemplateSlotChoice(
            { generation: generationRef.current, workspaceId: workspaceRef.current, slotId },
            capture,
            item,
            id => fetchAsset(id),
            asset => disabledReason?.(asset),
          ).then(commit => {
            if (commit.action === 'ignore') return
            if (commit.action === 'reject') {
              setIssue(commit.reasonKey === 'missing-id' ? t('composer.needsCatalogIdentity') : commit.message)
              return
            }
            setIssue('')
            if (commit.action === 'clear') {
              onClear?.()
              return
            }
            onPick(commit.item)
          }).catch(error => {
            setIssue(error instanceof Error ? error.message : t('composer.loadAssetsFailed'))
          })
        }}
      />
      {issue && <p role="alert" className="text-[10px] text-amber-200">{issue}</p>}
    </div>
  )
}
