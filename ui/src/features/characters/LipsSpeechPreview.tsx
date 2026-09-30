import { useEffect, useRef, useState } from 'react'
import { Play, Square, Volume2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { getFileUrl } from '../../api/client'
import { analyzeSceneSpeechDetailed } from '../../api/scene3dSpeech'
import { createCharacterSpeechPreview } from '../../lib/characterSpeechPreview'
import { faceRigAnchorFor, faceRigOverlayPreviewStyle } from '../../lib/characterKitFaceRig'
import { CHARACTER_MOUTH_STATES, mouthStateForSound } from '../../lib/characterMouthStates'
import type { CharacterKit, CharacterMouthState } from '../../lib/characterKit'
import { parseMouthCues } from '../scene3d/speech/track'
import type { MouthCue } from '../scene3d/speech/types'
import { decodeVoice, voiceWav } from '../scene3d/speech/audio'
import { LipsMorphPreview, type LipsMorphImage } from './LipsMorphPreview'

type Preview = { url: string; cues: MouthCue[]; text: string }

export function LipsSpeechPreview({ pack, workspace, onActiveState }: {
  pack: CharacterKit; workspace: string; onActiveState: (state: CharacterMouthState | undefined) => void
}) {
  const { t, i18n } = useUiTranslation('characters')
  const spanish = i18n.resolvedLanguage?.startsWith('es')
  const sampleText = spanish ? 'Hola. Mamá, Pepe y Lola miran un farol azul. A, e, i, o, u.' : 'Hello! This is a quick voice test. Watch my lips move as I speak.'
  const sampleRoot = `/speech-examples/${spanish ? 'spanish' : 'english'}-preview`
  const [sample, setSample] = useState<Preview>()
  const [custom, setCustom] = useState<Preview>()
  const [text, setText] = useState(sampleText)
  const [playing, setPlaying] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [active, setActive] = useState<CharacterMouthState>(), [onCharacter, setOnCharacter] = useState(false)
  const [morph, setMorph] = useState(false), [morphDuration, setMorphDuration] = useState(100)
  const [morphSupported, setMorphSupported] = useState(true), [transitionWindow, setTransitionWindow] = useState(100)
  const [resetToken, setResetToken] = useState(0), [inspecting, setInspecting] = useState(false)
  const [fromState, setFromState] = useState<CharacterMouthState>('closed'), [toState, setToState] = useState<CharacterMouthState>('wide')
  const [manualProgress, setManualProgress] = useState(50)
  const audio = useRef<HTMLAudioElement>(null), controller = useRef<AbortController | null>(null), blobUrl = useRef<string | null>(null)
  const currentCue = useRef<MouthCue | undefined>(undefined)
  const selectedSpeechModel = useStore(state => state.selectedModelPerAudioSubMode.speech)
  const models = useStore(state => state.models)
  const [model, setModel] = useState('')
  const speechModels = models.filter(item => /tts|kugelaudio/.test(item.model_type) && item.is_downloaded !== false)
  const speechModel = model || (speechModels.some(item => item.model_type === selectedSpeechModel) ? selectedSpeechModel : speechModels.find(item => item.model_type === 'qwen3_tts_customvoice')?.model_type || speechModels[0]?.model_type) || ''
  const preview = custom ?? sample
  useEffect(() => {
    const abort = new AbortController()
    void fetch(`${sampleRoot}.json`, { signal: abort.signal }).then(response => {
      if (!response.ok) throw new Error(t('lips.sampleUnavailable'))
      return response.json()
    }).then(data => setSample({ url: `${sampleRoot}.${spanish ? 'wav' : 'mp3'}`, cues: parseMouthCues(data), text: sampleText }))
      .catch(cause => { if (!abort.signal.aborted) setError((cause as Error).message) })
    return () => abort.abort()
  }, [sampleRoot, sampleText, spanish, t])
  useEffect(() => () => { controller.current?.abort(); if (blobUrl.current) URL.revokeObjectURL(blobUrl.current) }, [])
  useEffect(() => {
    const element = audio.current
    if (!element || !preview) return
    let frame = 0
    const tick = () => {
      const cue = preview.cues.find(cue => element.currentTime >= cue.start && element.currentTime < cue.end)
      const state = mouthStateForSound(cue?.viseme ?? 'rest', pack.mouthMapping)
      if (cue !== currentCue.current) {
        currentCue.current = cue
        setTransitionWindow(cue ? Math.max(0, (cue.end - element.currentTime) * 750) : 0)
      }
      setActive(state); onActiveState(element.paused ? undefined : state)
      if (!element.paused && !element.ended) frame = requestAnimationFrame(tick)
    }
    const play = () => { setPlaying(true); setInspecting(false); currentCue.current = undefined; cancelAnimationFrame(frame); tick() }
    const pause = () => { setPlaying(false); cancelAnimationFrame(frame); onActiveState(undefined) }
    const seek = () => { setResetToken(token => token + 1); tick() }
    element.addEventListener('play', play); element.addEventListener('pause', pause)
    element.addEventListener('seeked', seek); element.addEventListener('ended', pause)
    if (!element.paused) tick()
    return () => {
      cancelAnimationFrame(frame)
      element.removeEventListener('play', play); element.removeEventListener('pause', pause)
      element.removeEventListener('seeked', seek); element.removeEventListener('ended', pause)
    }
  }, [preview, pack.mouthMapping, onActiveState])
  const run = async (file?: File) => {
    audio.current?.pause(); controller.current?.abort()
    const abort = new AbortController(); controller.current = abort
    setBusy(true); setError('')
    try {
      let next: Preview
      if (file) {
        if (file.size > 32 * 1024 * 1024) throw new Error(t('lips.audioLimit'))
        const url = URL.createObjectURL(file)
        try {
          const buffer = await decodeVoice(url, abort.signal)
          const data = await analyzeSceneSpeechDetailed(await voiceWav(buffer), { language: spanish ? 'es' : 'en', signal: abort.signal })
          next = { url, cues: parseMouthCues(data), text: file.name }
        } catch (cause) { URL.revokeObjectURL(url); throw cause }
        if (blobUrl.current) URL.revokeObjectURL(blobUrl.current)
        blobUrl.current = url
      } else {
        const result = await createCharacterSpeechPreview({ kit: pack, text, model: speechModel, workspace, language: spanish ? 'es' : 'en', signal: abort.signal })
        next = { url: getFileUrl(result.filename, workspace), cues: parseMouthCues(result.cues), text }
      }
      abort.signal.throwIfAborted(); setCustom(next)
    } catch (cause) { if (!abort.signal.aborted) setError((cause as Error).message) }
    finally { if (!abort.signal.aborted) setBusy(false) }
  }
  const mouthState = active ?? mouthStateForSound('rest', pack.mouthMapping)
  const mouth = pack.mouth[mouthState]
  const availableStates = CHARACTER_MOUTH_STATES.filter(state => pack.mouth[state]?.source)
  const imageFor = (state: CharacterMouthState): LipsMorphImage => ({ source: pack.mouth[state]?.source ?? '',
    ...(onCharacter && pack.base ? { anchor: faceRigAnchorFor(pack, 'base', state) } : {}) })
  const from = availableStates.includes(fromState) ? fromState : availableStates[0]
  const to = availableStates.includes(toState) ? toState : availableStates[1] ?? availableStates[0]
  const manual = inspecting && from && to ? { from: imageFor(from), to: imageFor(to), progress: manualProgress / 100 } : undefined
  const mouthClass = onCharacter && pack.base ? 'absolute object-contain' : 'max-h-[65%] max-w-[75%] object-contain'
  const mouthStyle = onCharacter && pack.base ? faceRigOverlayPreviewStyle(faceRigAnchorFor(pack, 'base', mouthState)) : undefined
  const mouthLabel = manual ? `${t(`faceRig.states.${from}`)} → ${t(`faceRig.states.${to}`)} · ${manualProgress}%` : t(`faceRig.states.${mouthState}`)
  return <section aria-label={t('lips.preview')} className="space-y-4 rounded-xl border border-border bg-bg-secondary p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{t('lips.preview')}</h3>
      {pack.base && <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={onCharacter} onChange={event => setOnCharacter(event.target.checked)} />{t('lips.onCharacter')}</label>}
    </div>
    <div className="relative mx-auto flex aspect-square max-h-64 w-full max-w-64 items-center justify-center overflow-hidden rounded-xl bg-bg-primary">
      {onCharacter && pack.base && <img src={pack.base.source} alt="" className="absolute inset-0 h-full w-full object-contain" />}
      {mouth ? morph ? <LipsMorphPreview image={imageFor(mouthState)} images={availableStates.map(imageFor)} manual={manual}
        duration={Math.min(morphDuration, transitionWindow)} animate={playing} resetToken={resetToken} alt={mouthLabel}
        fallbackClassName={mouthClass} fallbackStyle={mouthStyle} onSupportChange={setMorphSupported} />
        : <img src={mouth.source} alt={mouthLabel} className={mouthClass} style={mouthStyle} />
        : <Volume2 size={36} strokeWidth={1.2} className="text-text-muted" />}
    </div>
    <p className="text-center text-xs text-text-muted">{mouthLabel}{!mouth && ` · ${t('lips.missing')}`}</p>
    <div className="space-y-3 rounded-lg border border-border p-3">
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={morph} disabled={availableStates.length < 2}
        onChange={event => { setMorph(event.target.checked); setInspecting(false) }} />{t('lips.morph')}</label>
      {morph && <>
        <label className="block text-xs text-text-secondary">{t('lips.morphDuration')} · {morphDuration} ms
          <input type="range" aria-label={t('lips.morphDuration')} min={40} max={240} step={10} value={morphDuration}
            onChange={event => setMorphDuration(Number(event.target.value))} className="mt-2 w-full accent-cyan-400" />
        </label>
        <p className="text-xs text-text-muted">{t('lips.morphHint')}</p>
        {!morphSupported && <p role="status" className="text-xs text-amber-200">{t('lips.morphUnavailable')}</p>}
        <details onToggle={event => { if (!playing) setInspecting(event.currentTarget.open) }} className="rounded-lg border border-border p-2">
          <summary className="cursor-pointer text-xs text-text-secondary">{t('lips.morphCompare')}</summary>
          <fieldset disabled={playing} className="mt-3 space-y-3 disabled:opacity-50">
            <div className="grid grid-cols-2 gap-2">{(['from', 'to'] as const).map(side => <label key={side} className="text-xs text-text-secondary">{t(`lips.morph${side === 'from' ? 'From' : 'To'}`)}
              <select aria-label={t(`lips.morph${side === 'from' ? 'From' : 'To'}`)} value={side === 'from' ? from : to}
                onChange={event => { (side === 'from' ? setFromState : setToState)(event.target.value as CharacterMouthState); setInspecting(true) }}
                className="mt-1 min-h-9 w-full rounded-lg border border-border bg-bg-primary p-1">
                {availableStates.map(state => <option key={state} value={state}>{t(`faceRig.states.${state}`)}</option>)}
              </select>
            </label>)}</div>
            <label className="block text-xs text-text-secondary">{t('lips.morphProgress')} · {manualProgress}%
              <input type="range" aria-label={t('lips.morphProgress')} min={0} max={100} step={1} value={manualProgress}
                onChange={event => { setManualProgress(Number(event.target.value)); setInspecting(true) }} className="mt-2 w-full accent-cyan-400" />
            </label>
            <p className="text-xs text-text-muted">{t('lips.morphCompareHint')}</p>
          </fieldset>
        </details>
      </>}
    </div>
    <button type="button" disabled={!preview || busy || !Object.keys(pack.mouth).length} className="flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-black disabled:opacity-40"
      onClick={() => { if (playing) audio.current?.pause(); else void audio.current?.play().catch(cause => setError((cause as Error).message)) }}>
      {playing ? <Square size={15} /> : <Play size={15} />}{t(playing ? 'lips.stop' : 'lips.play')}
    </button>
    <p className="text-sm text-text-secondary">{preview?.text ?? sampleText}</p>
    <audio ref={audio} controls src={preview?.url} preload="metadata" className="w-full" />
    <details className="rounded-lg border border-border p-3">
      <summary className="cursor-pointer text-sm text-text-secondary">{t('lips.customPhrase')}</summary>
      <div className="mt-3 space-y-3">
        <textarea aria-label={t('lips.phrase')} rows={2} maxLength={2000} value={text} disabled={busy} onChange={event => setText(event.target.value)} className="w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" />
        {!pack.voice && <select aria-label={t('lips.voiceModel')} value={speechModel} onChange={event => setModel(event.target.value)} disabled={busy} className="w-full rounded-lg border border-border bg-bg-primary p-2 text-sm">
          {!speechModels.length && <option value="">{t('lips.noVoiceModel')}</option>}{speechModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
        </select>}
        <button type="button" disabled={busy || !text.trim() || (!pack.voice && !speechModel)} onClick={() => void run()} className="min-h-10 rounded-lg border border-border px-3 text-sm disabled:opacity-40">{t(busy ? 'lips.working' : 'lips.generateVoice')}</button>
        <label className="block text-xs text-text-secondary">{t('lips.uploadAudio')}<input type="file" accept="audio/*" disabled={busy} className="mt-2 block w-full" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run(file) }} /></label>
        {custom && <button type="button" disabled={busy} onClick={() => { audio.current?.pause(); setCustom(undefined); onActiveState(undefined) }} className="text-xs text-cyan-300">{t('lips.defaultSample')}</button>}
      </div>
    </details>
    {busy && <p role="status" className="text-xs text-text-muted">{t('lips.working')}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>
}
