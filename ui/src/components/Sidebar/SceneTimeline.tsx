import { ClipboardPaste, Copy, Plus, Trash2 } from 'lucide-react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { getSceneKeyframes, getSceneLayerTiming, layerTimeToSceneTime } from '../../lib/sceneTimeline'
import type { SceneCurve, SceneKeyframe, SceneLayer } from '../../types'

type Props = {
  layers: SceneLayer[]
  duration: number
  currentTime: number
  selectedLayerId: string | null
  selectedKeyframeId: string | null
  onScrub: (time: number) => void
  onSelectLayer: (id: string) => void
  onSelectKeyframe: (layerId: string, keyframeId: string, time: number) => void
  onAddKeyframe: () => void
  onDeleteKeyframe: () => void
  onCopyKeyframes: () => void
  onPasteKeyframes: () => void
  onUpdateKeyframe: (keyframeId: string, patch: Partial<Omit<SceneKeyframe, 'id'>>) => void
  onUpdateTiming: (patch: Partial<Pick<SceneLayer['animation'], 'offset' | 'speed' | 'loop' | 'trimStart' | 'trimEnd'>>) => void
}

const CURVES: SceneCurve[] = ['linear', 'ease', 'dramatic', 'bounce']

function CurvePreview({ curve }: { curve: SceneCurve }) {
  const path = curve === 'ease'
    ? 'M2 30 C18 30 16 2 62 2'
    : curve === 'dramatic'
      ? 'M2 30 C38 30 48 20 62 2'
      : curve === 'bounce'
        ? 'M2 30 C18 28 27 5 36 9 C45 13 49 0 54 5 C58 8 60 3 62 2'
        : 'M2 30 L62 2'
  return <svg viewBox="0 0 64 32" className="h-8 w-16 rounded border border-border bg-bg-primary" aria-label={`${curve} easing preview`}><path d={path} fill="none" stroke="currentColor" strokeWidth="2" className="text-accent-blue" /><path d="M2 2 V30 H62" fill="none" stroke="currentColor" strokeWidth=".5" className="text-text-muted/40" /></svg>
}

const numberField = (label: string, value: number, change: (value: number) => void, step = .1, min?: number, max?: number, disabled = false) => (
  <label className="text-[9px] text-text-muted">{label}<input type="number" value={Number.isFinite(value) ? Number(value.toFixed(3)) : 0} step={step} min={min} max={max} disabled={disabled} onChange={event => { const next = Number(event.target.value); if (Number.isFinite(next)) change(next) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50" /></label>
)

export function SceneTimeline({ layers, duration, currentTime, selectedLayerId, selectedKeyframeId, onScrub, onSelectLayer, onSelectKeyframe, onAddKeyframe, onDeleteKeyframe, onCopyKeyframes, onPasteKeyframes, onUpdateKeyframe, onUpdateTiming }: Props) {
  const selectedLayer = layers.find(layer => layer.id === selectedLayerId) ?? null
  const selectedFrames = selectedLayer ? getSceneKeyframes(selectedLayer) : []
  const selectedTiming = selectedLayer ? getSceneLayerTiming(selectedLayer) : null
  const selectedIndex = selectedFrames.findIndex(frame => frame.id === selectedKeyframeId)
  const selectedFrame = selectedIndex >= 0 ? selectedFrames[selectedIndex] : null
  const isEndpoint = selectedIndex === 0 || selectedIndex === selectedFrames.length - 1
  const isLast = selectedIndex === selectedFrames.length - 1

  const seekTrack = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    onScrub(Math.max(0, Math.min(duration, (event.clientX - bounds.left) / Math.max(1, bounds.width) * duration)))
  }

  return <div className="mt-3 overflow-hidden rounded-lg border border-border bg-bg-secondary">
    <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-2 py-1.5">
      <span className="mr-auto text-[10px] font-medium uppercase tracking-wider text-text-secondary">Timeline · {currentTime.toFixed(2)}s / {duration.toFixed(2)}s</span>
      <button type="button" onClick={onAddKeyframe} disabled={!selectedLayer} className="flex items-center gap-1 rounded border border-border px-1.5 py-1 text-[9px] disabled:opacity-40"><Plus size={10} /> Keyframe</button>
      <button type="button" onClick={onDeleteKeyframe} disabled={!selectedFrame || isEndpoint} title={isEndpoint ? 'The first and last keyframes define the clip bounds.' : 'Delete selected keyframe'} className="rounded border border-border p-1 text-red-300 disabled:opacity-30"><Trash2 size={11} /></button>
      <button type="button" onClick={onCopyKeyframes} disabled={!selectedLayer} title="Copy all keyframes from this layer" className="rounded border border-border p-1 disabled:opacity-30"><Copy size={11} /></button>
      <button type="button" onClick={onPasteKeyframes} disabled={!selectedLayer} title="Paste keyframes onto this layer" className="rounded border border-border p-1 disabled:opacity-30"><ClipboardPaste size={11} /></button>
    </div>
    <div className="px-2 pb-2 pt-1.5">
      <input aria-label="Scene playhead" type="range" min={0} max={Math.max(.1, duration)} step={1 / 60} value={Math.min(duration, currentTime)} onChange={event => onScrub(Number(event.target.value))} className="mb-1.5 w-full accent-blue-500" />
      <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
        {[...layers].sort((a, b) => b.z - a.z).map(layer => {
          const frames = getSceneKeyframes(layer)
          return <div key={layer.id} className={`grid grid-cols-[88px_1fr] items-center gap-1 rounded px-1 py-0.5 ${selectedLayerId === layer.id ? 'bg-accent-blue/10' : ''}`}>
            <button type="button" onClick={() => onSelectLayer(layer.id)} className="truncate text-left text-[9px] text-text-secondary" title={layer.name}>{layer.type === 'camera' ? 'CAM · ' : ''}{layer.name}</button>
            <div onPointerDown={seekTrack} className="relative h-5 cursor-ew-resize rounded bg-bg-primary">
              <span className="pointer-events-none absolute inset-y-0 w-px bg-white/70" style={{ left: `${Math.max(0, Math.min(100, currentTime / Math.max(.1, duration) * 100))}%` }} />
              {frames.map((frame, index) => { const timing = getSceneLayerTiming(layer); const sceneFrameTime = layerTimeToSceneTime(layer, frame.time); const outsideTrim = frame.time < timing.trimStart || frame.time > timing.trimEnd; return <button key={frame.id} type="button" title={`Local ${frame.time.toFixed(2)}s · scene ${sceneFrameTime.toFixed(2)}s · ${frame.curve}`} onPointerDown={event => event.stopPropagation()} onClick={() => onSelectKeyframe(layer.id, frame.id, sceneFrameTime)} className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border ${outsideTrim ? 'opacity-30' : ''} ${selectedLayerId === layer.id && selectedKeyframeId === frame.id ? 'z-10 border-white bg-accent-blue' : index === 0 || index === frames.length - 1 ? 'border-cyan-200 bg-cyan-500/70' : 'border-purple-200 bg-purple-500/80'}`} style={{ left: `${Math.max(0, Math.min(100, sceneFrameTime / Math.max(.1, duration) * 100))}%` }} /> })}
            </div>
          </div>
        })}
      </div>
    </div>
    {selectedLayer && selectedTiming && <div className="border-t border-border bg-bg-tertiary px-2 py-2">
      <div className="mb-1.5 flex items-center justify-between"><span className="text-[9px] font-medium text-text-secondary">Layer timing</span><span className="text-[8px] text-text-muted">Effective range {selectedTiming.offset.toFixed(2)}–{(selectedTiming.offset + selectedTiming.span / selectedTiming.speed).toFixed(2)}s</span></div>
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-5">
        {numberField('Offset', selectedTiming.offset, value => onUpdateTiming({ offset: Math.max(0, value) }), .05, 0, duration)}
        {numberField('Trim in', selectedTiming.trimStart, value => onUpdateTiming({ trimStart: value }), .05, 0, selectedLayer.animation.duration - .01)}
        {numberField('Trim out', selectedTiming.trimEnd, value => onUpdateTiming({ trimEnd: value }), .05, .01, selectedLayer.animation.duration)}
        {numberField('Speed', selectedTiming.speed, value => onUpdateTiming({ speed: value }), .1, .1, 8)}
        <label className="flex items-end gap-1.5 pb-1 text-[9px] text-text-secondary"><input type="checkbox" checked={selectedTiming.loop} onChange={event => onUpdateTiming({ loop: event.target.checked })} /> Repeat motion</label>
      </div>
      <p className="mt-1 text-[8px] text-text-muted">Offset delays this layer. Trim chooses its local keyframe range; speed remaps time; repeat loops that range. Dimmed diamonds are outside the trim.</p>
    </div>}
    {selectedFrame && selectedLayer && <div className="border-t border-border bg-bg-tertiary px-2 py-2">
      <div className="mb-1.5 flex items-center justify-between"><span className="text-[9px] font-medium text-text-secondary">Selected keyframe · {selectedFrame.time.toFixed(2)}s</span><span className="text-[8px] text-text-muted">{isEndpoint ? 'Clip boundary' : `Frame ${selectedIndex + 1}/${selectedFrames.length}`}</span></div>
      <div className="grid grid-cols-3 gap-1.5 md:grid-cols-6">
        {numberField('Time', selectedFrame.time, value => onUpdateKeyframe(selectedFrame.id, { time: value }), .05, 0, duration, isEndpoint)}
        {numberField('X', selectedFrame.x, value => onUpdateKeyframe(selectedFrame.id, { x: value }), .5, -100, 200)}
        {numberField('Y', selectedFrame.y, value => onUpdateKeyframe(selectedFrame.id, { y: value }), .5, -100, 200)}
        {numberField('Scale', selectedFrame.scale, value => onUpdateKeyframe(selectedFrame.id, { scale: Math.max(.01, value) }), .05, .01, 10)}
        {numberField('Opacity', selectedFrame.opacity, value => onUpdateKeyframe(selectedFrame.id, { opacity: Math.max(0, Math.min(1, value)) }), .05, 0, 1)}
        {numberField('Rotation', selectedFrame.rotation, value => onUpdateKeyframe(selectedFrame.id, { rotation: value }), 1, -1080, 1080)}
      </div>
      <div className="mt-2 flex items-end gap-2">
        <label className="min-w-36 text-[9px] text-text-muted">Easing to next keyframe<select value={selectedFrame.curve} disabled={isLast} onChange={event => onUpdateKeyframe(selectedFrame.id, { curve: event.target.value as SceneCurve })} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50">{CURVES.map(curve => <option key={curve} value={curve}>{curve}</option>)}</select></label>
        {!isLast && <CurvePreview curve={selectedFrame.curve} />}
        <p className="text-[8px] leading-tight text-text-muted">Each diamond stores position, scale, opacity and rotation. Its curve controls only the following segment.</p>
      </div>
    </div>}
  </div>
}
