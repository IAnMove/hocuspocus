import { SeriesField } from './components'
import { inputClass, textareaClass } from './styles'
import type { SeriesProject } from './types'
import { useUiTranslation } from '../../i18n'
import { CharacterKitLink } from '../characters/CharacterKitLink'
import { CharacterKitSummary } from '../characters/CharacterKitSummary'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { useStore } from '../../stores/useStore'
import { resolvedCharacterTts } from '../../lib/characterKit'

export function SeriesVoiceFields({
  series, onPatchVoice, onConfigureCharacter,
}: {
  series: SeriesProject
  onPatchVoice: (index: number, patch: Record<string, unknown>) => void
  onConfigureCharacter?: (id: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const workspace = useStore(s => s.activeWorkspace)
  const { kits, error } = useCharacterKitLibrary(workspace)
  return (
    <div className="space-y-3">
      {series.characters.map((character, index) => {
        const kit = kits.find(item => item.id === character.voiceProfile?.characterKitRef?.id)
        const tts = resolvedCharacterTts(kit, character.voiceProfile)
        const kitOwnsTts = tts.source === 'kit'
        return (
        <div key={character.id} className="rounded-lg border border-border p-3">
          <strong className="text-xs text-text-primary">{character.name || t('canon.character')}</strong>
          {onConfigureCharacter && <button type="button" className="ml-3 text-xs text-cyan-200 underline" onClick={() => onConfigureCharacter(character.id)}>{t('speech.configure')}</button>}
          <CharacterKitLink
            value={character.voiceProfile?.characterKitRef}
            kits={kits}
            error={error}
            onChange={characterKitRef => {
              const next = kits.find(item => item.id === characterKitRef?.id)
              onPatchVoice(index, {
                characterKitRef,
                ...(next?.voice ? { provider: next.voice.provider, voiceId: next.voice.voiceId } : {}),
              })
            }}
          />
          <CharacterKitSummary kit={kit} />
          <p className="mt-2 text-[10px] text-text-muted">{kitOwnsTts ? t('canon.kitTtsHint') : t('canon.unlinkedTtsHint')}</p>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <SeriesField label={t('canon.provider')}>
              <input className={inputClass} value={String(kitOwnsTts ? tts.provider || '' : character.voiceProfile?.provider || '')} disabled={kitOwnsTts} onChange={event => onPatchVoice(index, { provider: event.target.value })} />
            </SeriesField>
            <SeriesField label={t('canon.voiceId')} hint={t('canon.voiceIdHint')}>
              <input className={inputClass} value={String(kitOwnsTts ? tts.voiceId || '' : character.voiceProfile?.voiceId || '')} disabled={kitOwnsTts} onChange={event => onPatchVoice(index, { voiceId: event.target.value })} />
            </SeriesField>
            <SeriesField label={t('canon.language')}>
              <input className={inputClass} value={String(character.voiceProfile?.language || '')} onChange={event => onPatchVoice(index, { language: event.target.value })} />
            </SeriesField>
            <SeriesField label={t('canon.pace')}>
              <input className={inputClass} type="number" step="0.05" value={Number(character.voiceProfile?.pace ?? 1)} onChange={event => onPatchVoice(index, { pace: Number(event.target.value) })} />
            </SeriesField>
            <SeriesField label={t('canon.pitch')}>
              <input className={inputClass} type="number" step="0.05" value={Number(character.voiceProfile?.pitch ?? 0)} onChange={event => onPatchVoice(index, { pitch: Number(event.target.value) })} />
            </SeriesField>
            <SeriesField label={t('canon.emotion')}>
              <input className={inputClass} value={String(character.voiceProfile?.emotionalDefaults || '')} onChange={event => onPatchVoice(index, { emotionalDefaults: event.target.value })} />
            </SeriesField>
            <SeriesField label={t('canon.pronunciationLabel')}>
              <textarea className={textareaClass} value={Object.entries(character.voiceProfile?.pronunciationDictionary || {}).map(([word, pronunciation]) => `${word}=${pronunciation}`).join('\n')} placeholder={t('canon.pronunciationPlaceholder')} onChange={event => onPatchVoice(index, { pronunciationDictionary: Object.fromEntries(event.target.value.split('\n').map(line => line.split('=', 2).map(value => value.trim())).filter(parts => parts.length === 2 && parts[0])) })} />
            </SeriesField>
            <SeriesField label={t('canon.consent')}>
              <textarea className={textareaClass} value={String(character.voiceProfile?.consentSourceNote || '')} onChange={event => onPatchVoice(index, { consentSourceNote: event.target.value })} />
            </SeriesField>
          </div>
        </div>
        )
      })}
    </div>
  )
}
