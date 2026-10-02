import { useEffect, useRef, useState } from 'react'
import { BASE } from '../../../api/http'
import { setupSpeechPhonemes } from '../../../api/scene3dSpeech'
import { useUiTranslation } from '../../../i18n'
import { speechInput } from './FaceControls'
import { SPEECH_ENGINES, type SpeechAnalysisSettings, type SpeechEngine } from './types'

export function SpeechAnalysisControls({ settings, disabled, onChange, onBusyChange }: {
  settings: SpeechAnalysisSettings; disabled: boolean; onChange: (settings: SpeechAnalysisSettings) => void
  onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [runtime, setRuntime] = useState<{ installed: boolean; dependencies_available: boolean }>()
  const [error, setError] = useState(''), [installing, setInstalling] = useState(false)
  const job = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void fetch(`${BASE}/api/v1/character-kits/speech/capabilities`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(t('speech.analysis.unavailable'))
      const data = await response.json()
      if (!controller.signal.aborted) setRuntime(data.phonemes ?? { installed: false, dependencies_available: false })
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message) })
    return () => { controller.abort(); job.current?.abort() }
  }, [t])
  return <div className="space-y-2 text-xs" data-testid="speech-analysis-controls">
    <label className="block">{t('speech.analysis.engine')}
      <select className={speechInput + ' w-full'} aria-label={t('speech.analysis.engine')} disabled={disabled || installing}
        value={settings.analysisEngine ?? 'auto'} onChange={event => onChange({ ...settings, analysisEngine: event.target.value as SpeechEngine })}>
        {SPEECH_ENGINES.map(engine => <option key={engine} value={engine}>{t(`speech.analysis.${engine}`)}</option>)}
      </select>
    </label>
    <p role="status" className="text-text-muted">{t(`speech.analysis.${runtime ? runtime.installed ? 'installed' : 'missing' : 'loading'}`)}</p>
    {runtime && !runtime.installed && <button type="button" className={speechInput}
      disabled={disabled || installing || !runtime.dependencies_available} onClick={() => {
        const controller = new AbortController(); job.current = controller
        setInstalling(true); setError(''); onBusyChange?.(true)
        void setupSpeechPhonemes(true, controller.signal).then(value => {
          if (!controller.signal.aborted) setRuntime(value)
        }).catch(cause => { if (!controller.signal.aborted) setError(cause.message) }).finally(() => {
          if (!controller.signal.aborted) { setInstalling(false); onBusyChange?.(false) }
        })
      }}>{t(installing ? 'speech.analysis.installing' : 'speech.analysis.install')}</button>}
    <label className="block">{t('speech.analysis.transcript')}
      <textarea aria-label={t('speech.analysis.transcript')} className={speechInput + ' w-full'} rows={2} maxLength={4000}
        disabled={disabled || installing} value={settings.text ?? ''} onChange={event => onChange({ ...settings, text: event.target.value })} />
    </label>
    <p className="text-text-muted">{t('speech.analysis.transcriptHint')}</p>
    <label className="block">{t('speech.analysis.language')}
      <input aria-label={t('speech.analysis.language')} className={speechInput + ' w-full'} maxLength={16} disabled={disabled || installing}
        value={settings.language ?? ''} placeholder="en / es" onChange={event => onChange({ ...settings, language: event.target.value })} />
    </label>
    {settings.analysisFallback && <p role="status" className="text-amber-200">{t('speech.analysis.fallback')}</p>}
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </div>
}
