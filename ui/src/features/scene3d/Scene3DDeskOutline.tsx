import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Scene3DObjectList } from './Scene3DObjectList'
import { Scene3DShotLibraryCard } from './Scene3DShotLibraryCard'
import type { Scene3DDeskModel } from './scene3dDeskModel'

export function Scene3DDeskOutline({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3dEditor')
  const full = model.editingLocked || model.sceneDoc.slots.length >= 64
  const sceneSelected = !model.selectedWorldSfxId && model.selectedId === ''
  return (
    <div className="space-y-3 p-2">
      <AddMenu model={model} full={full} />
      <Scene3DShotLibraryCard
        document={model.sceneDoc}
        userTemplateId={model.selectedUserTemplateId}
        applyDisabled={model.exporting}
        editingLocked={model.editingLocked}
        keepAssets={model.keepAssets}
        onKeepAssets={model.setKeepAssets}
        onTemplate={model.mountTemplate}
        onUserTemplate={model.mountUserTemplate}
        workspace={model.workspace}
        preview={model.preview}
      />
      <Scene3DObjectList
        slots={model.sceneDoc.slots}
        selectedId={model.selectedWorldSfxId ? undefined : model.selectedId || undefined}
        sceneLabel={t('desk.scene')}
        sceneSelected={sceneSelected}
        onSelect={model.selectSlot}
      />
      {model.selected?.slot === 'prop' && <button type="button" disabled={model.editingLocked} className="min-h-11 rounded-lg border border-border px-3 text-xs" onClick={model.removeSelected}>{t('props.remove')}</button>}
    </div>
  )
}

function AddMenu({ model, full }: { model: Scene3DDeskModel; full: boolean }) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const choose = (action: () => void) => {
    setOpen(false)
    action()
  }
  return (
    <div ref={root} className="relative">
      <button type="button" data-testid="scene3d-desk-add" aria-haspopup="menu" aria-expanded={open} disabled={model.editingLocked} onClick={() => setOpen(value => !value)} className="inline-flex h-8 items-center gap-1 rounded-lg border border-cyan-400/50 px-2 text-xs text-text-primary disabled:opacity-40">
        {t('desk.add')}<ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && <div role="menu" className="absolute left-0 top-full z-30 mt-1 flex min-w-44 flex-col gap-1 rounded-lg border border-border bg-bg-primary p-1 shadow-lg">
        <button type="button" role="menuitem" data-testid="scene3d-desk-new-object" disabled={model.editingLocked} className="rounded px-2 py-1.5 text-left text-xs disabled:opacity-40" onClick={() => choose(() => model.openPicker('prop'))}>{t('desk.addObject')}</button>
        <button type="button" role="menuitem" disabled={full} className="rounded px-2 py-1.5 text-left text-xs disabled:opacity-40" onClick={() => choose(model.addScreen)}>{t('screens.add')}</button>
        <button type="button" role="menuitem" disabled={model.editingLocked} className="rounded px-2 py-1.5 text-left text-xs disabled:opacity-40" onClick={() => choose(() => model.openPicker('all'))}>{t('desk.addPicker')}</button>
      </div>}
    </div>
  )
}
