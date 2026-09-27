import { useEffect, useRef, useState, type PointerEvent, type RefObject } from 'react'
import { useUiTranslation } from '../../../i18n'
import { VISEMES, type MouthCue, type Scene3DSpeech, type Viseme } from './types'
import { decodeVoice } from './audio'
import { safeMediaUrl } from './track'
import { SpeechNumber, speechInput } from './FaceControls'
import { addSilence, clipInterval, moveCueBound, setCueViseme, sourceToScene, waveformPeaks, type CueInterval } from './cueEdit'

export function CueTimeline({ speech, disabled, onChange, onReanalyze, analyzing }: {
  speech: Scene3DSpeech
  disabled: boolean
  onChange: (speech: Scene3DSpeech) => void
  onReanalyze?: (from: number, to: number) => void
  analyzing?: boolean
}) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [zoom, setZoom] = useState(1)
  const [loop, setLoop] = useState(false)
  const [selection, setSelection] = useState<CueInterval>()
  const [selected, setSelected] = useState(0)
  const [playhead, setPlayhead] = useState(0)
  const url = voiceUrl(speech)
  const wave = useVoiceWaveform(url)
  useSelectionLoop(audioRef, loop, selection)
  const span = timelineSpan(wave.duration, speech)
  const cue = speech.cues[Math.min(selected, Math.max(0, speech.cues.length - 1))]
  const locked = disabled || Boolean(analyzing)
  const choose = (start: number, end: number) => {
    const next = clipInterval(start, end, 0, span)
    if (next) setSelection(next)
  }
  return <section data-testid="speech-cue-timeline" className="space-y-2 rounded-lg border border-border p-2">
    <fieldset disabled={locked} className="space-y-2 disabled:opacity-60">
      <CueHeader clock={timelineClock(selection, playhead)} speech={speech} />
      <CueTrack span={span} zoom={zoom} bars={wave.peaks} speech={speech} cue={cue} selection={selection}
        locked={locked} playhead={playhead} onSelect={setSelected} onInterval={choose} />
      <CueTools url={url} span={span} zoom={zoom} loop={loop} selection={selection} locked={locked} audioRef={audioRef}
        onZoom={setZoom} onLoop={setLoop} onPlayhead={setPlayhead} onInterval={choose}
        onSilence={() => { if (selection) onChange({ ...speech, cues: addSilence(speech.cues, selection.start, selection.end) }) }}
        onReanalyze={onReanalyze} />
      {cue ? <CueFields cue={cue} speech={speech} onChange={onChange} /> : null}
    </fieldset>
  </section>
}

function voiceUrl(speech: Scene3DSpeech) {
  return speech.audio && safeMediaUrl(speech.audio.url) ? speech.audio.url : ''
}
function timelineSpan(duration: number, speech: Scene3DSpeech) {
  return Math.max(duration, speech.cues.at(-1)?.end ?? 0, speech.offset + .1, .1)
}
function timelineClock(selection: CueInterval | undefined, playhead: number) {
  const source = selection?.start ?? playhead
  return Number.isFinite(source) ? source : 0
}
function useVoiceWaveform(url: string) {
  const [duration, setDuration] = useState(0)
  const [peaks, setPeaks] = useState<number[]>([])
  useEffect(() => {
    if (!url) return
    let live = true
    void decodeVoice(url).then(buffer => {
      if (!live) return
      setDuration(buffer.duration)
      setPeaks(waveformPeaks(buffer.getChannelData(0), 80))
    }).catch(() => { if (live) setPeaks([]) })
    return () => { live = false }
  }, [url])
  return { duration: url ? duration : 0, peaks: url ? peaks : [] }
}
function useSelectionLoop(audioRef: RefObject<HTMLAudioElement | null>, loop: boolean, selection?: CueInterval) {
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !loop || !selection) return
    const tick = () => { if (outsideLoop(audio.currentTime, selection)) audio.currentTime = selection.start }
    tick(); audio.addEventListener('timeupdate', tick)
    return () => audio.removeEventListener('timeupdate', tick)
  }, [audioRef, loop, selection])
}
function outsideLoop(time: number, selection: CueInterval) {
  return time < selection.start || time >= selection.end - .02
}
function CueHeader({ clock, speech }: { clock: number; speech: Scene3DSpeech }) {
  const { t } = useUiTranslation('scene3dEditor')
  return <>
    <h4 className="text-xs font-semibold text-text-primary">{t('speech.timeline.title')}</h4>
    <p className="text-xs leading-5">{t('speech.timeline.clocks')}</p>
    <p className="text-xs text-cyan-200" role="status" data-testid="speech-cue-clocks">
      {t('speech.timeline.sourceTime', { seconds: clock.toFixed(2) })} · {t('speech.timeline.offsetTime', { seconds: speech.offset.toFixed(2) })} · {t('speech.timeline.sceneTime', { seconds: sourceToScene(clock, speech).toFixed(2) })}
    </p>
  </>
}
function CueTrack({ span, zoom, bars, speech, cue, selection, locked, playhead, onSelect, onInterval }: {
  span: number; zoom: number; bars: number[]; speech: Scene3DSpeech; cue?: MouthCue; selection?: CueInterval
  locked: boolean; playhead: number; onSelect: (index: number) => void; onInterval: (start: number, end: number) => void
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const drag = useRef<number | null>(null)
  const at = (clientX: number) => timeAtClient(trackRef.current, clientX, span)
  return <div className="overflow-x-auto">
    <div ref={trackRef} data-testid="speech-cue-track" className="relative min-h-24" style={{ width: `${Math.max(100, zoom * 100)}%` }}
      onPointerDown={event => beginDrag(event, locked, drag, at)}
      onPointerMove={event => { if (drag.current === null) return; onInterval(drag.current, at(event.clientX)) }}
      onPointerUp={() => { drag.current = null }}>
      <Waveform bars={bars} />
      <CueLane span={span} cues={speech.cues} cue={cue} selection={selection} offset={speech.offset} playhead={playhead}
        locked={locked} onSelect={onSelect} />
    </div>
  </div>
}
function beginDrag(event: PointerEvent<HTMLDivElement>, locked: boolean, drag: RefObject<number | null>, at: (x: number) => number) {
  if (locked) return
  drag.current = at(event.clientX)
  event.currentTarget.setPointerCapture?.(event.pointerId)
}
function timeAtClient(track: HTMLDivElement | null, clientX: number, span: number) {
  const rect = track?.getBoundingClientRect()
  if (!rect || rect.width <= 0 || !Number.isFinite(clientX)) return 0
  return Math.min(span, Math.max(0, ((clientX - rect.left) / rect.width) * span))
}
function Waveform({ bars }: { bars: number[] }) {
  const { t } = useUiTranslation('scene3dEditor')
  const peaks = bars.length ? bars : [0]
  return <div className="flex h-12 items-end gap-px rounded bg-slate-900 px-px" aria-label={t('speech.timeline.waveform')} data-testid="speech-cue-waveform">
    {peaks.map((peak, i) => <span key={i} className="flex-1 bg-cyan-300/80" style={{ height: `${Math.max(6, peak * 100)}%` }} />)}
  </div>
}
function CueLane({ span, cues, cue, selection, offset, playhead, locked, onSelect }: {
  span: number; cues: MouthCue[]; cue?: MouthCue; selection?: CueInterval; offset: number; playhead: number
  locked: boolean; onSelect: (index: number) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const percent = (time: number) => `${(time / span) * 100}%`
  return <div className="relative h-10">
    {cues.map((item, index) => <CueBar key={index} item={item} index={index} active={item === cue} locked={locked}
      label={item.manual ? ` · ${t('speech.timeline.manual')}` : ''} percent={percent} onSelect={onSelect} />)}
    <SelectionMark selection={selection} percent={percent} />
    <div className="pointer-events-none absolute inset-y-0 w-px bg-lime-300" style={{ left: percent(offset) }} title={t('speech.offset')} />
    <div className="pointer-events-none absolute inset-y-0 w-px bg-white/80" style={{ left: percent(playhead) }} />
  </div>
}
function CueBar({ item, index, active, locked, label, percent, onSelect }: {
  item: MouthCue; index: number; active: boolean; locked: boolean; label: string
  percent: (time: number) => string; onSelect: (index: number) => void
}) {
  return <button type="button" data-testid={`speech-cue-${index}`} data-manual={item.manual ? 'true' : 'false'}
    disabled={locked} aria-pressed={active} aria-label={`${item.viseme} ${item.start.toFixed(2)}–${item.end.toFixed(2)}`}
    className={cueBarClass(Boolean(item.manual), active)}
    style={{ left: percent(item.start), width: percent(item.end - item.start) }}
    onClick={() => onSelect(index)}>{item.viseme}{label}</button>
}
function cueBarClass(manual: boolean, active: boolean) {
  const tone = manual ? 'border-amber-300 bg-amber-300/20 text-amber-100' : 'border-cyan-400/70 bg-cyan-400/10 text-cyan-100'
  return `absolute top-1 h-8 overflow-hidden rounded border px-1 text-[10px] ${tone}${active ? ' ring-1 ring-white' : ''}`
}
function SelectionMark({ selection, percent }: { selection?: CueInterval; percent: (time: number) => string }) {
  if (!selection || selection.end <= selection.start) return null
  return <div data-testid="speech-cue-selection" className="pointer-events-none absolute inset-y-0 border border-dashed border-white/70 bg-white/10"
    style={{ left: percent(selection.start), width: percent(selection.end - selection.start) }} />
}
function CueTools({ url, span, zoom, loop, selection, locked, audioRef, onZoom, onLoop, onPlayhead, onInterval, onSilence, onReanalyze }: {
  url: string; span: number; zoom: number; loop: boolean; selection?: CueInterval; locked: boolean
  audioRef: RefObject<HTMLAudioElement | null>; onZoom: (value: number) => void; onLoop: (value: (current: boolean) => boolean) => void
  onPlayhead: (value: number) => void; onInterval: (start: number, end: number) => void; onSilence: () => void
  onReanalyze?: (from: number, to: number) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <>
    <label className="flex items-center gap-2 text-xs">{t('speech.timeline.zoom')}
      <input className="w-32" type="range" min={1} max={8} step={.5} value={zoom} disabled={locked} aria-label={t('speech.timeline.zoom')}
        onChange={event => onZoom(Number(event.target.value))} />
    </label>
    <VoicePlayer url={url} audioRef={audioRef} onPlayhead={onPlayhead} />
    <div className="flex flex-wrap gap-3">
      <SpeechNumber label={t('speech.timeline.selectStart')} value={selection?.start ?? 0} min={0} max={span} step={.01}
        onChange={start => onInterval(start, selection?.end ?? start + .1)} />
      <SpeechNumber label={t('speech.timeline.selectEnd')} value={selection?.end ?? 0} min={0} max={span} step={.01}
        onChange={end => onInterval(selection?.start ?? 0, end)} />
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" className={speechInput} disabled={locked || !selection || !url} aria-pressed={loop}
        onClick={() => toggleLoop(audioRef.current, selection, onLoop)}>{t('speech.timeline.loop')}</button>
      <button type="button" className={speechInput} disabled={locked || !selection} onClick={onSilence}>{t('speech.timeline.addSilence')}</button>
      <button type="button" className={speechInput} disabled={locked || !selection || !onReanalyze}
        onClick={() => runReanalyze(selection, onReanalyze)}>{t('speech.timeline.reanalyze')}</button>
    </div>
    {selection ? <p className="text-xs">{t('speech.timeline.selection', { start: selection.start.toFixed(2), end: selection.end.toFixed(2) })}</p> : null}
  </>
}
function VoicePlayer({ url, audioRef, onPlayhead }: { url: string; audioRef: RefObject<HTMLAudioElement | null>; onPlayhead: (value: number) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!url) return <p className="text-xs text-text-muted">{t('speech.timeline.noAudio')}</p>
  return <audio ref={audioRef} controls src={url} preload="metadata" className="w-full min-w-0" aria-label={t('speech.timeline.playback')}
    onTimeUpdate={event => onPlayhead(event.currentTarget.currentTime)} />
}
function toggleLoop(audio: HTMLAudioElement | null, selection: CueInterval | undefined, onLoop: (value: (current: boolean) => boolean) => void) {
  onLoop(value => !value)
  if (!audio || !selection) return
  audio.currentTime = selection.start
  void audio.play?.().catch(() => {})
}
function runReanalyze(selection: CueInterval | undefined, onReanalyze?: (from: number, to: number) => void) {
  if (!selection || !onReanalyze) return
  onReanalyze(selection.start, selection.end)
}
function CueFields({ cue, speech, onChange }: { cue: MouthCue; speech: Scene3DSpeech; onChange: (speech: Scene3DSpeech) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const index = speech.cues.indexOf(cue)
  return <div className="flex flex-wrap gap-3">
    <label className="flex items-center gap-2 text-xs">{t('speech.timeline.viseme')}
      <select className={speechInput} aria-label={t('speech.timeline.viseme')} value={cue.viseme}
        onChange={event => onChange({ ...speech, cues: setCueViseme(speech.cues, index, event.target.value as Viseme) })}>
        {VISEMES.map(viseme => <option key={viseme} value={viseme}>{viseme}</option>)}
      </select>
    </label>
    <SpeechNumber label={t('speech.timeline.cueStart')} value={cue.start} min={0} max={cue.end} step={.01}
      onChange={start => onChange({ ...speech, cues: moveCueBound(speech.cues, index, 'start', start) })} />
    <SpeechNumber label={t('speech.timeline.cueEnd')} value={cue.end} min={cue.start} max={600} step={.01}
      onChange={end => onChange({ ...speech, cues: moveCueBound(speech.cues, index, 'end', end) })} />
    {cue.manual ? <p className="text-xs text-amber-200">{t('speech.timeline.manual')}</p> : null}
  </div>
}
