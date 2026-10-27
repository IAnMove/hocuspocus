import { useEffect } from 'react'
import { useUiTranslation } from '../../i18n'
import type { Scene3DDeskModel } from './scene3dDeskModel'

/** Free orbit view, kept apart from the shot camera until the user writes it. */
export function Scene3DEditCameraBar({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3dEditor')
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'f' && event.key !== 'F') return
      if (event.metaKey || event.ctrlKey || event.altKey || !model.freeView) return
      const target = event.target
      if (target instanceof HTMLElement && target.closest('input, textarea, select')) return
      event.preventDefault()
      model.frameSelection()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [model])
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 z-10 flex flex-wrap gap-1" data-testid="scene3d-edit-camera">
      <button
        type="button"
        aria-pressed={model.freeView}
        disabled={model.exporting}
        onClick={() => model.setFreeView(!model.freeView)}
        className="pointer-events-auto min-h-10 rounded-lg border border-cyan-300/50 bg-black/80 px-3 text-xs font-semibold text-cyan-50 disabled:opacity-40"
      >
        {model.freeView ? t('desk.freeView') : t('desk.shotCamera')}
      </button>
      <button
        type="button"
        disabled={!model.freeView || model.editingLocked}
        onClick={model.frameSelection}
        className="pointer-events-auto min-h-10 rounded-lg border border-border bg-black/80 px-3 text-xs text-text-primary disabled:opacity-40"
      >
        {t('desk.frame')}
      </button>
      <button
        type="button"
        disabled={!model.freeView || model.editingLocked}
        onClick={model.commitFreeView}
        className="pointer-events-auto min-h-10 rounded-lg border border-border bg-black/80 px-3 text-xs text-text-primary disabled:opacity-40"
      >
        {t('desk.useView')}
      </button>
    </div>
  )
}
