import { useEffect, useRef, useState } from 'react'
import { Download, Loader2, Mic } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { downloadModel } from '../../api/client'
import type { CustomCharacterVoice } from '../../lib/characterVoice'
import { SPOKEN_LANGUAGES, type SpokenLanguage } from '../../lib/speechLanguage'
import { designVoiceCandidates, referenceVoice, REFERENCE_VOICE_MODEL, SAMPLE_TEXT, VOICE_DESIGN_MODEL, type DesignedVoice } from './voiceDesign'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

function Metrics({ voice }: { voice: DesignedVoice }) {
  const { t } = useUiTranslation('characters')
  if (!voice.check) return null
  const { medianPitchHz, wordsPerSecond, wer, warnings } = voice.check
  return <div className="text-xs text-text-secondary">
    <p>{t('voiceDesigner.metrics', { pitch: medianPitchHz ? Math.round(medianPitchHz) : '—', pace: wordsPerSecond.toFixed(1), errors: Math.round(wer * 100) })}</p>
    {warnings.map(warning => <p key={warning} className="text-amber-200">{warning}</p>)}
  </div>
}

/** Describe a voice → three takes in one language, each transcribed and measured → keep one as the reference. */
export function CharacterVoiceDesigner({ workspace, characterName, initialLanguage = 'english', onUse, disabled }: {
  workspace: string; characterName: string; initialLanguage?: SpokenLanguage; disabled?: boolean
  onUse: (language: SpokenLanguage, voice: CustomCharacterVoice) => Promise<void> | void
}) {
  const { t } = useUiTranslation('characters')
  const models = useStore(state => state.models)
  const [language, setLanguage] = useState<SpokenLanguage>(initialLanguage)
  const [description, setDescription] = useState(''), [text, setText] = useState(SAMPLE_TEXT[initialLanguage] ?? '')
  const [voices, setVoices] = useState<DesignedVoice[]>([]), [busy, setBusy] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null)
  useEffect(() => () => operation.current?.abort(), [])
  const missing = [VOICE_DESIGN_MODEL, REFERENCE_VOICE_MODEL].filter(type => models.some(model => model.model_type === type && model.is_downloaded === false))

  const changeLanguage = (next: SpokenLanguage) => {
    if (!text.trim() || text === SAMPLE_TEXT[language]) setText(SAMPLE_TEXT[next] ?? '')
    setLanguage(next); setVoices([])
  }
  const run = async (label: string, task: (signal: AbortSignal) => Promise<void>) => {
    if (operation.current || disabled) return
    const controller = new AbortController(); operation.current = controller
    setBusy(label); setError(''); setMessage('')
    try { await task(controller.signal) } catch (cause) { if (!controller.signal.aborted) setError((cause as Error).message) }
    finally { if (!controller.signal.aborted) { operation.current = null; setBusy('') } }
  }
  const design = () => run('design', async signal => {
    const found = await designVoiceCandidates({ workspace, description: description.trim(), text: text.trim(), language, signal, onUpdate: setVoices })
    setMessage(t(found.some(voice => voice.status === 'ready') ? 'voiceDesigner.pick' : 'voiceDesigner.noneReady'))
  })
  const use = (voice: DesignedVoice) => run('use', async () => {
    await onUse(language, referenceVoice(voice, { name: `${characterName} (${language})`, text: text.trim(), language }))
    setMessage(t('voiceDesigner.saved', { language: t(`voiceDesigner.languages.${language}`) }))
  })
  const download = () => run('download', async () => {
    for (const type of missing) await downloadModel(type)
    setMessage(t('voiceDesigner.downloading'))
  })

  const blocked = Boolean(busy) || Boolean(disabled)
  return <div className="space-y-3 rounded-lg border border-border p-3" data-testid="character-voice-designer">
    <p className="text-xs text-text-muted">{t('voiceDesigner.hint')}</p>
    {missing.length > 0 && <div className="flex flex-wrap items-center gap-2 text-xs text-amber-200">
      <span>{t('voiceDesigner.missing', { models: missing.join(', ') })}</span>
      <button type="button" disabled={blocked} onClick={() => void download()} className={`${control} inline-flex items-center gap-1`}><Download size={14} />{t('voiceDesigner.download')}</button>
    </div>}
    <div className="grid gap-3 md:grid-cols-[12rem_minmax(0,1fr)]">
      <label className="block text-xs text-text-secondary">{t('voiceDesigner.language')}
        <select value={language} disabled={blocked} onChange={event => changeLanguage(event.target.value as SpokenLanguage)} className={`${control} mt-1 w-full`}>
          {SPOKEN_LANGUAGES.map(code => <option key={code} value={code}>{t(`voiceDesigner.languages.${code}`)}</option>)}
        </select></label>
      <label className="block text-xs text-text-secondary">{t('voiceDesigner.description')}
        <textarea value={description} maxLength={600} rows={2} disabled={blocked} onChange={event => setDescription(event.target.value)} placeholder={t('voiceDesigner.placeholder')} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" /></label>
    </div>
    <label className="block text-xs text-text-secondary">{t('voiceDesigner.text')}
      <textarea value={text} maxLength={600} rows={2} disabled={blocked} onChange={event => setText(event.target.value)} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" /></label>
    <button type="button" disabled={blocked || missing.includes(VOICE_DESIGN_MODEL) || !description.trim() || !text.trim()} onClick={() => void design()} className={`${control} inline-flex items-center gap-2 text-cyan-200`}>
      {busy === 'design' ? <Loader2 size={15} className="animate-spin" /> : <Mic size={15} />}{t('voiceDesigner.create')}</button>
    {voices.length > 0 && <ol className="space-y-2">
      {voices.map((voice, index) => <li key={voice.id} className="rounded-lg border border-border p-2" data-testid={`designed-${voice.id}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold">{t('voiceDesigner.option', { number: index + 1 })}</span>
          {voice.url && <audio controls src={voice.url} className="h-8 max-w-full" />}
          {(voice.status === 'generating' || voice.status === 'checking') && <span className="inline-flex items-center gap-1 text-xs text-text-muted">
            <Loader2 size={13} className="animate-spin" />{t(`voiceDesigner.${voice.status}`)}</span>}
          {voice.status === 'ready' && <button type="button" disabled={blocked} onClick={() => void use(voice)} className={`${control} text-emerald-200`}>{t('voiceDesigner.use')}</button>}
        </div>
        <Metrics voice={voice} />
        {voice.status === 'failed' && <p role="alert" className="text-xs text-red-300">{voice.error}</p>}
      </li>)}
    </ol>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </div>
}
