import { lazy, Suspense, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'

const Preparation = lazy(() => import('./CharacterSpeechPreparation').then(module => ({ default: module.CharacterSpeechPreparation })))

export function CharacterDefinitionSpeechTools({ workspace, kit, disabled, onSaved }: {
  workspace: string; kit?: CharacterKit; disabled: boolean; onSaved: (library: CharacterKitLibrary) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false)
  return <div className="space-y-2">
    <button type="button" className="min-h-10 rounded border border-border px-3" disabled={disabled || !kit?.base}
      aria-expanded={open} onClick={() => setOpen(value => !value)}>{t('speech.configure2d')}</button>
    {!kit?.base && <p className="text-text-muted">{t('speech.need2dImage')}</p>}
    {open && kit?.base && <Suspense fallback={<p role="status">{t('speech.busy')}</p>}>
      <Preparation key={kit.id} workspace={workspace} initialKitId={kit.id} onSaved={onSaved} />
    </Suspense>}
  </div>
}
