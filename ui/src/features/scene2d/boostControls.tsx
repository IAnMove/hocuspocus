import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useUiTranslation } from '../../i18n'
import { createSceneEvaluator } from '../../lib/scene2d/evaluate'
import { FINISH_PRESETS, type SceneFinish } from '../../lib/scene2d/finish'
import { parseSequence, rhythmFromAnalysis, type FrameSequence, type ScenePath } from '../../lib/scene2d/motion'
import { normalizeScene2D } from '../../lib/scene2d/normalize'
import { paintScene2D } from '../../lib/scene2d/paint'
import { sceneProgressFromSeconds } from '../../lib/sceneTimeline'
import type { AudioAnalysisResult, Scene, SceneLayer } from '../../types'

const button = 'rounded border border-border bg-bg-primary px-2 py-1 text-[10px] text-text-secondary disabled:opacity-40'

const PRESETS = [
  ['warmCinema', 'finishWarm'],
  ['oldDoc', 'finishDoc'],
  ['nightNeon', 'finishNeon'],
  ['paperComic', 'finishPaper'],
] as const

export function SceneFinishControls({ finish, playing, recording, publishing, onChange }: { finish?: SceneFinish; playing?: boolean; recording?: boolean; publishing?: boolean; onChange: (finish: SceneFinish | undefined) => void }) {
  const { t } = useUiTranslation('kineticText')
  const amount = finish?.vignette?.amount ?? 0
  const disabled = Boolean(playing || recording || publishing)
  return <fieldset disabled={disabled} className="mt-3 space-y-2 rounded-lg border border-border p-2">
    <legend className="px-1 text-[10px] text-text-muted">{t('finishTitle')}</legend>
    <div className="flex flex-wrap gap-1">
      {PRESETS.map(([id, key]) => <button key={id} type="button" className={button} onClick={() => onChange(FINISH_PRESETS[id])}>{t(key)}</button>)}
      <button type="button" className={button} onClick={() => onChange(undefined)}>{t('finishClear')}</button>
    </div>
    <label className="block text-[9px] text-text-muted">{t('finishTitle')}
      <input type="range" min={0} max={1} step={0.05} value={amount} onChange={event => onChange({ ...finish, vignette: { amount: Number(event.target.value), softness: finish?.vignette?.softness ?? 0.55 } })} className="w-full" />
    </label>
  </fieldset>
}

async function loadStill(source: string) {
  const image = new Image()
  image.crossOrigin = 'anonymous'
  image.src = source
  try { await image.decode() } catch { return undefined }
  return image.naturalWidth > 0 ? image : undefined
}

export function SceneFinalPreview({ scene, seconds }: { scene: Scene; seconds: number }) {
  const { t } = useUiTranslation('kineticText')
  const [open, setOpen] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!open || !canvas) return undefined
    let cancel = false
    const paint = async () => {
      const normalized = normalizeScene2D(scene)
      const media = new Map<string, HTMLImageElement>()
      await Promise.all(normalized.layers.map(async layer => {
        const source = layer.sequence?.kind === 'sheet' ? layer.sequence.source : layer.sequence?.kind === 'frames' ? layer.sequence.sources[0] : layer.source
        if (!source || layer.type === 'effect' || layer.type === 'camera') return
        const image = await loadStill(source)
        if (image) media.set(layer.id, image)
      }))
      if (cancel) return
      canvas.width = normalized.width
      canvas.height = normalized.height
      paintScene2D(canvas, normalized, sceneProgressFromSeconds(seconds, normalized.duration), createSceneEvaluator(normalized), layer => media.get(layer.id) ?? null)
    }
    void paint()
    return () => { cancel = true }
  }, [open, scene, seconds])
  return <div className="mt-2">
    <button type="button" className={button} onClick={() => setOpen(value => !value)}>{t('finalPreview')}</button>
    {open ? <canvas ref={canvasRef} className="mt-2 w-full rounded border border-border" /> : null}
  </div>
}

function movePoint(points: Array<{ x: number; y: number }>, index: number, x: number, y: number) {
  return points.map((point, pointIndex) => pointIndex === index ? { x, y } : point)
}

function PathPad({ points, orient, onPath }: { points: Array<{ x: number; y: number }>; orient: boolean; onPath: (path: ScenePath) => void }) {
  const [drag, setDrag] = useState<number | null>(null)
  const place = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (drag == null) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(100, (event.clientX - rect.left) / Math.max(1, rect.width) * 100))
    const y = Math.max(0, Math.min(100, (event.clientY - rect.top) / Math.max(1, rect.height) * 100))
    onPath({ points: movePoint(points, drag, x, y), orient })
  }
  return <div className="relative h-28 rounded border border-border bg-[#0b1020]" onPointerMove={place} onPointerUp={() => setDrag(null)}>
    {points.map((point, index) => <button key={`${point.x}-${point.y}-${index}`} type="button" className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-200" style={{ left: `${point.x}%`, top: `${point.y}%` }} onPointerDown={() => setDrag(index)} />)}
  </div>
}

function sequenceText(layer: SceneLayer) {
  if (layer.sequence?.kind === 'frames') return layer.sequence.sources.join('\n')
  if (layer.sequence?.kind === 'sheet') return layer.sequence.source
  return ''
}

function MotionFields({ layer, disabled, onPath, onSequence }: { layer: SceneLayer; disabled: boolean; onPath: (path: ScenePath | undefined) => void; onSequence: (sequence: FrameSequence | undefined) => void }) {
  const { t } = useUiTranslation('kineticText')
  const points = layer.animation.path?.points ?? []
  const orient = layer.animation.path?.orient === true
  return <fieldset disabled={disabled} className="mt-3 space-y-2 rounded-lg border border-border p-2">
    <legend className="px-1 text-[10px] text-text-muted">{t('pathTitle')}</legend>
    {points.length < 2 ? <button type="button" className={button} onClick={() => onPath({ points: [{ x: 20, y: 70 }, { x: 50, y: 40 }, { x: 80, y: 65 }], orient: true })}>{t('pathAdd')}</button> : <PathPad points={points} orient={orient} onPath={onPath} />}
    {points.length >= 2 ? <label className="flex items-center gap-2 text-[9px] text-text-muted"><input type="checkbox" checked={orient} onChange={event => onPath({ points, orient: event.target.checked })} />{t('pathOrient')}</label> : null}
    <label className="block text-[9px] text-text-muted">{t('sequenceSources')}
      <textarea rows={3} defaultValue={sequenceText(layer)} onBlur={event => onSequence(parseSequence({ kind: 'frames', sources: event.target.value.split(/\n+/), fps: 12, loop: 'loop' }))} className="mt-1 w-full rounded border border-border bg-bg-primary p-1 text-[9px]" />
    </label>
  </fieldset>
}

export function SceneMotionControls({ layer, playing, recording, publishing, onPath, onSequence }: {
  layer?: SceneLayer | null
  playing?: boolean
  recording?: boolean
  publishing?: boolean
  onPath: (path: ScenePath | undefined) => void
  onSequence: (sequence: FrameSequence | undefined) => void
}) {
  const disabled = Boolean(playing || recording || publishing || layer?.locked)
  if (!layer || layer.type === 'effect') return null
  return <MotionFields layer={layer} disabled={disabled} onPath={onPath} onSequence={onSequence} />
}

export function LiveRhythmStore({ analysis, track, duration, playing, recording, publishing, rhythmBusy, onChange }: {
  analysis: AudioAnalysisResult | null
  track?: { startTime: number } | null
  duration: number
  playing?: boolean
  recording?: boolean
  publishing?: boolean
  rhythmBusy?: boolean
  onChange: (rhythm: NonNullable<Scene['rhythm']>) => void
}) {
  const { t } = useUiTranslation('kineticText')
  if (!analysis) return null
  const disabled = Boolean(rhythmBusy || playing || recording || publishing)
  return <button type="button" disabled={disabled} className={`${button} w-full`} onClick={() => {
    const rhythm = rhythmFromAnalysis(analysis, track?.startTime ?? 0, duration)
    if (rhythm) onChange(rhythm)
  }}>{t('rhythmLive')}</button>
}
