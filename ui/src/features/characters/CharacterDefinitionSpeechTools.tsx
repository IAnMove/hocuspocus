import { lazy, Suspense, useState, type RefObject } from 'react'
import type { SaveSpeechWorkshop } from './useCharacterSpeechLibrary'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'

const Preparation = lazy(() => import('./CharacterSpeechPreparation').then(module => ({ default: module.CharacterSpeechPreparation })))

export function CharacterDefinitionSpeechTools({ workspace, kit, disabled, onSaved, onDirtyChange, onBusyChange, saveRef }: {
  workspace: string; kit?: CharacterKit; disabled: boolean; onSaved: (library: CharacterKitLibrary) => void | Promise<void>
  saveRef?: RefObject<SaveSpeechWorkshop | null>
  onDirtyChange?: (dirty: boolean) => void; onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false)
  const [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false)
  return <div className="space-y-2">
    <button type="button" className="min-h-10 rounded border border-border px-3" disabled={disabled || dirty || busy || !kit?.base}
      aria-expanded={open} onClick={() => setOpen(value => !value)}>{t('speech.configure2d')}</button>
    {!kit?.base && <p className="text-text-muted">{t('speech.need2dImage')}</p>}
    {open && kit?.base && <Suspense fallback={<p role="status">{t('speech.busy')}</p>}>
      <Preparation key={kit.id} workspace={workspace} initialKitId={kit.id} onSaved={onSaved} saveRef={saveRef}
        onDirtyChange={value => { setDirty(value); onDirtyChange?.(value) }} onBusyChange={value => { setBusy(value); onBusyChange?.(value) }} />
    </Suspense>}
  </div>
}
