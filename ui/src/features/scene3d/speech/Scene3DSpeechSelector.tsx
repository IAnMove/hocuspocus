import { ChevronDown } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { Scene3DSlot } from '../types'

export function Scene3DSpeechSelector({ slots, selected, open, onToggle, onSelect }: {
  slots: Scene3DSlot[]; selected?: Scene3DSlot; open: boolean
  onToggle: () => void; onSelect: (id: string) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: sceneT } = useUiTranslation('scene3d')
  const characters = slots.filter(slot => slot.media === 'model3d')
  const selectedCharacter = selected?.media === 'model3d' ? selected.id : ''
  return <section className="rounded-xl border border-border bg-bg-secondary" data-testid="world3d-speech-section">
    <h3 className="text-sm font-semibold text-text-primary">
      <button type="button" data-testid="world3d-speech-toggle" aria-expanded={open} aria-controls="world3d-speech-inspector"
        disabled={!characters.length} onClick={() => {
          if (!open && !selectedCharacter) onSelect(characters[0].id)
          onToggle()
        }}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left disabled:opacity-40">
        <span>{t('speech.option')}</span>
        <ChevronDown size={16} aria-hidden="true" className={open ? 'rotate-180' : ''} />
      </button>
    </h3>
    {open && <div className="border-t border-border px-3 py-2">
      <label className="flex items-center gap-2 text-xs text-text-secondary">{t('speech.character')}
        <select aria-label={t('speech.character')} value={selectedCharacter} onChange={event => onSelect(event.target.value)}
          className="min-h-10 min-w-0 flex-1 rounded-lg border border-border bg-bg-primary px-2">
          {!selectedCharacter && <option value="" disabled>{t('speech.selectCharacter')}</option>}
          {characters.map(slot => <option key={slot.id} value={slot.id}>{slot.character?.name || sceneT(`stage.slot.${slot.slot}`)}</option>)}
        </select>
      </label>
    </div>}
  </section>
}
