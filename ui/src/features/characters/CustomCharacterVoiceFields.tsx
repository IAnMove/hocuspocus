import { useUiTranslation } from '../../i18n'
import { CHARACTER_VOICE_LANGUAGES, type CustomCharacterVoice } from '../../lib/characterVoice'
import { VoicePreview } from '../scene3d/speech/VoicePreview'
import { useVoiceReferenceCapture } from './useVoiceReferenceCapture'

const input = 'mt-1 min-h-10 w-full rounded border border-border bg-bg-primary p-2'
const button = 'min-h-10 rounded border border-border px-3 disabled:opacity-50'

export function CustomCharacterVoiceFields({ value, onChange, onBusyChange }: {
  value: CustomCharacterVoice; onChange: (voice: CustomCharacterVoice) => void; onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const capture = useVoiceReferenceCapture(referenceAudio => onChange({ ...value, referenceAudio, transcript: '' }), onBusyChange)
  const busy = capture.state !== 'idle'
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
      <label className="block">{t('speech.customVoice.language')}<select className={input} value={value.language}
        onChange={event => onChange({ ...value, language: event.target.value as CustomCharacterVoice['language'] })}>
        {CHARACTER_VOICE_LANGUAGES.map(language => <option key={language} value={language}>{t(`speech.customVoice.languages.${language}`)}</option>)}
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
