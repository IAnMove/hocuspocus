import { useUiTranslation } from '../../i18n'
import { characterKitStillSource, resolvedCharacterTts, type CharacterKit } from '../../lib/characterKit'

/** Read-only look + TTS from the library character. Story acting notes stay on the story row. */
export function CharacterKitSummary({ kit }: { kit?: CharacterKit }) {
  const { t } = useUiTranslation('characters')
  if (!kit) return null
  const still = characterKitStillSource(kit)
  const tts = resolvedCharacterTts(kit)
  return (
    <div data-testid="character-kit-summary" className="flex flex-wrap items-start gap-3 rounded border border-border bg-bg-tertiary/40 p-2 text-[11px] text-text-secondary">
      {still ? (
        <img
          src={still}
          alt={t('sheet.stillAlt', { name: kit.name })}
          className="h-16 w-16 rounded object-contain bg-bg-primary"
        />
      ) : null}
      <div className="min-w-0 space-y-1">
        <p className="font-medium text-text-primary">{kit.name}</p>
        <p>
          {tts.source === 'kit'
            ? t('sheet.ttsVoice', { voiceId: tts.voiceName ?? tts.voiceId ?? '' })
            : t('sheet.ttsNone')}
        </p>
        {kit.lookNotes?.trim() ? <p className="text-text-muted">{kit.lookNotes}</p> : null}
        <p className="text-text-muted">{t('sheet.linkedHint')}</p>
      </div>
    </div>
  )
}
