import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import type { CharacterVoice, CharacterVoicesByLanguage } from '../../lib/characterVoice'
import { SPOKEN_LANGUAGES, type SpokenLanguage } from '../../lib/speechLanguage'
import { CharacterVoiceFields } from './CharacterVoiceFields'
import { CharacterVoiceDesigner } from './CharacterVoiceDesigner'

const newReference = (language: SpokenLanguage): CharacterVoice =>
  ({ provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: '', referenceAudio: '', transcript: '', language })

/** Optional dedicated voices per spoken language. The default voice keeps speaking every other language. */
export function CharacterLanguageVoices({ workspace, value, onChange, savedKits, disabled, onBusyChange, characterName = '' }: {
  workspace: string; value?: CharacterVoicesByLanguage; onChange: (voices: CharacterVoicesByLanguage | undefined) => void
  savedKits?: CharacterKit[]; disabled?: boolean; onBusyChange?: (busy: boolean) => void; characterName?: string
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [adding, setAdding] = useState<SpokenLanguage | ''>('')
  const [designing, setDesigning] = useState<SpokenLanguage | ''>('')
  const assigned = SPOKEN_LANGUAGES.filter(language => value?.[language])
  const available = SPOKEN_LANGUAGES.filter(language => !value?.[language])
  const set = (language: SpokenLanguage, voice: CharacterVoice | undefined) => {
    const next: CharacterVoicesByLanguage = { ...value }
    if (voice) next[language] = voice
    else delete next[language]
    onChange(Object.keys(next).length ? next : undefined)
  }
  return <fieldset disabled={disabled} data-testid="character-language-voices" className="space-y-3 rounded-lg border border-border p-3 text-xs">
    <legend className="px-1 font-medium">{t('speech.languageVoices.title')}</legend>
    <p className="text-text-muted">{t('speech.languageVoices.hint')}</p>
    {assigned.map(language => <div key={language} data-testid={`language-voice-${language}`} className="space-y-2 border-t border-border pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{t(`speech.customVoice.languages.${language}`)}</span>
        <span className="flex gap-1">
          <button type="button" className="min-h-10 px-2 underline" aria-expanded={designing === language}
            onClick={() => setDesigning(open => open === language ? '' : language)}>{t('speech.languageVoices.design')}</button>
          <button type="button" className="min-h-10 px-2 underline" onClick={() => set(language, undefined)}>
            {t('speech.languageVoices.remove')}</button>
        </span>
      </div>
      {designing === language && <CharacterVoiceDesigner workspace={workspace} characterName={characterName || t(`speech.customVoice.languages.${language}`)}
        initialLanguage={language} disabled={disabled} onUse={(chosen, voice) => { set(chosen, voice); setDesigning('') }} />}
      <CharacterVoiceFields workspace={workspace} language={language} value={value?.[language]} savedKits={savedKits}
        onBusyChange={onBusyChange} onChange={voice => set(language, voice)} />
    </div>)}
    {available.length > 0 && <div className="flex flex-wrap items-end gap-2">
      <label className="block">{t('speech.languageVoices.add')}
        <select data-testid="add-language-voice" className="mt-1 min-h-10 rounded border border-border bg-bg-primary px-2"
          value={adding} onChange={event => setAdding(event.target.value as SpokenLanguage | '')}>
          <option value="">{t('speech.languageVoices.choose')}</option>
          {available.map(language => <option key={language} value={language}>{t(`speech.customVoice.languages.${language}`)}</option>)}
        </select>
      </label>
      <button type="button" data-testid="add-language-voice-confirm" className="min-h-10 rounded border border-border px-3 disabled:opacity-50"
        disabled={!adding} onClick={() => { if (adding) { set(adding, newReference(adding)); setAdding('') } }}>
        {t('speech.languageVoices.addButton')}</button>
    </div>}
  </fieldset>
}
