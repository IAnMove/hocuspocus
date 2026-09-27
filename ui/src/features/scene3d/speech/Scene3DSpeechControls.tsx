import { useEffect, useRef, useState } from 'react'
import type { ApiOutput } from '../../../api/outputs'
import { fetchOutputs } from '../../../api/client'
import { analyzeSceneSpeech } from '../../../api/scene3dSpeech'
import { AssetInput } from '../../asset-picker/AssetInput'
import { useUiTranslation } from '../../../i18n'
import type { Scene3DSlot } from '../types'
import { sourceRefFromOutput } from '../slotSource'
import type { PlacementMode } from './calibration'
import { EXPRESSIONS, defaultSpeech, type FacePlacement, type Scene3DSpeech } from './types'
import { FACE_PACK_GLB, FACE_PACK_IDS, FACE_PACKS, applyBundledFacePack, facePackIdOf, talkingScreen } from './facePackExamples'
import { amplitudeCues, parseMouthCues } from './track'
import { decodeVoice, voiceWav } from './audio'
import { analysisWindow, mapFragmentCues, replaceCueInterval } from './cueEdit'
import { CueTimeline } from './CueTimeline'
import { importSpeechKit } from './kit'
import { SpeechNumber, speechInput } from './FaceControls'
import { LipsPlacementControls } from './LipsPlacementControls'
import { QuickVoiceControls } from './QuickVoiceControls'
import { exampleVoice, recordedVoice } from './quickVoice'
import { VoicePreview } from './VoicePreview'
import { VocalIsolationOption } from './VocalIsolationOption'
import { useVocalIsolation } from './useVocalIsolation'

export type SpeechControlsProps = {
  slot: Scene3DSlot; workspace: string; disabled: boolean
  calibrate: (profile: PlacementMode) => FacePlacement | undefined
  onChange: (speech: Scene3DSpeech) => void
  onImport: (patch: Partial<Scene3DSlot>) => void
  onFit: (duration: number) => void
  onBusyChange?: (busy: boolean) => void
  onPick?: () => void
}
export function Scene3DSpeechControls({ slot, workspace, disabled, calibrate, onChange, onImport, onFit, onBusyChange, onPick }: SpeechControlsProps) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: sceneT } = useUiTranslation('scene3d')
  const speech = slot.speech ?? defaultSpeech()
  const [items, setItems] = useState<ApiOutput[]>([])
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [recording, setRecording] = useState(false)
  const [isolateVocals, setIsolateVocals] = useVocalIsolation(slot, workspace, speech)
  const [jobs] = useState(() => ({ serial: 0, controller: null as AbortController | null }))
  const jsonInput = useRef<HTMLInputElement>(null), kitInput = useRef<HTMLInputElement>(null)
  useEffect(() => { onBusyChange?.(busy || recording); return () => onBusyChange?.(false) }, [busy, recording, onBusyChange])
  useEffect(() => {
    let alive = true
    void fetchOutputs(200, 0, { mediaType: 'audio', workspace }).then(result => { if (alive) setItems(result.outputs.filter(item => item.type === 'audio')) }).catch(() => {})
    return () => { alive = false; jobs.serial++; jobs.controller?.abort(); setBusy(false) }
  }, [workspace, slot.id, slot.sourceUrl, jobs])
  const applyVoice = (item: ApiOutput | null) => {
    if (disabled) return
    if (!item) {
      jobs.serial++
      jobs.controller?.abort()
      setBusy(false)
      onChange({ ...speech, audio: undefined, cues: [] })
      return
    }
    if (item.type !== 'audio') return
    void run(async () => {
      const buffer = await decodeVoice(item.url)
      return () => onChange({ ...speech, offset: 0, audio: sourceRefFromOutput(item, workspace), cues: amplitudeCues(buffer), driver: 'amplitude' })
    })
  }
  const run = async (task: (signal: AbortSignal) => Promise<() => void>) => {
    const generation = ++jobs.serial
    jobs.controller?.abort(); jobs.controller = new AbortController()
    setBusy(true); setError('')
    try {
      const commit = await task(jobs.controller.signal)
      if (generation === jobs.serial && !jobs.controller.signal.aborted) commit()
    } catch (caught) {
      if (generation === jobs.serial && !jobs.controller.signal.aborted) setError(caught instanceof Error ? caught.message : String(caught))
    } finally { if (generation === jobs.serial) setBusy(false) }
  }
  const locked = disabled || busy || recording
  const voiceDisabled = locked || !slot.sourceUrl
  const audioValue = speechAudioOutput(speech)
  return <section data-testid="scene3d-speech" className="space-y-3 rounded-xl border border-border bg-bg-secondary p-3 text-text-secondary">
    <h3 className="text-sm font-semibold text-text-primary">{t('speech.option')} · {slot.character?.name || sceneT(`stage.slot.${slot.slot}`)}</h3>
    <p className="text-xs leading-5">{t('speech.intro')}</p>
    {!slot.sourceUrl && <p className="text-xs text-text-muted">{t('speech.chooseModel')}</p>}
    <fieldset disabled={locked} className="space-y-2 disabled:opacity-60">
      <p className="text-xs font-medium text-text-primary">{t('speech.facePack')}</p>
      <p className="text-xs leading-5 text-text-muted">{t('speech.facePackHint')}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('speech.facePack')}>
        {FACE_PACK_IDS.map(id => {
          const selected = facePackIdOf(speech.facePack?.url) === id
          return <button key={id} type="button" aria-pressed={selected} data-testid={`face-pack-${id}`}
            className={`overflow-hidden rounded-lg border ${selected ? 'border-cyan-300 bg-cyan-300/15' : 'border-border bg-bg-primary hover:border-cyan-300/50'}`}
            onClick={() => {
              const next = applyBundledFacePack(speech, id)
              onImport({
                ...(slot.sourceUrl ? {} : { sourceUrl: FACE_PACK_GLB, media: 'model3d' as const }),
                screen: talkingScreen(id),
                speech: next,
              })
              onChange(next)
            }}>
            <img src={FACE_PACKS[id].url} alt="" width={40} height={40} className="h-10 w-10 object-cover object-left-top" />
            <span className="block px-1.5 pb-1 text-[10px] leading-4 text-text-secondary">{t(`speech.pack.${id}`)}</span>
          </button>
        })}
      </div>
      <label className="flex items-center gap-2 text-xs">{t('speech.expressionHold')}
        <select aria-label={t('speech.expressionHold')} className={speechInput} value={speech.expression}
          onChange={event => {
            const expression = event.target.value as Scene3DSpeech['expression']
            onChange({ ...speech, expression, expressionCues: undefined })
          }}>
          {EXPRESSIONS.map(expression => <option key={expression} value={expression}>{t(`speech.expression.${expression}`)}</option>)}
        </select>
      </label>
      <p className="text-xs leading-5 text-text-muted">{t('speech.expressionHoldHint')}</p>
      <p className="text-xs leading-5 text-text-muted">{t('speech.facePackMakerHint')}</p>
    </fieldset>
    <fieldset disabled={locked} className="space-y-3 disabled:opacity-60">
      <LipsPlacementControls speech={speech} hasModel={Boolean(slot.sourceUrl)} calibrate={calibrate} onChange={onChange} onPick={onPick} />
    </fieldset>
    <QuickVoiceControls disabled={voiceDisabled} onBusyChange={setRecording}
      onExample={() => void run(async signal => {
        const voice = await exampleVoice(workspace, signal)
        return () => { const { duration, ...patch } = voice; onChange({ ...speech, ...patch, offset: 0 }); onFit(speech.start + duration) }
      })}
      onAudio={blob => void run(async signal => {
        const voice = await recordedVoice(blob, workspace, signal)
        return () => { const { duration, ...patch } = voice; onChange({ ...speech, ...patch, offset: 0 }); onFit(speech.start + duration) }
      })} />
    {typeof window !== 'undefined' && !window.isSecureContext && <p role="note" className="text-xs text-amber-200">{t('speech.microphoneUnavailable')}</p>}
    {speech.audio && <VoicePreview url={speech.audio.url} disabled={locked} label={t('speech.voicePreview')} />}
    {(speech.audio || speech.cues.length > 0) && <CueTimeline speech={speech} disabled={locked} analyzing={busy}
      onChange={onChange} onReanalyze={(from, to) => void run(async signal => {
        const buffer = await decodeVoice(speech.audio!.url)
        const next = await analyzedSpeech(speech, buffer, from, to, signal, isolateVocals)
        return () => onChange(next)
      })} />}
    <fieldset disabled={locked} className="space-y-3 disabled:opacity-60">
      <AssetInput label={t('speech.voice')} placeholder={t('speech.pickVoice')} items={items} value={audioValue} optional
        disabled={voiceDisabled} workspaceId={workspace} accept="audio/*" constraints={{ kinds: ['audio'], maxCount: 1, optional: true }} onChoose={applyVoice} />
      <div className="flex flex-wrap gap-3">
        <button type="button" className={speechInput} disabled={!speech.audio} onClick={() => void run(async signal => {
          const buffer = await decodeVoice(speech.audio!.url)
          const span = Math.min(buffer.duration - speech.offset, (speech.end ?? speech.start + buffer.duration - speech.offset) - speech.start)
          const next = await analyzedSpeech(speech, buffer, speech.offset, speech.offset + span, signal, isolateVocals)
          return () => onChange(next)
        })}>{t('speech.analyze')}</button>
        <button type="button" className={speechInput} disabled={!speech.cues.length} onClick={() => onFit(Math.max(.1, speech.start + (speech.cues.at(-1)?.end ?? 0) - speech.offset))}>{t('speech.fit')}</button>
      </div>
      <VocalIsolationOption checked={isolateVocals} onChange={setIsolateVocals} />
      <p className="text-xs text-cyan-200" role="status">{t(`speech.driver.${speech.driver}`)} · {t('speech.cues', { count: speech.cues.length })}</p>
      {speech.driver === 'amplitude' && <p className="text-xs text-amber-200">{t('speech.amplitudeHint')}</p>}
      <div className="flex flex-wrap gap-3">
        <SpeechNumber label={t('speech.start')} value={speech.start} min={0} max={600} step={.1} onChange={start => onChange({ ...speech, start })} />
        <SpeechNumber label={t('speech.offset')} value={speech.offset} min={0} max={600} step={.1} onChange={offset => onChange({ ...speech, offset })} />
        <SpeechNumber label={t('speech.gain')} value={speech.gain} min={0} max={1} step={.05} onChange={gain => onChange({ ...speech, gain })} />
      </div>
      <details className="rounded-lg border border-border p-2">
        <summary className="cursor-pointer text-xs">{t('speech.advancedImport')}</summary>
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className={speechInput} onClick={() => kitInput.current?.click()}>{t('speech.importKit')}</button>
          <button type="button" className={speechInput} onClick={() => jsonInput.current?.click()}>{t('speech.importCues')}</button>
        </div>
      </details>
      <input ref={jsonInput} type="file" accept=".json,application/json" className="hidden" data-testid="speech-cues-file" onChange={event => {
        const file = event.target.files?.[0]; event.target.value = ''
        if (file) void run(async () => {
          if (file.size > 2 * 1024 * 1024) throw new Error('Cues JSON exceeds 2 MB.')
          const cues = parseMouthCues(JSON.parse(await file.text()))
          return () => onChange({ ...speech, cues, driver: 'imported' })
        })
      }} />
      <input ref={kitInput} type="file" accept=".zip,application/zip" className="hidden" data-testid="speech-kit-file" onChange={event => {
        const file = event.target.files?.[0]; event.target.value = ''
        if (file) void run(async signal => {
          const patch = await importSpeechKit(file, workspace, signal)
          return () => onImport(patch)
        })
      }} />
    </fieldset>
    {!speech.face && <p className="text-xs text-amber-200">{t('speech.needsPlacement')}</p>}
    {busy && <p role="status" className="text-xs">{t('speech.busy')}</p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}

async function analyzedSpeech(speech: Scene3DSpeech, buffer: AudioBuffer, from: number, to: number, signal: AbortSignal, isolateVocals: boolean): Promise<Scene3DSpeech> {
  const fragment = analysisWindow(from, to, buffer.duration)
  const localCues = await analyzeSceneSpeech(await voiceWav(buffer, fragment.start, fragment.duration), signal, isolateVocals)
  const mapped = mapFragmentCues(localCues, fragment.start)
  return { ...speech, cues: replaceCueInterval(speech.cues, fragment.start, fragment.start + fragment.duration, mapped),
    driver: isolateVocals ? 'rhubarb-vocals' : 'rhubarb' }
}

function speechAudioOutput(speech: Scene3DSpeech): ApiOutput | undefined {
  return speech.audio ? { name: speech.audio.filename, url: speech.audio.url, type: 'audio', mode: null, size: 0,
    created_at: 0, thumbnail_url: '', workspace_id: speech.audio.workspaceId, asset_id: speech.audio.assetId } : undefined
}
