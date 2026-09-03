import { ClipboardPaste, Copy, Flag, Plus, Trash2 } from 'lucide-react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useUiTranslation } from '../../i18n'
import { getSceneEvents, getSceneKeyframes, getSceneLayerTiming, layerTimeToSceneTime } from '../../lib/sceneTimeline'
import type { SceneAnimationEvent, SceneCurve, SceneFrameRate, SceneKeyframe, SceneLayer } from '../../types'

type Props = {
  layers: SceneLayer[]
  duration: number
  fps: SceneFrameRate
  currentTime: number
  selectedLayerId: string | null
  selectedKeyframeId: string | null
  selectedEventId: string | null
  onScrub: (time: number) => void
  onSelectLayer: (id: string) => void
  onSelectKeyframe: (layerId: string, keyframeId: string, time: number) => void
  onSelectEvent: (layerId: string, eventId: string, time: number) => void
  onAddKeyframe: () => void
  onAddEvent: () => void
  onDeleteKeyframe: () => void
  onDeleteEvent: () => void
  onCopyKeyframes: () => void
  onPasteKeyframes: () => void
  onUpdateKeyframe: (keyframeId: string, patch: Partial<Omit<SceneKeyframe, 'id'>>) => void
  onUpdateEvent: (eventId: string, patch: Partial<Omit<SceneAnimationEvent, 'id'>>) => void
  onUpdateTiming: (patch: Partial<Pick<SceneLayer['animation'], 'offset' | 'speed' | 'loop' | 'trimStart' | 'trimEnd'>>) => void
}

const CURVES: SceneCurve[] = ['linear', 'ease', 'dramatic', 'bounce', 'hold']

function CurvePreview({ curve, label }: { curve: SceneCurve; label: string }) {
  const path = curve === 'ease'
    ? 'M2 30 C18 30 16 2 62 2'
    : curve === 'dramatic'
      ? 'M2 30 C38 30 48 20 62 2'
      : curve === 'bounce'
        ? 'M2 30 C18 28 27 5 36 9 C45 13 49 0 54 5 C58 8 60 3 62 2'
        : 'M2 30 L62 2'
  return <svg viewBox="0 0 64 32" className="h-8 w-16 rounded border border-border bg-bg-primary" aria-label={label}><path d={path} fill="none" stroke="currentColor" strokeWidth="2" className="text-accent-blue" /><path d="M2 2 V30 H62" fill="none" stroke="currentColor" strokeWidth=".5" className="text-text-muted/40" /></svg>
}

const numberField = (label: string, value: number, change: (value: number) => void, step = .1, min?: number, max?: number, disabled = false) => (
  <label className="text-[9px] text-text-muted">{label}<input type="number" value={Number.isFinite(value) ? Number(value.toFixed(3)) : 0} step={step} min={min} max={max} disabled={disabled} onChange={event => { const next = Number(event.target.value); if (Number.isFinite(next)) change(next) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50" /></label>
)

export function SceneTimeline({ layers, duration, fps, currentTime, selectedLayerId, selectedKeyframeId, selectedEventId, onScrub, onSelectLayer, onSelectKeyframe, onSelectEvent, onAddKeyframe, onAddEvent, onDeleteKeyframe, onDeleteEvent, onCopyKeyframes, onPasteKeyframes, onUpdateKeyframe, onUpdateEvent, onUpdateTiming }: Props) {
  const { t } = useUiTranslation('scene3d')
  const curveLabel = (curve: SceneCurve) => t(`curves.${curve}`)
  const selectedLayer = layers.find(layer => layer.id === selectedLayerId) ?? null
  const selectedFrames = selectedLayer ? getSceneKeyframes(selectedLayer) : []
  const selectedEvents = selectedLayer ? getSceneEvents(selectedLayer) : []
  const selectedTiming = selectedLayer ? getSceneLayerTiming(selectedLayer) : null
  const selectedIndex = selectedFrames.findIndex(frame => frame.id === selectedKeyframeId)
  const selectedFrame = selectedIndex >= 0 ? selectedFrames[selectedIndex] : null
  const selectedEvent = selectedEvents.find(event => event.id === selectedEventId) ?? null
  const locked = Boolean(selectedLayer?.locked)
  const isEndpoint = selectedIndex === 0 || selectedIndex === selectedFrames.length - 1
  const isLast = selectedIndex === selectedFrames.length - 1
  const quantizeTime = (time: number) => Math.max(0, Math.min(duration, Math.round(time * fps) / fps))

  const seekTrack = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    onScrub(quantizeTime((event.clientX - bounds.left) / Math.max(1, bounds.width) * duration))
  }

  return <div className="mt-3 overflow-hidden rounded-lg border border-border bg-bg-secondary">
    <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-2 py-1.5">
      <span className="mr-auto text-[10px] font-medium uppercase tracking-wider text-text-secondary">{t('timeline.title', { current: currentTime.toFixed(2), duration: duration.toFixed(2), fps })}</span>
      <button type="button" onClick={onAddKeyframe} disabled={!selectedLayer || locked} className="flex items-center gap-1 rounded border border-border px-1.5 py-1 text-[9px] disabled:opacity-40"><Plus size={10} /> {t('timeline.keyframe')}</button>
      <button type="button" onClick={onAddEvent} disabled={!selectedLayer || locked} className="flex items-center gap-1 rounded border border-amber-400/40 px-1.5 py-1 text-[9px] text-amber-200 disabled:opacity-40"><Flag size={10} /> {t('timeline.event')}</button>
      <button type="button" onClick={selectedEvent ? onDeleteEvent : onDeleteKeyframe} disabled={locked || (!selectedEvent && (!selectedFrame || isEndpoint))} title={selectedEvent ? t('timeline.deleteEvent') : isEndpoint ? t('timeline.deleteEndpoint') : t('timeline.deleteKeyframe')} className="rounded border border-border p-1 text-red-300 disabled:opacity-30"><Trash2 size={11} /></button>
      <button type="button" onClick={onCopyKeyframes} disabled={!selectedLayer} title={t('timeline.copyKeyframes')} className="rounded border border-border p-1 disabled:opacity-30"><Copy size={11} /></button>
      <button type="button" onClick={onPasteKeyframes} disabled={!selectedLayer || locked} title={t('timeline.pasteKeyframes')} className="rounded border border-border p-1 disabled:opacity-30"><ClipboardPaste size={11} /></button>
    </div>
    <div className="px-2 pb-2 pt-1.5">
      <input aria-label={t('timeline.playheadAria')} type="range" min={0} max={Math.max(.1, duration)} step={1 / fps} value={Math.min(duration, currentTime)} onChange={event => onScrub(quantizeTime(Number(event.target.value)))} className="mb-1.5 w-full accent-blue-500" />
      <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
        {[...layers].sort((a, b) => b.z - a.z).map(layer => {
          const frames = getSceneKeyframes(layer)
          const events = getSceneEvents(layer)
          const timing = getSceneLayerTiming(layer)
          return <div key={layer.id} className={`grid grid-cols-[88px_1fr] items-center gap-1 rounded px-1 py-0.5 ${selectedLayerId === layer.id ? 'bg-accent-blue/10' : ''}`}>
            <button type="button" onClick={() => onSelectLayer(layer.id)} className="truncate text-left text-[9px] text-text-secondary" title={layer.name}>{layer.type === 'camera' ? t('timeline.cameraPrefix') : ''}{layer.name}{layer.locked ? t('timeline.lockedSuffix') : ''}</button>
            <div onPointerDown={seekTrack} className="relative h-6 cursor-ew-resize rounded bg-bg-primary">
              <span className="pointer-events-none absolute inset-y-0 w-px bg-white/70" style={{ left: `${Math.max(0, Math.min(100, currentTime / Math.max(.1, duration) * 100))}%` }} />
              {events.map(event => { const sceneEventTime = layerTimeToSceneTime(layer, event.time); const outsideTrim = event.time < timing.trimStart || event.time > timing.trimEnd; return <button key={`event-${event.id}`} type="button" title={event.payload ? t('timeline.eventTitlePayload', { name: event.name, local: event.time.toFixed(2), scene: sceneEventTime.toFixed(2), payload: event.payload }) : t('timeline.eventTitle', { name: event.name, local: event.time.toFixed(2), scene: sceneEventTime.toFixed(2) })} onPointerDown={pointer => pointer.stopPropagation()} onClick={() => onSelectEvent(layer.id, event.id, sceneEventTime)} className={`absolute top-0.5 h-2 w-2 -translate-x-1/2 rotate-45 border border-amber-100 bg-amber-400 ${outsideTrim ? 'opacity-30' : ''} ${selectedLayerId === layer.id && selectedEventId === event.id ? 'z-20 ring-1 ring-white' : 'z-10'}`} style={{ left: `${Math.max(0, Math.min(100, sceneEventTime / Math.max(.1, duration) * 100))}%` }} /> })}
              {frames.map((frame, index) => { const sceneFrameTime = layerTimeToSceneTime(layer, frame.time); const outsideTrim = frame.time < timing.trimStart || frame.time > timing.trimEnd; return <button key={`frame-${frame.id}`} type="button" title={t('timeline.localSceneCurve', { local: frame.time.toFixed(2), scene: sceneFrameTime.toFixed(2), curve: frame.curve })} onPointerDown={event => event.stopPropagation()} onClick={() => onSelectKeyframe(layer.id, frame.id, sceneFrameTime)} className={`absolute top-[68%] h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border ${outsideTrim ? 'opacity-30' : ''} ${selectedLayerId === layer.id && selectedKeyframeId === frame.id ? 'z-10 border-white bg-accent-blue' : index === 0 || index === frames.length - 1 ? 'border-cyan-200 bg-cyan-500/70' : 'border-purple-200 bg-purple-500/80'}`} style={{ left: `${Math.max(0, Math.min(100, sceneFrameTime / Math.max(.1, duration) * 100))}%` }} /> })}
            </div>
          </div>
        })}
      </div>
    </div>
    {selectedLayer && selectedTiming && <div className="border-t border-border bg-bg-tertiary px-2 py-2">
      <div className="mb-1.5 flex items-center justify-between"><span className="text-[9px] font-medium text-text-secondary">{t('timeline.layerTiming')}</span><span className="text-[8px] text-text-muted">{t('timeline.effectiveRange', { start: selectedTiming.offset.toFixed(2), end: (selectedTiming.offset + selectedTiming.span / selectedTiming.speed).toFixed(2) })}</span></div>
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-5">
        {numberField(t('timeline.offset'), selectedTiming.offset, value => onUpdateTiming({ offset: Math.max(0, value) }), .05, 0, duration, locked)}
        {numberField(t('timeline.trimIn'), selectedTiming.trimStart, value => onUpdateTiming({ trimStart: value }), .05, 0, selectedLayer.animation.duration - .01, locked)}
        {numberField(t('timeline.trimOut'), selectedTiming.trimEnd, value => onUpdateTiming({ trimEnd: value }), .05, .01, selectedLayer.animation.duration, locked)}
        {numberField(t('timeline.speed'), selectedTiming.speed, value => onUpdateTiming({ speed: value }), .1, .1, 8, locked)}
        <label className="flex items-end gap-1.5 pb-1 text-[9px] text-text-secondary"><input type="checkbox" checked={selectedTiming.loop} disabled={locked} onChange={event => onUpdateTiming({ loop: event.target.checked })} /> {t('timeline.repeatMotion')}</label>
      </div>
      <p className="mt-1 text-[8px] text-text-muted">{t('timeline.timingHelp')}</p>
    </div>}
    {selectedFrame && selectedLayer && <div className="border-t border-border bg-bg-tertiary px-2 py-2">
      <div className="mb-1.5 flex items-center justify-between"><span className="text-[9px] font-medium text-text-secondary">{t('timeline.selectedKeyframe', { time: selectedFrame.time.toFixed(2) })}</span><span className="text-[8px] text-text-muted">{isEndpoint ? t('timeline.clipBoundary') : t('timeline.frameIndex', { index: selectedIndex + 1, total: selectedFrames.length })}</span></div>
      <div className="grid grid-cols-3 gap-1.5 md:grid-cols-6">
        {numberField(t('timeline.time'), selectedFrame.time, value => onUpdateKeyframe(selectedFrame.id, { time: value }), .05, 0, duration, isEndpoint || locked)}
        {numberField(t('timeline.x'), selectedFrame.x, value => onUpdateKeyframe(selectedFrame.id, { x: value }), .5, -100, 200, locked)}
        {numberField(t('timeline.y'), selectedFrame.y, value => onUpdateKeyframe(selectedFrame.id, { y: value }), .5, -100, 200, locked)}
        {numberField(t('timeline.scale'), selectedFrame.scale, value => onUpdateKeyframe(selectedFrame.id, { scale: Math.max(.01, value) }), .05, .01, 10, locked)}
        {numberField(t('timeline.opacity'), selectedFrame.opacity, value => onUpdateKeyframe(selectedFrame.id, { opacity: Math.max(0, Math.min(1, value)) }), .05, 0, 1, locked)}
        {numberField(t('timeline.rotation'), selectedFrame.rotation, value => onUpdateKeyframe(selectedFrame.id, { rotation: value }), 1, -1080, 1080, locked)}
      </div>
      <div className="mt-2 flex items-end gap-2">
        <label className="min-w-36 text-[9px] text-text-muted">{t('timeline.easing')}<select value={selectedFrame.curve} disabled={isLast || locked} onChange={event => onUpdateKeyframe(selectedFrame.id, { curve: event.target.value as SceneCurve })} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50">{CURVES.map(curve => <option key={curve} value={curve}>{curveLabel(curve)}</option>)}</select></label>
        {!isLast && <CurvePreview curve={selectedFrame.curve} label={t('timeline.easingPreview', { curve: curveLabel(selectedFrame.curve) })} />}
        <p className="text-[8px] leading-tight text-text-muted">{t('timeline.keyframeHelp')}</p>
      </div>
    </div>}
    {selectedEvent && selectedLayer && <div className="border-t border-amber-400/30 bg-amber-400/[.04] px-2 py-2">
      <div className="mb-1.5 flex items-center justify-between"><span className="flex items-center gap-1 text-[9px] font-medium text-amber-200"><Flag size={10} /> {t('timeline.animationEvent', { time: selectedEvent.time.toFixed(2) })}</span><span className="text-[8px] text-text-muted">{t('timeline.metadataMarker')}</span></div>
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-[100px_1fr_2fr]">
        {numberField(t('timeline.time'), selectedEvent.time, value => onUpdateEvent(selectedEvent.id, { time: value }), 1 / fps, 0, selectedLayer.animation.duration, locked)}
        <label className="text-[9px] text-text-muted">{t('timeline.name')}<input value={selectedEvent.name} disabled={locked} maxLength={100} onChange={event => onUpdateEvent(selectedEvent.id, { name: event.target.value })} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50" /></label>
        <label className="text-[9px] text-text-muted">{t('timeline.payload')}<input value={selectedEvent.payload ?? ''} disabled={locked} maxLength={2000} placeholder={t('timeline.payloadPlaceholder')} onChange={event => onUpdateEvent(selectedEvent.id, { payload: event.target.value })} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px] disabled:opacity-50" /></label>
      </div>
      <p className="mt-1 text-[8px] text-text-muted">{t('timeline.eventHelp')}</p>
    </div>}
  </div>
}
