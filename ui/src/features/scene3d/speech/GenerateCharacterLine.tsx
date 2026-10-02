import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import { generateSceneSpeechClip, type SceneSpeechClip } from '../../../lib/sceneSpeech'
import type { CharacterVoice } from '../../../lib/characterVoice'
import { getPlayableFileUrl } from '../../../api/client'
import { analyzeSceneSpeechDetailed } from '../../../api/scene3dSpeech'
import { analysisDriver } from './analysis'
import { parseMouthCues } from './track'
import { decodeVoice, voiceWav } from './audio'
import type { SpeechClip } from './types'
import { speechInput } from './FaceControls'

export function GenerateCharacterLine({ clip, voice, workspace, disabled, onChange, onBusyChange }: {
  clip: SpeechClip; voice?: CharacterVoice; workspace: string; disabled: boolean
  onChange: (clip: SpeechClip) => void; onBusyChange: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const identity = JSON.stringify([workspace, clip.text?.trim(), voice])
  const [cached, setGenerated] = useState<{ identity: string; clip: SceneSpeechClip }>()
  const generated = cached?.identity === identity ? cached.clip : undefined
  const pending = useRef<AbortController | null>(null)
  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false) }, [busy, onBusyChange])
  useEffect(() => () => pending.current?.abort(), [])
  return <div className="space-y-2">
    <button data-testid="generate-character-line" className={speechInput} disabled={disabled || busy || !!clip.audio || !voice || !clip.text?.trim()}
      onClick={() => {
        // Existing audio always wins; neither load, save nor render creates jobs.
        if (clip.audio || !voice || !clip.text?.trim()) return
        const controller = new AbortController(); pending.current = controller
        setBusy(true); setError('')
        void (async () => {
          const result = generated ?? await generateSceneSpeechClip({ prompt: clip.text!, model: voice.model, voice, workspace,
            durationSeconds: (clip.end ?? clip.start + 5) - clip.start, signal: controller.signal })
          controller.signal.throwIfAborted()
          setGenerated({ identity, clip: result })
          const audio = { workspaceId: workspace, filename: result.filename, url: getPlayableFileUrl('', result.filename, workspace) }
          const buffer = await decodeVoice(audio.url)
          controller.signal.throwIfAborted()
          // Keep the produced file for retry; do not buy/generate it again or move another turn.
          if (buffer.duration > (clip.end ?? 600) - clip.start + .01) throw new Error(t('speech.voiceTooLong', { seconds: buffer.duration.toFixed(2), file: result.filename }))
          const analysis = await analyzeSceneSpeechDetailed(await voiceWav(buffer), { signal: controller.signal,
            dialogue: result.prompt, language: clip.language, engine: clip.analysisEngine ?? 'auto' })
          const cues = parseMouthCues(analysis)
          controller.signal.throwIfAborted()
          onChange({ ...clip, text: result.prompt, audio, cues, driver: analysisDriver(analysis), analysisFallback: analysis.fallbackReason ?? null,
            offset: 0, end: clip.start + buffer.duration, audible: true })
        })().catch(reason => { if (!controller.signal.aborted) setError(reason.message) })
          .finally(() => { if (!controller.signal.aborted) setBusy(false) })
      }}>{busy ? t('speech.busy') : generated ? t('speech.attachGeneratedVoice') : t('speech.generateVoice')}</button>
    <p className="text-xs text-text-muted">{clip.audio ? t('speech.existingAudioWins') : t('speech.explicitGeneration')}</p>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </div>
}
