import { X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { TemplateSummary } from '../../api/templates'
import { TemplateLibraryPanel } from '../templates/TemplateLibraryPanel'

type Scene2DDocument = { version: 1; name?: string; duration?: number; layers: unknown[] }

function parseScene2D(value: unknown): Scene2DDocument | undefined {
  const scene = value as Scene2DDocument | null
  return scene && typeof scene === 'object' && scene.version === 1 && Array.isArray(scene.layers) ? scene : undefined
}

/** "My templates" for Video 2D: the server template library in a dialog. */
export function Scene2DTemplateDialog({ scene, workspace, preview, disabled, onApply, onClose }: {
  scene: { name?: string; duration?: number }
  workspace: string
  preview: () => string | undefined
  disabled: boolean
  onApply: (summary: TemplateSummary, document: Scene2DDocument) => void
  onClose: () => void
}) {
  const { t } = useUiTranslation('common')
  return <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
    <div role="dialog" aria-modal="true" aria-label={t('templateLibrary.title')} onClick={event => event.stopPropagation()}
      className="max-h-[88vh] w-[64rem] max-w-[96vw] overflow-y-auto rounded-2xl border border-border bg-bg-secondary p-4 shadow-2xl">
      <div className="flex justify-end">
        <button type="button" onClick={onClose} aria-label={t('templateLibrary.cancel')} className="rounded p-1 text-text-muted hover:text-text-primary"><X size={16} /></button>
      </div>
      <TemplateLibraryPanel editor="video2d" document={scene} workspace={workspace} preview={preview} disabled={disabled}
        fallbackTitle={scene.name || 'Scene'} testIdPrefix="scene2d" parse={parseScene2D}
        onApply={(summary, document) => { onApply(summary, document); onClose() }} />
    </div>
  </div>
}
