import { useEffect, useRef, useState } from 'react'
import { getFileUrl } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import type { CharacterVoice } from '../../lib/characterVoice'
import { generateSceneSpeechClip } from '../../lib/sceneSpeech'

/** An explicit voice-only audition: no saved character or mouth rig required. */
export function CharacterVoiceAudition({ workspace, voice }: { workspace: string; voice: CharacterVoice }) {
  const { t, i18n } = useUiTranslation('scene3dEditor')
  const [language, setLanguage] = useState<'es' | 'en'>(i18n.resolvedLanguage?.startsWith('es') ? 'es' : 'en')
  const [filename, setFilename] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const stopAudio = () => { if (audio.current && !audio.current.paused) audio.current.pause() }
  useEffect(() => () => {
    controller.current?.abort()
    if (audio.current && !audio.current.paused) audio.current.pause()
  }, [])
  const cancel = () => { controller.current?.abort(); setBusy(false) }
  const generate = async () => {
    stopAudio()
    const owner = new AbortController(); controller.current = owner
    setBusy(true); setError(''); setFilename('')
    try {
      const sampleVoice = voice.model === 'qwen3_tts_base' ? { ...voice, language: language === 'es' ? 'spanish' as const : 'english' as const } : voice
      const result = await generateSceneSpeechClip({ workspace, model: voice.model, durationSeconds: 20,
        prompt: t(`speech.voiceAudition.sample.${language}`), signal: owner.signal, voice: sampleVoice })
      if (!owner.signal.aborted) setFilename(result.filename)
    } catch (cause) { if (!owner.signal.aborted) setError((cause as Error).message) }
    finally { if (!owner.signal.aborted) setBusy(false) }
  }
  return <div className="space-y-2 rounded-lg border border-border bg-bg-primary p-3">
    <label className="block">{t('speech.voiceAudition.language')}
      <select className="ml-2 min-h-10 rounded border border-border bg-bg-secondary px-2" value={language} disabled={busy}
        onChange={event => { stopAudio(); setLanguage(event.target.value as 'es' | 'en'); setFilename(''); setError('') }}>
        <option value="es">Español</option><option value="en">English</option>
      </select>
    </label>
    <p>{t(`speech.voiceAudition.sample.${language}`)}</p>
    <button type="button" disabled={busy} className="min-h-10 rounded bg-cyan-400 px-3 font-semibold text-black disabled:opacity-50"
      onClick={() => void generate()}>{t(busy ? 'speech.voiceAudition.generating' : 'speech.voiceAudition.generate')}</button>
    {busy && <button type="button" className="ml-3 min-h-10 underline" onClick={cancel}>{t('speech.voiceAudition.cancel')}</button>}
    {filename && <audio ref={node => { if (node) audio.current = node }} aria-label={t('speech.voiceAudition.audio')}
      controls preload="metadata" src={getFileUrl(filename, workspace)} className="w-full" />}
    <p className="text-text-muted">{t('speech.voiceAudition.hint')}</p>
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </div>
}
