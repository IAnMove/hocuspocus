import { useUiTranslation } from '../../i18n'
import { TemplateLibraryPanel } from '../templates/TemplateLibraryPanel'
import { parseScene3DDocument } from './document.ts'
import { packFromApplied } from './templateLibraryModel'
import { Scene3DWorkspaceTemplates } from './Scene3DWorkspaceTemplates'
import type { Scene3DDocument } from './types.ts'
import type { World3DUserTemplate } from './userTemplates.ts'

/** "My templates" in the Video 3D shot library: the workspace's own templates (agents save there) and the server template library. */
export function Scene3DUserTemplates({ document, workspace, preview, disabled, selectedId, onApply }: {
  document: Scene3DDocument
  workspace?: string
  preview?: () => string | undefined
  disabled: boolean
  selectedId?: string
  onApply: (pack: World3DUserTemplate) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <>
    <Scene3DWorkspaceTemplates workspace={workspace} disabled={disabled} selectedId={selectedId} onApply={onApply} />
    <TemplateLibraryPanel editor="video3d" document={document} workspace={workspace} preview={preview} disabled={disabled} selectedId={selectedId}
      fallbackTitle={t(`template.${document.templateId}.title`)} testIdPrefix="world3d"
      parse={value => parseScene3DDocument(value) ?? undefined}
      onApply={(summary, parsed) => onApply(packFromApplied(summary, parsed))} />
  </>
}
