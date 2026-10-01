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

function speechModelKind(modelType: string) {
  return /tts|kugelaudio/.test(modelType)
}

function chosenSpeechModel(model: string, models: { model_type: string }[], selected: string | undefined) {
  if (model) return model
  if (models.some(item => item.model_type === selected)) return selected || ''
  const custom = models.find(item => item.model_type === 'qwen3_tts_customvoice')
  return custom?.model_type || models[0]?.model_type || ''
}

function speechSample(language: string | undefined) {
  const spanish = language?.startsWith('es') === true
  return {
    spanish,
    text: spanish ? 'Hola. Mamá, Pepe y Lola miran un farol azul. A, e, i, o, u.' : 'Hello! This is a quick voice test. Watch my lips move as I speak.',
    root: `/speech-examples/${spanish ? 'spanish' : 'english'}-preview`,
  }
}

function previewCanPlay(ready: boolean, busy: boolean, mouthCount: number) {
  return ready && !busy && mouthCount > 0
}

function plainText(translate: unknown) {
  const call = translate as (key: string, values?: Record<string, string | number>) => string
  return (key: string, values?: Record<string, string | number>) => call(key, values)
}

function PlayLabel({ playing, text }: { playing: boolean; text: (key: string) => string }) {
  const label = playing ? 'lips.stop' : 'lips.play'
  return <>{playing ? <Square size={15} /> : <Play size={15} />}{text(label)}</>
}

export function LipsSpeechPreview({ pack, workspace, onActiveState }: {
  pack: CharacterKit; workspace: string; onActiveState: (state: CharacterMouthState | undefined) => void
}) {
  const { t, i18n } = useUiTranslation('characters')
  const say = plainText(t)
  const sampleCopy = speechSample(i18n.resolvedLanguage)
  const spanish = sampleCopy.spanish
  const sampleText = sampleCopy.text
  const sampleRoot = sampleCopy.root
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
  const speechModels = models.filter(item => speechModelKind(item.model_type) && item.is_downloaded !== false)
  const speechModel = chosenSpeechModel(model, speechModels, selectedSpeechModel)
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
  const pose = mouthPose(pack, active, onCharacter, inspecting, fromState, toState, manualProgress, say)
  const canPlay = previewCanPlay(Boolean(preview), busy, Object.keys(pack.mouth).length)
  return <section aria-label={t('lips.preview')} className="space-y-4 rounded-xl border border-border bg-bg-secondary p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{t('lips.preview')}</h3>
      {pack.base && <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={onCharacter} onChange={event => setOnCharacter(event.target.checked)} />{t('lips.onCharacter')}</label>}
    </div>
    <LipsMouthStage pack={pack} pose={pose} morph={morph} onCharacter={onCharacter} playing={playing} morphDuration={morphDuration} transitionWindow={transitionWindow} resetToken={resetToken} onSupportChange={setMorphSupported} />
    <p className="text-center text-xs text-text-muted">{pose.label}{pose.mouth ? '' : ` · ${t('lips.missing')}`}</p>
    <LipsMorphControls morph={morph} supported={morphSupported} playing={playing} duration={morphDuration} progress={manualProgress} available={pose.available} from={pose.from} to={pose.to}
      onMorph={value => { setMorph(value); setInspecting(false) }} onDuration={setMorphDuration} onProgress={value => { setManualProgress(value); setInspecting(true) }}
      onInspect={open => { if (!playing) setInspecting(open) }} onFrom={state => { setFromState(state); setInspecting(true) }} onTo={state => { setToState(state); setInspecting(true) }} text={say} />
    <button type="button" disabled={!canPlay} className="flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-black disabled:opacity-40"
      onClick={() => { if (playing) audio.current?.pause(); else void audio.current?.play().catch(cause => setError((cause as Error).message)) }}>
      <PlayLabel playing={playing} text={say} />
    </button>
    <p className="text-sm text-text-secondary">{preview?.text ?? sampleText}</p>
    <audio ref={audio} controls src={preview?.url} preload="metadata" className="w-full" />
    <LipsPhrasePanel pack={pack} textValue={text} busy={busy} speechModel={speechModel} speechModels={speechModels} custom={Boolean(custom)}
      onText={setText} onModel={setModel} onGenerate={() => void run()} onFile={file => void run(file)}
      onReset={() => { audio.current?.pause(); setCustom(undefined); onActiveState(undefined) }} label={say} />
    {busy && <p role="status" className="text-xs text-text-muted">{t('lips.working')}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>
}

type Pose = {
  mouthState: CharacterMouthState
  mouth: CharacterKit['mouth'][CharacterMouthState]
  available: CharacterMouthState[]
  from: CharacterMouthState | undefined
  to: CharacterMouthState | undefined
  manual: { from: LipsMorphImage; to: LipsMorphImage; progress: number } | undefined
  mouthClass: string
  mouthStyle: ReturnType<typeof faceRigOverlayPreviewStyle> | undefined
  label: string
  imageFor: (state: CharacterMouthState) => LipsMorphImage
}

function mouthImage(pack: CharacterKit, onCharacter: boolean, state: CharacterMouthState): LipsMorphImage {
  const placed = onCharacter && pack.base
  return { source: pack.mouth[state]?.source ?? '', ...(placed ? { anchor: faceRigAnchorFor(pack, 'base', state) } : {}) }
}

function pickedState(available: CharacterMouthState[], chosen: CharacterMouthState, fallback: number) {
  return available.includes(chosen) ? chosen : available[fallback]
}

function mouthPose(pack: CharacterKit, active: CharacterMouthState | undefined, onCharacter: boolean, inspecting: boolean, fromState: CharacterMouthState, toState: CharacterMouthState, manualProgress: number, text: (key: string) => string): Pose {
  const mouthState = active ?? mouthStateForSound('rest', pack.mouthMapping)
  const available = CHARACTER_MOUTH_STATES.filter(state => pack.mouth[state]?.source)
  const from = pickedState(available, fromState, 0)
  const to = pickedState(available, toState, 1) ?? available[0]
  const placed = Boolean(onCharacter && pack.base)
  const imageFor = (state: CharacterMouthState) => mouthImage(pack, onCharacter, state)
  const manual = inspecting && from && to ? { from: imageFor(from), to: imageFor(to), progress: manualProgress / 100 } : undefined
  const label = manual ? `${text(`faceRig.states.${from}`)} → ${text(`faceRig.states.${to}`)} · ${manualProgress}%` : text(`faceRig.states.${mouthState}`)
  return {
    mouthState, mouth: pack.mouth[mouthState], available, from, to, manual, imageFor, label,
    mouthClass: placed ? 'absolute object-contain' : 'max-h-[65%] max-w-[75%] object-contain',
    mouthStyle: placed ? faceRigOverlayPreviewStyle(faceRigAnchorFor(pack, 'base', mouthState)) : undefined,
  }
}

function LipsMouthStage({ pack, pose, morph, onCharacter, playing, morphDuration, transitionWindow, resetToken, onSupportChange }: {
  pack: CharacterKit; pose: Pose; morph: boolean; onCharacter: boolean; playing: boolean
  morphDuration: number; transitionWindow: number; resetToken: number; onSupportChange: (supported: boolean) => void
}) {
  const showBase = Boolean(onCharacter && pack.base)
  return <div className="relative mx-auto flex aspect-square max-h-64 w-full max-w-64 items-center justify-center overflow-hidden rounded-xl bg-bg-primary">
    {showBase && pack.base && <img src={pack.base.source} alt="" className="absolute inset-0 h-full w-full object-contain" />}
    <LipsMouthPicture pose={pose} morph={morph} playing={playing} morphDuration={morphDuration} transitionWindow={transitionWindow} resetToken={resetToken} onSupportChange={onSupportChange} />
  </div>
}

function LipsMouthPicture({ pose, morph, playing, morphDuration, transitionWindow, resetToken, onSupportChange }: {
  pose: Pose; morph: boolean; playing: boolean; morphDuration: number; transitionWindow: number; resetToken: number
  onSupportChange: (supported: boolean) => void
}) {
  if (!pose.mouth) return <Volume2 size={36} strokeWidth={1.2} className="text-text-muted" />
  if (!morph) return <img src={pose.mouth.source} alt={pose.label} className={pose.mouthClass} style={pose.mouthStyle} />
  return <LipsMorphPreview image={pose.imageFor(pose.mouthState)} images={pose.available.map(pose.imageFor)} manual={pose.manual}
    duration={Math.min(morphDuration, transitionWindow)} animate={playing} resetToken={resetToken} alt={pose.label}
    fallbackClassName={pose.mouthClass} fallbackStyle={pose.mouthStyle} onSupportChange={onSupportChange} />
}

function LipsMorphControls({ morph, supported, playing, duration, progress, available, from, to, onMorph, onDuration, onProgress, onInspect, onFrom, onTo, text }: {
  morph: boolean; supported: boolean; playing: boolean; duration: number; progress: number
  available: CharacterMouthState[]; from: CharacterMouthState | undefined; to: CharacterMouthState | undefined
  onMorph: (value: boolean) => void; onDuration: (value: number) => void; onProgress: (value: number) => void
  onInspect: (open: boolean) => void; onFrom: (state: CharacterMouthState) => void; onTo: (state: CharacterMouthState) => void
  text: (key: string) => string
}) {
  return <div className="space-y-3 rounded-lg border border-border p-3">
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={morph} disabled={available.length < 2}
      onChange={event => onMorph(event.target.checked)} />{text('lips.morph')}</label>
    {morph && <LipsMorphSliders supported={supported} playing={playing} duration={duration} progress={progress} available={available} from={from} to={to}
      onDuration={onDuration} onProgress={onProgress} onInspect={onInspect} onFrom={onFrom} onTo={onTo} text={text} />}
  </div>
}

function LipsMorphSliders({ supported, playing, duration, progress, available, from, to, onDuration, onProgress, onInspect, onFrom, onTo, text }: {
  supported: boolean; playing: boolean; duration: number; progress: number
  available: CharacterMouthState[]; from: CharacterMouthState | undefined; to: CharacterMouthState | undefined
  onDuration: (value: number) => void; onProgress: (value: number) => void; onInspect: (open: boolean) => void
  onFrom: (state: CharacterMouthState) => void; onTo: (state: CharacterMouthState) => void; text: (key: string) => string
}) {
  return <>
    <label className="block text-xs text-text-secondary">{text('lips.morphDuration')} · {duration} ms
      <input type="range" aria-label={text('lips.morphDuration')} min={40} max={240} step={10} value={duration}
        onChange={event => onDuration(Number(event.target.value))} className="mt-2 w-full accent-cyan-400" />
    </label>
    <p className="text-xs text-text-muted">{text('lips.morphHint')}</p>
    {!supported && <p role="status" className="text-xs text-amber-200">{text('lips.morphUnavailable')}</p>}
    <details onToggle={event => onInspect(event.currentTarget.open)} className="rounded-lg border border-border p-2">
      <summary className="cursor-pointer text-xs text-text-secondary">{text('lips.morphCompare')}</summary>
      <fieldset disabled={playing} className="mt-3 space-y-3 disabled:opacity-50">
        <div className="grid grid-cols-2 gap-2">
          <MouthSide label={text('lips.morphFrom')} value={from} states={available} onChange={onFrom} text={text} />
          <MouthSide label={text('lips.morphTo')} value={to} states={available} onChange={onTo} text={text} />
        </div>
        <label className="block text-xs text-text-secondary">{text('lips.morphProgress')} · {progress}%
          <input type="range" aria-label={text('lips.morphProgress')} min={0} max={100} step={1} value={progress}
            onChange={event => onProgress(Number(event.target.value))} className="mt-2 w-full accent-cyan-400" />
        </label>
        <p className="text-xs text-text-muted">{text('lips.morphCompareHint')}</p>
      </fieldset>
    </details>
  </>
}

function MouthSide({ label, value, states, onChange, text }: {
  label: string; value: CharacterMouthState | undefined; states: CharacterMouthState[]
  onChange: (state: CharacterMouthState) => void; text: (key: string) => string
}) {
  return <label className="text-xs text-text-secondary">{label}
    <select aria-label={label} value={value} onChange={event => onChange(event.target.value as CharacterMouthState)}
      className="mt-1 min-h-9 w-full rounded-lg border border-border bg-bg-primary p-1">
      {states.map(state => <option key={state} value={state}>{text(`faceRig.states.${state}`)}</option>)}
    </select>
  </label>
}

function LipsPhrasePanel({ pack, textValue, busy, speechModel, speechModels, custom, onText, onModel, onGenerate, onFile, onReset, label }: {
  pack: CharacterKit; textValue: string; busy: boolean; speechModel: string
  speechModels: { model_type: string; name: string }[]; custom: boolean
  onText: (value: string) => void; onModel: (value: string) => void; onGenerate: () => void
  onFile: (file: File) => void; onReset: () => void; label: (key: string) => string
}) {
  const needsModel = !pack.voice
  const blocked = busy || !textValue.trim() || (needsModel && !speechModel)
  return <details className="rounded-lg border border-border p-3">
    <summary className="cursor-pointer text-sm text-text-secondary">{label('lips.customPhrase')}</summary>
    <div className="mt-3 space-y-3">
      <textarea aria-label={label('lips.phrase')} rows={2} maxLength={2000} value={textValue} disabled={busy} onChange={event => onText(event.target.value)} className="w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" />
      {needsModel && <select aria-label={label('lips.voiceModel')} value={speechModel} onChange={event => onModel(event.target.value)} disabled={busy} className="w-full rounded-lg border border-border bg-bg-primary p-2 text-sm">
        {!speechModels.length && <option value="">{label('lips.noVoiceModel')}</option>}
        {speechModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
      </select>}
      <button type="button" disabled={blocked} onClick={onGenerate} className="min-h-10 rounded-lg border border-border px-3 text-sm disabled:opacity-40">{label(busy ? 'lips.working' : 'lips.generateVoice')}</button>
      <label className="block text-xs text-text-secondary">{label('lips.uploadAudio')}<input type="file" accept="audio/*" disabled={busy} className="mt-2 block w-full" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onFile(file) }} /></label>
      {custom && <button type="button" disabled={busy} onClick={onReset} className="text-xs text-cyan-300">{label('lips.defaultSample')}</button>}
    </div>
  </details>
}
