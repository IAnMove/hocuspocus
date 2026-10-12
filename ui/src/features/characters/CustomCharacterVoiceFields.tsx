import { useUiTranslation } from '../../i18n'
import { CHARACTER_VOICE_LANGUAGES, REFERENCE_VOICE_MODELS, STYLED_REFERENCE_VOICE_MODELS, VOICE_STYLE_MAX_CHARS, type CustomCharacterVoice, type ReferenceVoiceModel } from '../../lib/characterVoice'
import { VoicePreview } from '../scene3d/speech/VoicePreview'
import { useVoiceReferenceCapture } from './useVoiceReferenceCapture'

const input = 'mt-1 min-h-10 w-full rounded border border-border bg-bg-primary p-2'
const button = 'min-h-10 rounded border border-border px-3 disabled:opacity-50'

/** `languages` narrows the selector, e.g. to one spoken language and automatic detection. */
export function CustomCharacterVoiceFields({ value, onChange, onBusyChange, languages = CHARACTER_VOICE_LANGUAGES }: {
  value: CustomCharacterVoice; onChange: (voice: CustomCharacterVoice) => void; onBusyChange?: (busy: boolean) => void
  languages?: readonly CustomCharacterVoice['language'][]
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const capture = useVoiceReferenceCapture(referenceAudio => onChange({ ...value, referenceAudio, transcript: '' }), onBusyChange)
  const busy = capture.state !== 'idle'
  const styled = STYLED_REFERENCE_VOICE_MODELS.includes(value.model)
  const setEngine = (model: ReferenceVoiceModel) => {
    const { instructions, ...rest } = value
    onChange({ ...rest, model, ...(STYLED_REFERENCE_VOICE_MODELS.includes(model) && instructions ? { instructions } : {}) })
  }
  return <div className="space-y-3 rounded-lg border border-border p-3" data-testid="custom-character-voice">
    <p>{t('speech.customVoice.hint')}</p>
    <fieldset disabled={busy} className="space-y-3">
      <label className="block">{t('speech.customVoice.name')}<input className={input} maxLength={120} value={value.name}
        onChange={event => onChange({ ...value, name: event.target.value })} /></label>
      <label className="block">{t('speech.customVoice.import')}<input className={input} type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.webm"
        onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) capture.importAudio(file) }} /></label>
      <button type="button" className={button} onClick={capture.record}>{t('speech.customVoice.record')}</button>
      <p className="text-text-muted">{t('speech.customVoice.recordHint')}</p>
      <label className="block">{t('speech.customVoice.transcript')}<textarea className={input} rows={3} maxLength={4000}
        placeholder={t('speech.customVoice.transcriptPlaceholder')} value={value.transcript}
        onChange={event => onChange({ ...value, transcript: event.target.value })} /></label>
      <label className="block">{t('speech.customVoice.engine')}<select data-testid="custom-voice-engine" className={input} value={value.model}
        onChange={event => setEngine(event.target.value as ReferenceVoiceModel)}>
        {REFERENCE_VOICE_MODELS.map(model => <option key={model} value={model}>{t(`speech.customVoice.engines.${model}`)}</option>)}
      </select></label>
      {styled && <label className="block">{t('speech.customVoice.style')}<textarea data-testid="custom-voice-style" className={input} rows={2}
        maxLength={VOICE_STYLE_MAX_CHARS} placeholder={t('speech.customVoice.stylePlaceholder')} value={value.instructions ?? ''}
        onChange={event => onChange({ ...value, instructions: event.target.value })} />
        <span className="text-text-muted">{t('speech.customVoice.styleHint')}</span></label>}
      <label className="block">{t('speech.customVoice.language')}<select className={input} value={value.language}
        onChange={event => onChange({ ...value, language: event.target.value as CustomCharacterVoice['language'] })}>
        {languages.map(language => <option key={language} value={language}>{t(`speech.customVoice.languages.${language}`)}</option>)}
      </select></label>
    </fieldset>
    {capture.state !== 'idle' && <div className="flex flex-wrap items-center gap-3">
      <span role="status">{t(`speech.customVoice.states.${capture.state}`)}</span>
      {capture.state === 'recording' && <button type="button" className={button} onClick={capture.stop}>{t('speech.stopRecording')}</button>}
      <button type="button" className={button} onClick={capture.cancel}>{t('speech.cancelRecording')}</button>
    </div>}
    {value.referenceAudio && <VoicePreview url={value.referenceAudio} disabled={busy} label={t('speech.customVoice.referencePreview')} />}
    <p className="text-text-muted">{t('speech.customVoice.saveHint')}</p>
    {capture.error && <p role="alert" className="text-red-300">{capture.error}</p>}
  </div>
}
