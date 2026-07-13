import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Box, Camera, ChevronDown, ChevronDown as Down, ChevronUp, Copy, CopyPlus, Download, Eye, EyeOff, FileJson, Film, Image as ImageIcon, Loader2, Lock, Play, Plus, Redo2, Trash2, Undo2, Unlock, Video } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { saveScene as saveSceneOutput, uploadImage } from '../../api/client'
import { PENDING_SCENE_KEY } from '../../lib/sceneOutput'
import { evaluateSceneLayer, getSceneKeyframes, getSceneLayerTiming, mapSceneAnimationPoints, normalizeSceneKeyframes, sceneLayerMotionProgress, sceneTimeToLayerTime, withNormalizedSceneTiming, withSceneKeyframes } from '../../lib/sceneTimeline'
import type { Scene, SceneCurve, SceneKeyframe, SceneLayer, SceneLayerType } from '../../types'
import { SceneTimeline } from './SceneTimeline'

type Point = { x: number; y: number; scale: number; opacity?: number; rotation?: number }
type AnimatorLayerType = SceneLayerType
type VisualLayerType = Exclude<SceneLayerType, 'camera'>
type ParallaxPreset = 'background' | 'midground' | 'foreground'
type AnimatorLayer = Omit<SceneLayer, 'type' | 'animation'> & {
  type: AnimatorLayerType
  /** Camera-pan response. Distant layers move less; foreground layers move more. */
  parallax?: number
  animation: Omit<SceneLayer['animation'], 'start' | 'end'> & { start: Point; end: Point }
}
type AnimatorScene = Omit<Scene, 'layers'> & { layers: AnimatorLayer[] }
type VisualAnimatorLayer = AnimatorLayer & { type: VisualLayerType }
type LayerState = { x: number; y: number; scale: number; opacity: number; rotation: number; z: number }
type PresetCategory = 'classic' | 'game' | 'cinematic'
type Preset = { id: string; label: string; category: PresetCategory; start: Point; end: Point; duration: number; spin: boolean; curve: SceneCurve; requiresTarget?: boolean; preview: string; poster: string }
type CameraPreset = { id: string; label: string; start: Point; end: Point; duration: number; curve: SceneCurve }
type Gesture = { id: string; mode: 'move' | 'resize' | 'orbit'; startX: number; startY: number; x: number; y: number; scale: number; rotationX: number; rotationY: number }

const makePoint = (x: number, y: number, scale: number): Point => ({ x, y, scale })
const CAMERA_PRESETS: CameraPreset[] = [
  { id: 'camera-locked', label: 'Locked shot', start: { x: 50, y: 50, scale: 1, rotation: 0 }, end: { x: 50, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'linear' },
  { id: 'camera-pan-right', label: 'Pan right', start: { x: 35, y: 50, scale: 1, rotation: 0 }, end: { x: 65, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-pan-left', label: 'Pan left', start: { x: 65, y: 50, scale: 1, rotation: 0 }, end: { x: 35, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-push-in', label: 'Slow push-in', start: { x: 50, y: 50, scale: 1, rotation: 0 }, end: { x: 50, y: 50, scale: 1.55, rotation: 0 }, duration: 6, curve: 'ease' },
  { id: 'camera-pull-out', label: 'Reveal pull-out', start: { x: 50, y: 50, scale: 1.6, rotation: 0 }, end: { x: 50, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-crane-up', label: 'Crane up', start: { x: 50, y: 68, scale: 1.15, rotation: 0 }, end: { x: 50, y: 34, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-dutch-drift', label: 'Dutch drift', start: { x: 44, y: 54, scale: 1.05, rotation: -6 }, end: { x: 57, y: 46, scale: 1.28, rotation: 7 }, duration: 6, curve: 'ease' },
]
const PRESETS: Preset[] = ([
  ['turntable', 'Product turntable', 50, 50, 50, 50, .8, .8, 5, true, 'linear'], ['meteor', 'Meteor fly-by', -10, 82, 112, 18, .22, .65, 2, true, 'dramatic'], ['space-cruise', 'Spacecraft cruise', 8, 54, 92, 43, .48, .68, 5, true, 'ease'], ['hover', 'Hovering reveal', 50, 54, 50, 46, .7, .76, 4, true, 'ease'], ['landing', 'Landing', 50, -12, 50, 60, .2, .82, 4, false, 'bounce'], ['liftoff', 'Lift-off', 50, 68, 54, -15, .82, .28, 3, false, 'dramatic'], ['zoom-in', 'Hero zoom in', 50, 50, 50, 50, .18, 1.35, 3, true, 'dramatic'], ['zoom-out', 'Retreat into distance', 50, 50, 50, 50, 1.25, .18, 3, true, 'ease'], ['drift-right', 'Slow drift right', 25, 50, 75, 50, .68, .68, 6, false, 'linear'], ['drift-left', 'Slow drift left', 75, 50, 25, 50, .68, .68, 6, false, 'linear'], ['diagonal-rise', 'Diagonal rise', 20, 82, 78, 22, .38, .82, 4, true, 'ease'], ['diagonal-drop', 'Diagonal drop', 78, 16, 24, 84, .82, .35, 3, true, 'dramatic'], ['pop', 'Pop into frame', 50, 50, 50, 50, .05, .85, 1, true, 'bounce'], ['glide', 'Low glide', -8, 72, 108, 70, .4, .52, 4, false, 'ease'], ['pass-camera', 'Pass the camera', 16, 50, 90, 50, .18, 1.5, 3, true, 'dramatic'], ['vibrate', 'Nave vibrando', 49, 51, 51, 49, .72, .75, 2, false, 'bounce'], ['orbit-sweep', 'Orbit sweep', 18, 70, 86, 30, .32, .9, 5, true, 'ease'], ['center-reveal', 'Center reveal', 50, 105, 50, 52, .35, .9, 3, true, 'ease'], ['exit-frame', 'Emergency exit', 50, 50, 120, -10, .8, .25, 2, true, 'dramatic'], ['floating-logo', 'Floating logo', 50, 45, 50, 55, .72, .72, 4, true, 'ease'],
].map(([id, label, sx, sy, ex, ey, ss, es, duration, spin, curve]) => ({ id: id as string, label: label as string, category: 'classic' as const, start: makePoint(sx as number, sy as number, ss as number), end: makePoint(ex as number, ey as number, es as number), duration: duration as number, spin: spin as boolean, curve: curve as SceneCurve })) as Array<Omit<Preset, 'preview' | 'poster'>>).concat([
  { id: 'orbit-layer', label: 'Orbit around another layer', category: 'cinematic', start: makePoint(50, 50, .45), end: makePoint(50, 50, .45), duration: 5, spin: true, curve: 'linear', requiresTarget: true },
  { id: 'game-spawn', label: 'Game spawn', category: 'game', start: { x: 50, y: 55, scale: .05, opacity: 0 }, end: { x: 50, y: 50, scale: .8, opacity: 1 }, duration: 1.2, spin: true, curve: 'bounce' },
  { id: 'loot-drop', label: 'Loot drop', category: 'game', start: makePoint(50, -18, .35), end: makePoint(50, 72, .72), duration: 1.4, spin: true, curve: 'bounce' },
  { id: 'item-pickup', label: 'Item pickup', category: 'game', start: { x: 50, y: 68, scale: .72, opacity: 1 }, end: { x: 50, y: 20, scale: .12, opacity: 0 }, duration: .9, spin: true, curve: 'dramatic' },
  { id: 'projectile-launch', label: 'Projectile launch', category: 'game', start: makePoint(-12, 58, .16), end: makePoint(115, 42, .5), duration: .75, spin: true, curve: 'dramatic' },
  { id: 'boss-entrance', label: 'Boss entrance', category: 'game', start: { x: 50, y: -20, scale: .18, opacity: 0 }, end: { x: 50, y: 58, scale: 1.25, opacity: 1 }, duration: 2.2, spin: false, curve: 'bounce' },
  { id: 'dodge-dash', label: 'Dodge dash', category: 'game', start: makePoint(30, 55, .82), end: makePoint(78, 50, .68), duration: .55, spin: false, curve: 'dramatic' },
  { id: 'hit-knockback', label: 'Hit knockback', category: 'game', start: makePoint(55, 48, .88), end: makePoint(32, 58, .62), duration: .65, spin: true, curve: 'bounce' },
  { id: 'power-up-rise', label: 'Power-up rise', category: 'game', start: { x: 50, y: 78, scale: .3, opacity: .25 }, end: { x: 50, y: 42, scale: 1.05, opacity: 1 }, duration: 1.8, spin: true, curve: 'bounce' },
  { id: 'cinematic-push', label: 'Cinematic push-in', category: 'cinematic', start: makePoint(38, 55, .28), end: makePoint(54, 48, 1.18), duration: 5.5, spin: false, curve: 'ease' },
  { id: 'hero-flyover', label: 'Hero flyover', category: 'cinematic', start: makePoint(-18, 22, .22), end: makePoint(118, 72, 1.15), duration: 4.2, spin: true, curve: 'ease' },
  { id: 'fade-reveal', label: 'Fade reveal', category: 'cinematic', start: { x: 50, y: 50, scale: .78, opacity: 0 }, end: { x: 50, y: 50, scale: .92, opacity: 1 }, duration: 2.5, spin: false, curve: 'ease' },
  { id: 'foreground-parallax', label: 'Foreground parallax', category: 'cinematic', start: makePoint(-28, 50, 1.55), end: makePoint(128, 50, 1.55), duration: 7, spin: false, curve: 'linear' },
  { id: 'crane-reveal', label: 'Crane reveal', category: 'cinematic', start: { x: 50, y: 112, scale: 1.3, opacity: .2 }, end: { x: 50, y: 45, scale: .72, opacity: 1 }, duration: 4.5, spin: false, curve: 'ease' },
  { id: 'portal-arrival', label: 'Portal arrival', category: 'cinematic', start: { x: 50, y: 50, scale: .02, opacity: 0 }, end: { x: 50, y: 50, scale: 1, opacity: 1 }, duration: 1.6, spin: true, curve: 'dramatic' },
]).map(preset => ({ ...preset, preview: `/preset-previews/${preset.id}.webm`, poster: `/preset-previews/${preset.id}.webp` }))

const blankScene = (): AnimatorScene => ({ version: 1, name: 'Untitled scene', width: 1280, height: 720, duration: 5, layers: [] })
const AUTOSAVE_KEY = 'maestro-scene-animator-autosave-v1'
const HISTORY_LIMIT = 80
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const isMissing = (source: string) => source.startsWith('blob:')
const isAnimatorLayerType = (value: unknown): value is AnimatorLayerType => value === 'model3d' || value === 'image' || value === 'video' || value === 'overlay' || value === 'camera'
const isVisualLayer = (layer: AnimatorLayer): layer is VisualAnimatorLayer => layer.type !== 'camera'
const iconFor = (type: AnimatorLayerType) => type === 'camera' ? <Camera size={13} /> : type === 'model3d' ? <Box size={13} /> : type === 'video' ? <Video size={13} /> : <ImageIcon size={13} />
const PARALLAX_PRESETS: Record<ParallaxPreset, number> = { background: .3, midground: .7, foreground: 1.2 }
const RESOLUTIONS = [
  ['HD landscape', 1280, 720], ['Full HD landscape', 1920, 1080], ['4K landscape', 3840, 2160],
  ['Square', 1080, 1080], ['HD portrait', 720, 1280], ['Full HD portrait', 1080, 1920], ['4K portrait', 2160, 3840],
] as const

const assignZ = (layers: AnimatorLayer[]) => layers.map((layer, index) => ({ ...layer, z: index * 10 }))
const normalizeZ = (layers: AnimatorLayer[]) => assignZ([...layers].sort((a, b) => a.z - b.z))
const ANIMATED_FIELDS = ['x', 'y', 'scale', 'opacity', 'rotation'] as const
type AnimatedField = typeof ANIMATED_FIELDS[number]

const endpointValue = (layer: AnimatorLayer, endpoint: 'start' | 'end', field: AnimatedField) => {
  const value = layer.animation[endpoint][field]
  if (typeof value === 'number') return value
  return field === 'opacity' ? layer.transform.opacity : field === 'rotation' ? layer.transform.rotation ?? 0 : 0
}

const reconcileLegacyKeyframeUpdate = (before: AnimatorLayer, after: AnimatorLayer): AnimatorLayer => {
  if (!before.animation.keyframes?.length || after.animation.keyframes !== before.animation.keyframes) return after
  let frames = getSceneKeyframes(before)
  for (const field of ANIMATED_FIELDS) {
    const beforeStart = endpointValue(before, 'start', field)
    const beforeEnd = endpointValue(before, 'end', field)
    const afterStart = endpointValue(after, 'start', field)
    const afterEnd = endpointValue(after, 'end', field)
    const startChanged = Math.abs(afterStart - beforeStart) > 1e-9
    const endChanged = Math.abs(afterEnd - beforeEnd) > 1e-9
    if (!startChanged && !endChanged) continue
    const transformChanged = field in before.transform && field in after.transform && before.transform[field as keyof typeof before.transform] !== after.transform[field as keyof typeof after.transform]
    if (startChanged && endChanged && transformChanged && (field === 'scale' || field === 'opacity') && Math.abs(afterStart - afterEnd) < 1e-9) {
      frames = frames.map(frame => ({ ...frame, [field]: afterStart }))
    } else if (startChanged && endChanged && Math.abs((afterStart - beforeStart) - (afterEnd - beforeEnd)) < 1e-9) {
      const delta = afterStart - beforeStart
      frames = frames.map(frame => ({ ...frame, [field]: frame[field] + delta }))
    } else {
      frames = frames.map((frame, index) => index === 0 && startChanged ? { ...frame, [field]: afterStart } : index === frames.length - 1 && endChanged ? { ...frame, [field]: afterEnd } : frame)
    }
  }
  if (before.animation.curve !== after.animation.curve) frames = frames.map(frame => ({ ...frame, curve: after.animation.curve }))
  return withSceneKeyframes(after, frames, after.animation.duration) as AnimatorLayer
}

function MotionPresetCard({ preset, selected, onSelect }: { preset: Preset; selected: boolean; onSelect: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [hovered, setHovered] = useState(false)
  const play = () => { setHovered(true); const video = videoRef.current; if (!video) return; video.currentTime = 0; void video.play().catch(() => {}) }
  const stop = () => { setHovered(false); const video = videoRef.current; if (!video) return; video.pause(); video.currentTime = 0 }
  return <button type="button" onClick={onSelect} onPointerEnter={play} onPointerLeave={stop} onFocus={play} onBlur={stop} className={`overflow-hidden rounded border text-left transition-colors ${selected ? 'border-accent-blue bg-accent-blue/10 ring-1 ring-accent-blue/40' : 'border-border bg-bg-primary hover:border-accent-blue/70'}`}>
    <div className="relative aspect-video overflow-hidden bg-[#07111f]"><img src={preset.poster} alt="" className="absolute inset-0 h-full w-full object-cover" /><video ref={videoRef} src={preset.preview} poster={preset.poster} muted loop playsInline preload="metadata" className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity ${hovered ? 'opacity-100' : 'opacity-0'}`} /></div>
    <div className="flex min-h-9 items-center justify-between gap-1 px-1.5 py-1"><span className="line-clamp-2 text-[9px] leading-tight text-text-secondary">{preset.label}</span><span className="flex shrink-0 flex-col items-end gap-0.5">{preset.category !== 'classic' && <span className={`rounded px-1 py-0.5 text-[7px] uppercase ${preset.category === 'game' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-purple-500/15 text-purple-300'}`}>{preset.category}</span>}{preset.requiresTarget && <span className="rounded bg-accent-blue/15 px-1 py-0.5 text-[8px] text-accent-blue">2 layers</span>}</span></div>
  </button>
}

export function SceneAnimatorPanel() {
  const outputs = useStore(s => s.outputs)
  const loadOutputs = useStore(s => s.loadOutputs)
  const [scene, setScene] = useState<AnimatorScene>(blankScene)
  const sceneRef = useRef(scene)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [picker, setPicker] = useState<'model' | 'media' | null>(null)
  const [playing, setPlaying] = useState(false)
  const [recording, setRecording] = useState(false)
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState(0)
  const [flash, setFlash] = useState<{ x: number; y: number } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [motionText, setMotionText] = useState('')
  const [reassignId, setReassignId] = useState<string | null>(null)
  const [jsonOpen, setJsonOpen] = useState(false)
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [selectedKeyframeId, setSelectedKeyframeId] = useState<string | null>(null)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [lastAutosaveAt, setLastAutosaveAt] = useState<number | null>(null)
  const [clipsByLayer, setClipsByLayer] = useState<Record<string, string[]>>({})
  const canvasRef = useRef<HTMLDivElement>(null)
  const animationRef = useRef<number | null>(null)
  const modelInputRef = useRef<HTMLInputElement>(null)
  const mediaInputRef = useRef<HTMLInputElement>(null)
  const overlayInputRef = useRef<HTMLInputElement>(null)
  const motionInputRef = useRef<HTMLInputElement>(null)
  const sceneInputRef = useRef<HTMLInputElement>(null)
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({})
  const flashTimerRef = useRef<number | null>(null)
  const gestureRef = useRef<Gesture | null>(null)
  const localFilesRef = useRef<Record<string, File>>({})
  const keyframeClipboardRef = useRef('')
  const pastScenesRef = useRef<AnimatorScene[]>([])
  const futureScenesRef = useRef<AnimatorScene[]>([])
  const lastHistoryAtRef = useRef(0)
  const selected = scene.layers.find(layer => layer.id === selectedId) ?? null
  const generatedModels = outputs.filter(output => output.type === 'model3d' && /\.glb$/i.test(output.name))
  const generatedMedia = outputs.filter(output => output.type === 'image' || output.type === 'video')

  useEffect(() => { void import('@google/model-viewer') }, [])
  // Rigged GLBs expose their baked clips through model-viewer's
  // availableAnimations; poll briefly after selection until the model loads.
  useEffect(() => {
    if (!selected || selected.type !== 'model3d') return
    let timer: number | null = null
    const read = () => {
      const element = canvasRef.current?.querySelector(`[data-layer-id="${selected.id}"]`) as (HTMLElement & { availableAnimations?: string[] }) | null
      const clips = element?.availableAnimations ?? []
      if (clips.length > 0) {
        setClipsByLayer(current => JSON.stringify(current[selected.id]) === JSON.stringify(clips) ? current : { ...current, [selected.id]: clips })
        if (timer !== null) window.clearInterval(timer)
      }
    }
    read()
    timer = window.setInterval(read, 800)
    return () => { if (timer !== null) window.clearInterval(timer) }
  }, [selected?.id, selected?.type, selected?.source])
  useEffect(() => { void loadOutputs() }, [loadOutputs])
  useEffect(() => () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); if (flashTimerRef.current) clearTimeout(flashTimerRef.current) }, [])

  useEffect(() => { sceneRef.current = scene }, [scene])
  const replaceScene = (next: AnimatorScene) => { sceneRef.current = next; setScene(next) }
  const updateScene = (updater: (current: AnimatorScene) => AnimatorScene) => {
    const current = sceneRef.current
    const next = updater(current)
    if (next === current) return
    const removesLockedLayer = current.layers.some(layer => layer.locked && !next.layers.some(candidate => candidate.id === layer.id))
    if (removesLockedLayer) { setMessage('Unlock the layer before deleting it.'); return }
    const now = Date.now()
    if (pastScenesRef.current.length === 0 || now - lastHistoryAtRef.current > 350) {
      pastScenesRef.current.push(current)
      if (pastScenesRef.current.length > HISTORY_LIMIT) pastScenesRef.current.shift()
    }
    lastHistoryAtRef.current = now
    futureScenesRef.current = []
    sceneRef.current = next
    setScene(next)
    setHistoryRevision(value => value + 1)
  }
  const undoScene = () => {
    const previous = pastScenesRef.current.pop()
    if (!previous) return
    futureScenesRef.current.push(sceneRef.current)
    replaceScene(previous); lastHistoryAtRef.current = 0; setHistoryRevision(value => value + 1)
    setSelectedId(id => id && previous.layers.some(layer => layer.id === id) ? id : null); setSelectedKeyframeId(null); setMessage('Undo')
  }
  const redoScene = () => {
    const next = futureScenesRef.current.pop()
    if (!next) return
    pastScenesRef.current.push(sceneRef.current)
    replaceScene(next); lastHistoryAtRef.current = 0; setHistoryRevision(value => value + 1)
    setSelectedId(id => id && next.layers.some(layer => layer.id === id) ? id : null); setSelectedKeyframeId(null); setMessage('Redo')
  }
  const updateLayer = (id: string, updater: (layer: AnimatorLayer) => AnimatorLayer) => updateScene(current => {
    const target = current.layers.find(layer => layer.id === id)
    if (!target) return current
    const updated = reconcileLegacyKeyframeUpdate(target, updater(target))
    if (target.locked) {
      const changedKeys = (Object.keys(updated) as Array<keyof AnimatorLayer>).filter(key => updated[key] !== target[key])
      if (changedKeys.some(key => key !== 'visible' && key !== 'locked')) return current
    }
    const activatesCamera = updated.type === 'camera' && updated.visible
    return { ...current, layers: current.layers.map(layer => layer.id === id ? updated : activatesCamera && layer.type === 'camera' ? { ...layer, visible: false } : layer) }
  })
  const updateLayerDuration = (id: string, value: number, minimum = .1) => updateScene(current => {
    if (current.layers.find(layer => layer.id === id)?.locked) return current
    const duration = Math.max(minimum, value)
    return {
      ...current,
      duration: Math.max(current.duration, duration),
      layers: current.layers.map(layer => {
        if (layer.id !== id) return layer
        if (layer.locked) return layer
        const previousDuration = Math.max(.1, layer.animation.duration)
        const keyframes = layer.animation.keyframes?.map(frame => ({ ...frame, time: frame.time * duration / previousDuration }))
        return { ...layer, animation: { ...layer.animation, duration, keyframes, trimStart: (layer.animation.trimStart ?? 0) * duration / previousDuration, trimEnd: (layer.animation.trimEnd ?? previousDuration) * duration / previousDuration } }
      }),
    }
  })
  const updateLayerTiming = (id: string, patch: Partial<Pick<AnimatorLayer['animation'], 'offset' | 'speed' | 'loop' | 'trimStart' | 'trimEnd'>>) => updateScene(current => {
    if (current.layers.find(layer => layer.id === id)?.locked) return current
    let sceneEnd = current.duration
    const layers = current.layers.map(layer => {
      if (layer.id !== id) return layer
      if (layer.locked) return layer
      const updated = withNormalizedSceneTiming({ ...layer, animation: { ...layer.animation, ...patch } }) as AnimatorLayer
      const timing = getSceneLayerTiming(updated)
      sceneEnd = Math.max(sceneEnd, timing.offset + timing.span / timing.speed)
      return updated
    })
    return { ...current, duration: sceneEnd, layers }
  })
  const updateLayerEndpoint = (id: string, endpoint: 'start' | 'end', patch: Partial<Point>) => updateLayer(id, layer => {
    if (!layer.animation.keyframes?.length) return { ...layer, animation: { ...layer.animation, [endpoint]: { ...layer.animation[endpoint], ...patch } } }
    const frames = getSceneKeyframes(layer)
    const index = endpoint === 'start' ? 0 : frames.length - 1
    const keyframe = frames[index]
    frames[index] = {
      ...keyframe,
      ...patch,
      opacity: patch.opacity ?? keyframe.opacity,
      rotation: patch.rotation ?? keyframe.rotation,
    }
    return withSceneKeyframes(layer, frames) as AnimatorLayer
  })
  const updateLayerCurve = (id: string, curve: SceneCurve) => updateLayer(id, layer => ({
    ...layer,
    animation: {
      ...layer.animation,
      curve,
      keyframes: layer.animation.keyframes?.map(frame => ({ ...frame, curve })),
    },
  }))
  const setLayerVisibility = (id: string, visible: boolean) => updateScene(current => {
    const target = current.layers.find(layer => layer.id === id)
    return {
      ...current,
      layers: current.layers.map(layer => ({
        ...layer,
        visible: target?.type === 'camera' && visible && layer.type === 'camera' ? layer.id === id : layer.id === id ? visible : layer.visible,
      })),
    }
  })
  const flashAt = (x: number, y: number, layerId = selectedId) => {
    const layer = scene.layers.find(item => item.id === layerId)
    const point = layer && isVisualLayer(layer)
      ? applyCameraTransform({ x, y, scale: 1, opacity: 1, rotation: 0, z: layer.z }, layer, progress)
      : { x, y }
    setFlash({ x: point.x, y: point.y })
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    flashTimerRef.current = window.setTimeout(() => setFlash(null), 550)
  }
  const addLayer = (type: VisualLayerType, source: string, name: string, thumbnail?: string, localFile?: File) => {
    const id = uid()
    if (localFile) localFilesRef.current[id] = localFile
    updateScene(current => {
      const foregroundCount = current.layers.filter(layer => layer.type === 'model3d' || layer.type === 'overlay').length
      const offset = type === 'model3d' || type === 'overlay' ? Math.min(24, foregroundCount * 6) : 0
      const scale = type === 'model3d' ? .7 : 1
      const layer: AnimatorLayer = { id, name, type, source, thumbnail, visible: true, z: 0, parallax: 1, transform: { x: 50 + offset, y: 50 + offset / 3, scale, opacity: 1, rotation: 0, rotationX: 75, rotationY: 0 }, animation: { start: makePoint(50 + offset, 50 + offset / 3, scale), end: makePoint(50 + offset, 50 + offset / 3, scale), duration: current.duration, curve: 'linear', spin: type === 'model3d', rotationSpeed: 35 } }
      const ordered = normalizeZ(current.layers)
      const layers = type === 'image' || type === 'video' ? [layer, ...ordered] : [...ordered, layer]
      return { ...current, layers: normalizeZ(layers) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null)
  }
  const addCamera = () => {
    const id = uid()
    updateScene(current => {
      const cameraCount = current.layers.filter(layer => layer.type === 'camera').length
      const camera: AnimatorLayer = {
        id,
        name: `Camera ${cameraCount + 1}`,
        type: 'camera',
        source: '',
        visible: true,
        z: 0,
        transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
        animation: {
          start: { x: 50, y: 50, scale: 1, rotation: 0 },
          end: { x: 50, y: 50, scale: 1, rotation: 0 },
          duration: current.duration,
          curve: 'ease',
        },
      }
      const layers = current.layers.map(layer => layer.type === 'camera' ? { ...layer, visible: false } : layer)
      return { ...current, layers: normalizeZ([...layers, camera]) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null); setProgress(0)
  }
  const duplicateLayer = (id: string) => {
    const original = sceneRef.current.layers.find(layer => layer.id === id)
    if (!original) return
    const duplicateId = uid()
    if (localFilesRef.current[id]) localFilesRef.current[duplicateId] = localFilesRef.current[id]
    updateScene(current => {
      const source = current.layers.find(layer => layer.id === id)
      if (!source) return current
      const clone = structuredClone(source) as AnimatorLayer
      clone.id = duplicateId
      clone.name = `${source.name} copy`
      clone.locked = false
      clone.visible = source.type === 'camera' ? false : source.visible
      clone.z = source.z + 5
      clone.animation.keyframes = clone.animation.keyframes?.map(frame => ({ ...frame, id: uid() }))
      if (isVisualLayer(clone)) {
        clone.transform = { ...clone.transform, x: clone.transform.x + 3, y: clone.transform.y + 3 }
        clone.animation = mapSceneAnimationPoints(clone, point => ({ ...point, x: point.x + 3, y: point.y + 3 }))
      }
      return { ...current, layers: normalizeZ([...current.layers, clone]) }
    })
    setSelectedId(duplicateId); setSelectedKeyframeId(null); setMessage(`Duplicated ${original.name}.`)
  }
  const addOrReassign = (type: VisualLayerType, file: File) => {
    const source = URL.createObjectURL(file)
    if (reassignId) {
      localFilesRef.current[reassignId] = file
      updateLayer(reassignId, layer => ({ ...layer, type, source, name: file.name, missingAsset: false }))
      setReassignId(null)
    } else addLayer(type, source, file.name, undefined, file)
  }
  const translateLayer = (id: string, x: number, y: number) => updateLayer(id, layer => {
    const dx = x - layer.transform.x; const dy = y - layer.transform.y
    return { ...layer, transform: { ...layer.transform, x, y }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, x: point.x + dx, y: point.y + dy })) }
  })
  const resizeLayer = (id: string, scale: number) => updateLayer(id, layer => ({ ...layer, transform: { ...layer.transform, scale }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale })) }))
  const startGesture = (event: ReactPointerEvent<HTMLElement>, layer: AnimatorLayer, mode: Gesture['mode']) => {
    if (layer.locked) { event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id); setMessage('Unlock the layer before moving it.'); return }
    event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id)
    gestureRef.current = { id: layer.id, mode, startX: event.clientX, startY: event.clientY, x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, rotationX: layer.transform.rotationX ?? 75, rotationY: layer.transform.rotationY ?? 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = gestureRef.current; const bounds = canvasRef.current?.getBoundingClientRect(); if (!gesture || !bounds) return
    if (gesture.mode === 'move') {
      const screenX = (event.clientX - gesture.startX) / bounds.width * 100
      const screenY = (event.clientY - gesture.startY) / bounds.height * 100
      const view = cameraState(progress); const radians = view.rotation * Math.PI / 180; const cos = Math.cos(radians); const sin = Math.sin(radians); const zoom = Math.max(.05, view.scale); const aspect = scene.width / Math.max(1, scene.height)
      const x = gesture.x + (screenX * cos - screenY / aspect * sin) / zoom
      const y = gesture.y + (screenX * aspect * sin + screenY * cos) / zoom
      translateLayer(gesture.id, x, y); flashAt(x, y, gesture.id)
    }
    else if (gesture.mode === 'resize') { const zoom = Math.max(.05, cameraState(progress).scale); resizeLayer(gesture.id, Math.max(.05, Math.min(3, gesture.scale + (event.clientX - gesture.startX + event.clientY - gesture.startY) / Math.min(bounds.width, bounds.height) / zoom))) }
    else updateLayer(gesture.id, layer => ({ ...layer, transform: { ...layer.transform, rotationY: gesture.rotationY + (event.clientX - gesture.startX) * .8, rotationX: Math.max(1, Math.min(179, gesture.rotationX + (event.clientY - gesture.startY) * .5)) } }))
  }
  const endGesture = () => { gestureRef.current = null }
  const baseLayerState = (layer: AnimatorLayer, time: number): LayerState => ({ ...evaluateSceneLayer(layer, sceneTimeToLayerTime(layer, time * scene.duration)), z: layer.z })
  const activeCameraLayer = () => [...scene.layers].filter(layer => layer.type === 'camera' && layer.visible).sort((a, b) => b.z - a.z)[0]
  const cameraState = (time: number): LayerState => {
    const camera = activeCameraLayer()
    return camera ? baseLayerState(camera, time) : { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0, z: 0 }
  }
  const applyCameraTransform = (state: LayerState, layer: AnimatorLayer, time: number): LayerState => {
    const camera = activeCameraLayer()
    if (!camera || layer.type === 'camera') return state
    const view = baseLayerState(camera, time)
    const parallax = layer.parallax ?? 1
    const dx = state.x - 50 - (view.x - 50) * parallax
    const dy = state.y - 50 - (view.y - 50) * parallax
    const radians = view.rotation * Math.PI / 180
    const cos = Math.cos(radians); const sin = Math.sin(radians)
    const zoom = Math.max(.05, view.scale)
    const aspect = scene.width / Math.max(1, scene.height)
    return {
      ...state,
      // Rotate in scene pixels rather than percent-space so portrait and
      // landscape shots keep a physically correct camera roll.
      x: 50 + (dx * cos + dy / aspect * sin) * zoom,
      y: 50 + (-dx * aspect * sin + dy * cos) * zoom,
      scale: state.scale * zoom,
      rotation: state.rotation - view.rotation,
    }
  }
  const layerState = (layer: AnimatorLayer, time = progress) => {
    const state = baseLayerState(layer, time)
    const orbit = layer.animation.orbit
    const target = orbit && scene.layers.find(item => item.id === orbit.targetLayerId)
    if (!orbit || !target || !isVisualLayer(target) || target.id === layer.id) return state
    const targetState = baseLayerState(target, time)
    const orbitProgress = sceneLayerMotionProgress(layer, time * scene.duration)
    const angle = orbit.phase * Math.PI / 180 + orbitProgress * orbit.turns * Math.PI * 2
    const depth = Math.sin(angle)
    const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
    const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
    return { ...state, x: centerX + Math.cos(angle) * orbit.radiusX, y: centerY + depth * orbit.radiusY, scale: state.scale * (1 + depth * .12), z: target.z + (depth >= 0 ? 1 : -1) }
  }
  const renderedLayerState = (layer: AnimatorLayer, time = progress) => applyCameraTransform(layerState(layer, time), layer, time)
  const moveLayerZ = (id: string, direction: 1 | -1) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const moving = layers.find(layer => layer.id === id)
    if (!moving || moving.locked) return current
    // Cameras have a priority order of their own and must not consume a
    // foreground/background click intended for a visual layer.
    const peers = layers.filter(layer => moving.type === 'camera' ? layer.type === 'camera' : isVisualLayer(layer))
    const index = peers.findIndex(layer => layer.id === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= peers.length) return current
    const other = peers[target]
    if (other.locked) return current
    const swapped = layers.map(layer => layer.id === moving.id ? { ...layer, z: other.z } : layer.id === other.id ? { ...layer, z: moving.z } : layer)
    return { ...current, layers: assignZ(swapped.sort((a, b) => a.z - b.z)) }
  })
  const sendToBack = (id: string) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const layer = layers.find(item => item.id === id)
    if (!layer || layer.locked) return current
    return { ...current, layers: assignZ([layer, ...layers.filter(item => item.id !== id)]) }
  })
  const resetSkeletalClips = () => canvasRef.current?.querySelectorAll('.scene-animator-model').forEach(element => { (element as HTMLElement & { currentTime: number }).currentTime = 0 })
  const animate = (done?: () => void) => { const started = performance.now(); resetSkeletalClips(); setPlaying(true); Object.values(videoRefs.current).forEach(video => { if (video) { video.currentTime = 0; void video.play().catch(() => {}) } }); const frame = (now: number) => { const next = Math.min(1, (now - started) / (scene.duration * 1000)); setProgress(next); if (next < 1) animationRef.current = requestAnimationFrame(frame); else { setPlaying(false); Object.values(videoRefs.current).forEach(video => video?.pause()); done?.() } }; animationRef.current = requestAnimationFrame(frame) }
  const play = () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); setProgress(0); animate() }
  const applyPreset = (presetId: string) => {
    if (!selected || selected.type === 'camera' || selected.locked) return
    const preset = PRESETS.find(item => item.id === presetId)
    if (!preset) return
    const target = scene.layers.find(layer => layer.id !== selected.id && layer.type === 'model3d') ?? scene.layers.find(layer => layer.id !== selected.id && isVisualLayer(layer))
    if (preset.requiresTarget && !target) { setMessage('Add a second layer before applying this relational movement.'); return }
    updateLayer(selected.id, layer => ({ ...layer, animation: { start: preset.start, end: preset.end, duration: preset.duration, curve: preset.curve, spin: preset.spin, rotationSpeed: layer.animation.rotationSpeed, clip: layer.animation.clip, orbit: preset.requiresTarget && target ? { targetLayerId: target.id, radiusX: 18, radiusY: 9, turns: 2, phase: 0, centerOffsetX: 0, centerOffsetY: 0 } : undefined } }))
    updateScene(current => ({ ...current, duration: Math.max(current.duration, preset.duration) }))
    setMessage(preset.requiresTarget ? `Orbit target: ${target?.name}` : null); setSelectedKeyframeId(null); setProgress(0)
  }
  const applyCameraPreset = (presetId: string) => {
    if (!selected || selected.type !== 'camera' || selected.locked) return
    const preset = CAMERA_PRESETS.find(item => item.id === presetId)
    if (!preset) return
    updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, x: preset.start.x, y: preset.start.y, scale: preset.start.scale, rotation: preset.start.rotation ?? 0 }, animation: { ...layer.animation, start: { ...preset.start }, end: { ...preset.end }, keyframes: undefined, duration: preset.duration, curve: preset.curve, offset: 0, speed: 1, loop: false, trimStart: 0, trimEnd: preset.duration, orbit: undefined } }))
    updateScene(current => ({ ...current, duration: Math.max(current.duration, preset.duration) }))
    setSelectedPresetId(preset.id); setSelectedKeyframeId(null); setProgress(0); setMessage(`${preset.label} applied to ${selected.name}.`)
  }
  const updateCameraTransform = (id: string, field: 'x' | 'y' | 'scale' | 'rotation', value: number) => updateLayer(id, layer => {
    if (layer.type !== 'camera') return layer
    const previous = field === 'rotation' ? layer.transform.rotation ?? 0 : layer.transform[field]
    if (field === 'scale') {
      const ratio = value / Math.max(.05, previous)
      return {
        ...layer,
        transform: { ...layer.transform, scale: value },
        animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale: Math.max(.05, point.scale * ratio) })),
      }
    }
    const delta = value - previous
    return {
      ...layer,
      transform: { ...layer.transform, [field]: value },
      animation: mapSceneAnimationPoints(layer, point => ({ ...point, [field]: point[field] + delta })),
    }
  })
  const applyParallaxPreset = (id: string, preset: ParallaxPreset) => updateLayer(id, layer => {
    if (!isVisualLayer(layer)) return layer
    const parallax = PARALLAX_PRESETS[preset]
    if (preset !== 'background' || layer.type === 'model3d') return { ...layer, parallax }
    const overscan = 1.2
    return {
      ...layer,
      parallax,
      fill: true,
      transform: { ...layer.transform, scale: Math.max(overscan, layer.transform.scale) },
      animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale: Math.max(overscan, point.scale) })),
    }
  })
  const motion = (layer: AnimatorLayer) => ({ start: layer.animation.start, end: layer.animation.end, keyframes: layer.animation.keyframes, duration: layer.animation.duration, curve: layer.animation.curve, offset: layer.animation.offset, speed: layer.animation.speed, loop: layer.animation.loop, trimStart: layer.animation.trimStart, trimEnd: layer.animation.trimEnd, spin: layer.animation.spin, rotationSpeed: layer.animation.rotationSpeed, orbit: layer.animation.orbit })
  const applyMotion = (raw: unknown) => {
    if (!selected || selected.locked || !raw || typeof raw !== 'object') throw new Error('Select an unlocked layer and provide a motion object.')
    const value = (raw as { motion?: unknown }).motion ?? raw
    if (!value || typeof value !== 'object') throw new Error('JSON must contain motion.')
    const item = value as Partial<AnimatorLayer['animation']>
    if (!item.start || !item.end || typeof item.duration !== 'number' || !Number.isFinite(item.duration)) throw new Error('Motion needs start, end and a finite duration.')
    const duration = Math.max(.1, item.duration)
    updateLayer(selected.id, layer => {
      const updated = withNormalizedSceneTiming({
        ...layer,
        animation: {
          ...layer.animation,
          ...item,
          start: { ...layer.animation.start, ...item.start },
          end: { ...layer.animation.end, ...item.end },
          keyframes: undefined,
          duration,
          curve: ['linear', 'ease', 'dramatic', 'bounce'].includes(item.curve ?? '') ? item.curve as SceneCurve : 'linear',
        },
      }) as AnimatorLayer
      const keyframes = normalizeSceneKeyframes(item.keyframes, updated)
      return keyframes ? withSceneKeyframes(updated, keyframes, duration) as AnimatorLayer : updated
    })
    const timingLayer = withNormalizedSceneTiming({ ...selected, animation: { ...selected.animation, ...item, duration } }) as AnimatorLayer
    const timing = getSceneLayerTiming(timingLayer)
    updateScene(current => ({ ...current, duration: Math.max(current.duration, timing.offset + timing.span / timing.speed) }))
    setSelectedKeyframeId(null); setProgress(0)
  }
  const addKeyframeAtPlayhead = () => {
    if (!selected || selected.locked) { setMessage('Unlock the layer before adding keyframes.'); return }
    const sceneTime = progress * scene.duration
    const time = sceneTimeToLayerTime(selected, sceneTime)
    const frames = getSceneKeyframes(selected)
    const existing = frames.find(frame => Math.abs(frame.time - time) < .025)
    if (existing) { setSelectedKeyframeId(existing.id); return }
    const point = evaluateSceneLayer(selected, time)
    const keyframe: SceneKeyframe = { id: uid(), time, ...point, curve: selected.animation.curve }
    updateLayer(selected.id, layer => withSceneKeyframes(layer, [...getSceneKeyframes(layer), keyframe], Math.max(layer.animation.duration, time)) as AnimatorLayer)
    updateScene(current => ({ ...current, duration: Math.max(current.duration, time) }))
    setSelectedKeyframeId(keyframe.id)
    setMessage(`Keyframe added at local ${time.toFixed(2)}s (scene ${sceneTime.toFixed(2)}s).`)
  }
  const updateTimelineKeyframe = (keyframeId: string, patch: Partial<Omit<SceneKeyframe, 'id'>>) => {
    if (!selected || selected.locked) return
    updateLayer(selected.id, layer => {
      const frames = getSceneKeyframes(layer)
      const index = frames.findIndex(frame => frame.id === keyframeId)
      if (index < 0) return layer
      const previousTime = index > 0 ? frames[index - 1].time + .01 : frames[index].time
      const nextTime = index < frames.length - 1 ? frames[index + 1].time - .01 : frames[index].time
      const time = index === 0 || index === frames.length - 1 ? frames[index].time : Math.max(previousTime, Math.min(nextTime, patch.time ?? frames[index].time))
      const updated = frames.map(frame => frame.id === keyframeId ? { ...frame, ...patch, time } : frame)
      return withSceneKeyframes(layer, updated) as AnimatorLayer
    })
  }
  const deleteTimelineKeyframe = () => {
    if (!selected || selected.locked || !selectedKeyframeId) return
    const frames = getSceneKeyframes(selected)
    const index = frames.findIndex(frame => frame.id === selectedKeyframeId)
    if (index <= 0 || index >= frames.length - 1) return
    updateLayer(selected.id, layer => withSceneKeyframes(layer, getSceneKeyframes(layer).filter(frame => frame.id !== selectedKeyframeId)) as AnimatorLayer)
    setSelectedKeyframeId(null)
    setMessage('Keyframe deleted.')
  }
  const copyTimelineKeyframes = () => {
    if (!selected) return
    const payload = JSON.stringify({ version: 1, keyframes: getSceneKeyframes(selected) }, null, 2)
    keyframeClipboardRef.current = payload
    void navigator.clipboard?.writeText(payload).catch(() => {})
    setMessage(`${getSceneKeyframes(selected).length} keyframes copied.`)
  }
  const pasteTimelineKeyframes = async () => {
    if (!selected || selected.locked) { setMessage('Unlock the target layer before pasting keyframes.'); return }
    let text = keyframeClipboardRef.current
    try { text = await navigator.clipboard?.readText() || text } catch { /* Internal clipboard remains available. */ }
    if (!text) { setMessage('Copy keyframes first.'); return }
    try {
      const parsed = JSON.parse(text) as { keyframes?: unknown }
      const frames = normalizeSceneKeyframes(Array.isArray(parsed) ? parsed : parsed.keyframes, selected)?.map(frame => ({ ...frame, id: uid() }))
      if (!frames) throw new Error('Clipboard does not contain at least two valid keyframes.')
      const pastedDuration = Math.max(.1, frames[frames.length - 1].time)
      updateLayer(selected.id, layer => withSceneKeyframes({ ...layer, animation: { ...layer.animation, trimStart: 0, trimEnd: pastedDuration } }, frames, pastedDuration) as AnimatorLayer)
      const timing = getSceneLayerTiming({ ...selected, animation: { ...selected.animation, duration: pastedDuration, trimStart: 0, trimEnd: pastedDuration } })
      const effectiveEnd = timing.offset + timing.span / timing.speed
      updateScene(current => ({ ...current, duration: Math.max(current.duration, effectiveEnd) }))
      setSelectedKeyframeId(frames[0].id); setProgress(timing.offset / Math.max(.1, Math.max(scene.duration, effectiveEnd))); setMessage(`${frames.length} keyframes pasted.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid keyframe clipboard.') }
  }
  const download = (name: string, data: unknown) => { const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url) }
  const importScene = (text: string) => {
    try {
      const incoming = JSON.parse(text) as AnimatorScene
      if (incoming.version !== 1 || !Array.isArray(incoming.layers)) throw new Error('This is not a Maestro Scene Animator scene.')
      const activeCameraId = [...incoming.layers]
        .filter(layer => layer.type === 'camera' && layer.visible)
        .sort((a, b) => (b.z ?? 0) - (a.z ?? 0))[0]?.id
      const layers = normalizeZ(incoming.layers.map(rawLayer => {
        if (!isAnimatorLayerType((rawLayer as { type?: unknown }).type)) throw new Error(`Unsupported scene layer type: ${String((rawLayer as { type?: unknown }).type ?? 'missing')}`)
        const isCamera = rawLayer.type === 'camera'
        const transform = {
          ...rawLayer.transform,
          x: rawLayer.transform?.x ?? 50,
          y: rawLayer.transform?.y ?? 50,
          scale: rawLayer.transform?.scale ?? 1,
          opacity: rawLayer.transform?.opacity ?? 1,
          rotation: rawLayer.transform?.rotation ?? 0,
          rotationX: rawLayer.transform?.rotationX ?? 75,
          rotationY: rawLayer.transform?.rotationY ?? 0,
        }
        const start = { x: rawLayer.animation?.start?.x ?? transform.x, y: rawLayer.animation?.start?.y ?? transform.y, scale: rawLayer.animation?.start?.scale ?? transform.scale, opacity: rawLayer.animation?.start?.opacity, rotation: rawLayer.animation?.start?.rotation ?? (isCamera ? transform.rotation : undefined) }
        const end = { x: rawLayer.animation?.end?.x ?? transform.x, y: rawLayer.animation?.end?.y ?? transform.y, scale: rawLayer.animation?.end?.scale ?? transform.scale, opacity: rawLayer.animation?.end?.opacity, rotation: rawLayer.animation?.end?.rotation ?? (isCamera ? transform.rotation : undefined) }
        const visible = isCamera ? rawLayer.id === activeCameraId : rawLayer.visible !== false
        const layer = {
          ...rawLayer,
          source: isCamera ? '' : String(rawLayer.source ?? ''),
          visible,
          locked: rawLayer.locked === true,
          parallax: isCamera ? undefined : typeof rawLayer.parallax === 'number' && Number.isFinite(rawLayer.parallax) ? Math.max(0, Math.min(2, rawLayer.parallax)) : 1,
          transform,
          animation: { ...rawLayer.animation, start, end, keyframes: undefined, duration: Math.max(.1, rawLayer.animation?.duration ?? incoming.duration ?? 5), curve: rawLayer.animation?.curve ?? 'linear' },
          missingAsset: isCamera ? false : Boolean(rawLayer.missingAsset || isMissing(String(rawLayer.source ?? ''))),
        } as AnimatorLayer
        const timedLayer = withNormalizedSceneTiming(layer) as AnimatorLayer
        const keyframes = normalizeSceneKeyframes(rawLayer.animation?.keyframes, timedLayer)
        return keyframes ? withSceneKeyframes(timedLayer, keyframes, timedLayer.animation.duration) as AnimatorLayer : timedLayer
      }))
      const duration = Math.max(.1, Number.isFinite(incoming.duration) ? incoming.duration : 5, ...layers.map(layer => { const timing = getSceneLayerTiming(layer); return timing.offset + timing.span / timing.speed }))
      localFilesRef.current = {}; replaceScene({ ...blankScene(), ...incoming, duration, layers }); setSelectedId(layers[0]?.id ?? null); setSelectedKeyframeId(null); setMessage('Scene imported. Reassign layers marked missing asset.'); setJsonOpen(false)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid scene JSON.') }
  }
  useEffect(() => {
    const pending = sessionStorage.getItem(PENDING_SCENE_KEY)
    if (pending) {
      sessionStorage.removeItem(PENDING_SCENE_KEY)
      importScene(pending)
      return
    }
    const autosave = localStorage.getItem(AUTOSAVE_KEY)
    if (!autosave) return
    try {
      const parsed = JSON.parse(autosave) as Partial<AnimatorScene>
      if (parsed.version === 1 && Array.isArray(parsed.layers) && parsed.layers.length > 0) {
        importScene(autosave)
        setMessage('Autosave restored. Local assets may need reassignment.')
      }
    } catch { localStorage.removeItem(AUTOSAVE_KEY) }
    // Scene restoration is intentionally a one-time mount operation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(scene)); setLastAutosaveAt(Date.now()) } catch { setMessage('Autosave could not be written in this browser.') }
    }, 700)
    return () => window.clearTimeout(timer)
  }, [scene])
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return
      const target = event.target as HTMLElement | null
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return
      event.preventDefault()
      if (event.shiftKey) redoScene(); else undoScene()
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
    // Rebind when history changes so keyboard state and buttons stay aligned.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyRevision])
  const paintScene = (canvas: HTMLCanvasElement, time: number) => {
    const context = canvas.getContext('2d')
    if (!context) return false
    context.fillStyle = '#0b1020'; context.fillRect(0, 0, canvas.width, canvas.height)
    scene.layers.filter(layer => layer.visible && isVisualLayer(layer)).map(layer => ({ layer, state: renderedLayerState(layer, time) })).sort((a, b) => a.state.z - b.state.z).forEach(({ layer, state }) => {
      context.save(); context.globalAlpha = state.opacity
      const width = canvas.width * (layer.type === 'model3d' ? .52 : 1) * state.scale
      const height = canvas.height * (layer.type === 'model3d' ? .75 : 1) * state.scale
      context.translate(canvas.width * state.x / 100, canvas.height * state.y / 100); context.rotate(state.rotation * Math.PI / 180)
      if (layer.type === 'model3d') {
        const viewer = canvasRef.current?.querySelector(`[data-layer-id="${layer.id}"]`)?.shadowRoot?.querySelector('canvas') as HTMLCanvasElement | null
        if (viewer) context.drawImage(viewer, -width / 2, -height / 2, width, height)
      } else {
        const media = layer.type === 'video' ? videoRefs.current[layer.id] : canvasRef.current?.querySelector(`[data-layer-id="${layer.id}"]`) as HTMLImageElement | null
        if (media && (media instanceof HTMLVideoElement ? media.readyState >= 2 : media.complete)) {
          const sourceWidth = media instanceof HTMLVideoElement ? media.videoWidth : media.naturalWidth
          const sourceHeight = media instanceof HTMLVideoElement ? media.videoHeight : media.naturalHeight
          const sourceRatio = sourceWidth / Math.max(1, sourceHeight); const targetRatio = width / Math.max(1, height)
          let drawWidth = width; let drawHeight = height
          if (!layer.fill) { if (sourceRatio > targetRatio) drawHeight = width / sourceRatio; else drawWidth = height * sourceRatio }
          else if (sourceRatio > targetRatio) drawWidth = height * sourceRatio; else drawHeight = width / sourceRatio
          context.beginPath(); context.rect(-width / 2, -height / 2, width, height); context.clip()
          context.drawImage(media, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight)
        }
      }
      context.restore()
    })
    return true
  }
  const record = () => {
    if (!scene.layers.some(layer => layer.visible && isVisualLayer(layer))) { setMessage('Add a visible visual layer before recording.'); return }
    if (!('MediaRecorder' in window)) { setMessage('This browser cannot record the scene.'); return }
    const canvas = document.createElement('canvas'); canvas.width = scene.width; canvas.height = scene.height; if (!canvas.getContext('2d')) return
    const stream = canvas.captureStream(30); const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm'; const recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8_000_000 }); const chunks: Blob[] = []
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }; recorder.onstop = () => { const url = URL.createObjectURL(new Blob(chunks, { type: mime })); const link = document.createElement('a'); link.href = url; link.download = `maestro-scene-${Date.now()}.webm`; link.click(); URL.revokeObjectURL(url); setRecording(false) }
    resetSkeletalClips(); setRecording(true); setProgress(0); recorder.start(250); const started = performance.now(); Object.values(videoRefs.current).forEach(video => { if (video) { video.currentTime = 0; void video.play().catch(() => {}) } }); const frame = (now: number) => { const next = Math.min(1, (now - started) / (scene.duration * 1000)); setProgress(next); paintScene(canvas, next); if (next < 1) requestAnimationFrame(frame); else { Object.values(videoRefs.current).forEach(video => video?.pause()); recorder.stop() } }; requestAnimationFrame(frame)
  }
  const persistScene = async () => {
    if (!scene.layers.length) { setMessage('Add at least one layer before saving.'); return }
    setSaving(true); setMessage(null)
    try {
      const preview = document.createElement('canvas')
      const previewScale = Math.min(1, 1280 / Math.max(scene.width, scene.height))
      preview.width = Math.max(1, Math.round(scene.width * previewScale)); preview.height = Math.max(1, Math.round(scene.height * previewScale))
      paintScene(preview, progress)
      const layers = await Promise.all(scene.layers.map(async layer => {
        if (layer.type === 'camera') return layer
        if (!layer.source.startsWith('blob:')) return layer
        const file = localFilesRef.current[layer.id]
        if (!file) return { ...layer, missingAsset: true }
        const uploaded = await uploadImage(file)
        return { ...layer, source: uploaded.url, missingAsset: false }
      }))
      const persisted = { ...scene, layers }
      const saved = await saveSceneOutput(persisted, preview.toDataURL('image/png'))
      replaceScene(persisted); localFilesRef.current = {}; await loadOutputs()
      setMessage(`Scene saved to Maestro as ${saved.name}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save scene.')
    } finally {
      setSaving(false)
    }
  }
  const numberInput = (label: string, value: number, change: (value: number) => void, min = -100, max = 200, step = 1) => <label className="text-[10px] text-text-muted">{label}<input type="number" min={min} max={max} step={step} value={value} onChange={event => { const next = Number(event.target.value); if (Number.isFinite(next)) change(next) }} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label>
  const orbitPivot = (() => {
    if (!selected || !isVisualLayer(selected)) return null
    const orbit = selected?.animation.orbit
    const target = orbit && scene.layers.find(layer => layer.id === orbit.targetLayerId)
    if (!orbit || !target || !isVisualLayer(target)) return null
    const targetState = baseLayerState(target, progress)
    return applyCameraTransform({ ...targetState, x: targetState.x + (orbit.centerOffsetX ?? 0), y: targetState.y + (orbit.centerOffsetY ?? 0) }, selected, progress)
  })()
  const renderLayer = (layer: AnimatorLayer) => {
    if (layer.type === 'camera') return null
    const state = renderedLayerState(layer); const common = { left: `${state.x}%`, top: `${state.y}%`, width: `${(layer.type === 'model3d' ? 52 : 100) * state.scale}%`, height: `${(layer.type === 'model3d' ? 75 : 100) * state.scale}%`, opacity: state.opacity, zIndex: state.z, transform: `translate(-50%, -50%) rotate(${state.rotation}deg)` }; const selection = selectedId === layer.id
    if (!layer.visible) return null
    if (layer.missingAsset) return <button key={layer.id} onClick={() => setSelectedId(layer.id)} className={`absolute flex items-center justify-center border border-dashed border-red-400/70 bg-red-500/10 text-[10px] text-red-300 ${selection ? 'ring-2 ring-accent-blue ring-inset' : ''}`} style={common}>Missing asset</button>
    const edgeMove = (event: ReactPointerEvent<HTMLElement>) => { if (layer.type !== 'model3d') return startGesture(event, layer, 'move'); const box = event.currentTarget.getBoundingClientRect(); const edge = (event.clientX - box.left) / box.width < .18 || (event.clientX - box.left) / box.width > .82 || (event.clientY - box.top) / box.height < .18 || (event.clientY - box.top) / box.height > .82; startGesture(event, layer, edge ? 'move' : 'orbit') }
    const media = layer.type === 'model3d'
      ? <model-viewer data-layer-id={layer.id} src={layer.source} camera-orbit={`${layer.transform.rotationY ?? 0}deg ${layer.transform.rotationX ?? 75}deg auto`} interaction-prompt="none" auto-rotate={layer.animation.spin && (playing || recording) ? true : undefined} rotation-per-second={`${layer.animation.rotationSpeed ?? 35}deg`} autoplay={layer.animation.clip ? true : undefined} animation-name={layer.animation.clip || undefined} shadow-intensity="1" exposure="1" loading="eager" className="scene-animator-model pointer-events-none h-full w-full" />
      : layer.type === 'video'
        ? <video data-layer-id={layer.id} ref={element => { videoRefs.current[layer.id] = element }} src={layer.source} muted loop className={`h-full w-full ${layer.fill ? 'object-cover' : 'object-contain'}`} />
        : <img data-layer-id={layer.id} src={layer.source} alt={layer.name} draggable={false} className={`h-full w-full select-none ${layer.fill ? 'object-cover' : 'object-contain'}`} />
    return <div key={layer.id} style={common} onPointerDown={edgeMove} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} className={`absolute touch-none cursor-grab active:cursor-grabbing ${selection ? 'ring-2 ring-accent-blue ring-inset' : ''}`}>{media}{selection && <button aria-label="Resize layer" onPointerDown={event => startGesture(event, layer, 'resize')} onPointerMove={moveGesture} onPointerUp={endGesture} className="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-white bg-accent-blue shadow" />}</div>
  }
  const activeCamera = activeCameraLayer()
  const canUndo = historyRevision >= 0 && pastScenesRef.current.length > 0
  const canRedo = historyRevision >= 0 && futureScenesRef.current.length > 0

  return <div className="flex min-h-[620px] flex-col overflow-hidden rounded-xl border border-border bg-bg-tertiary xl:flex-row">
    <section className="flex min-w-0 flex-1 flex-col p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-1.5 text-xs font-medium"><Film size={15} className="text-accent-blue" /><input value={scene.name} onChange={event => updateScene(current => ({ ...current, name: event.target.value }))} aria-label="Scene name" className="w-44 rounded border border-transparent bg-transparent px-1 py-0.5 text-xs font-medium hover:border-border focus:border-accent-blue focus:outline-none" /><span className="text-[10px] font-normal text-text-muted">{scene.width}×{scene.height}</span></div><div className="flex gap-2"><button onClick={play} disabled={!scene.layers.length || playing || recording} className="rounded border border-border bg-bg-primary px-2.5 py-1.5 text-[10px] flex items-center gap-1 disabled:opacity-50"><Play size={12} /> Preview</button><button onClick={record} disabled={recording} className="rounded bg-cta px-2.5 py-1.5 text-[10px] text-white flex items-center gap-1 disabled:opacity-50">{recording ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}{recording ? 'Recording…' : 'Record WebM'}</button></div></div>
      <div className="mb-2 flex items-center justify-end gap-1.5"><button type="button" onClick={undoScene} disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)" className="rounded border border-border bg-bg-primary p-1.5 disabled:opacity-30"><Undo2 size={12} /></button><button type="button" onClick={redoScene} disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)" className="rounded border border-border bg-bg-primary p-1.5 disabled:opacity-30"><Redo2 size={12} /></button><span className="ml-1 text-[8px] text-text-muted">{lastAutosaveAt ? `Autosaved ${new Date(lastAutosaveAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Autosave waiting…'}</span></div>
      <div className="mb-3 flex flex-wrap gap-1">{RESOLUTIONS.map(([label, width, height]) => <button key={label} onClick={() => updateScene(current => ({ ...current, width, height }))} className={`rounded border px-1.5 py-1 text-[9px] ${scene.width === width && scene.height === height ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-muted'}`}>{label}</button>)}</div>
      {selected && isVisualLayer(selected) && selected.type !== 'model3d' && <button onClick={() => updateLayer(selected.id, layer => ({ ...layer, fill: !layer.fill, transform: { ...layer.transform, x: 50, y: 50, scale: 1 }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, x: 50, y: 50, scale: 1 })) }))} className={`mb-3 rounded border px-2 py-1 text-[10px] ${selected.fill ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-secondary'}`}>{selected.fill ? 'Fill screen enabled' : 'Fill screen'}</button>}
      {selected && isVisualLayer(selected) && selected.type !== 'model3d' && <button onClick={() => { sendToBack(selected.id); applyParallaxPreset(selected.id, 'background') }} className="mb-3 ml-1 rounded border border-border bg-bg-primary px-2 py-1 text-[10px] text-text-secondary">Use as background</button>}
      <div ref={canvasRef} className="relative isolate mx-auto w-full min-h-[240px] overflow-hidden rounded-lg border border-border bg-[#0b1020]" style={{ aspectRatio: `${scene.width} / ${scene.height}`, maxHeight: '68vh' }}>{[...scene.layers].sort((a, b) => a.z - b.z).map(renderLayer)}{activeCamera && <div className="pointer-events-none absolute left-2 top-2 z-[997] flex items-center gap-1 rounded bg-black/55 px-1.5 py-1 text-[8px] text-cyan-200"><Camera size={10} /> {activeCamera.name}</div>}{orbitPivot && <div className="pointer-events-none absolute z-[998] h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-300 bg-cyan-400/20 shadow-[0_0_8px_rgba(103,232,249,.9)]" style={{ left: `${orbitPivot.x}%`, top: `${orbitPivot.y}%` }}><span className="absolute left-1/2 top-[-5px] h-6 w-px -translate-x-1/2 bg-cyan-300/80" /><span className="absolute left-[-5px] top-1/2 h-px w-6 -translate-y-1/2 bg-cyan-300/80" /></div>}{flash && <div className="pointer-events-none absolute z-[999]" style={{ left: `${flash.x}%`, top: `${flash.y}%` }}><span className="absolute -left-6 -top-6 h-12 w-12 rounded-full border-2 border-white/90 animate-ping" /><span className="absolute -left-1.5 -top-1.5 h-3 w-3 rounded-full bg-white shadow-[0_0_20px_8px_rgba(96,165,250,.9)]" /></div>}<div className="absolute inset-x-0 bottom-0 z-[1000] h-1 bg-black/40"><div className="h-full bg-accent-blue" style={{ width: `${progress * 100}%` }} /></div></div>
      <p className="mt-2 text-[9px] text-text-muted">Center-drag a 3D layer to orbit it 360°; drag its outer edge to move it. Camera layers animate pan, zoom and rotation without rendering an asset. Parallax controls how strongly each visual layer follows camera pan. WebM uses the same camera transform and Z order as this preview.</p>
      <SceneTimeline
        layers={scene.layers}
        duration={scene.duration}
        currentTime={progress * scene.duration}
        selectedLayerId={selectedId}
        selectedKeyframeId={selectedKeyframeId}
        onScrub={time => { if (animationRef.current) cancelAnimationFrame(animationRef.current); setPlaying(false); Object.values(videoRefs.current).forEach(video => video?.pause()); setProgress(Math.max(0, Math.min(1, time / Math.max(.1, scene.duration)))) }}
        onSelectLayer={id => { setSelectedId(id); setSelectedKeyframeId(null) }}
        onSelectKeyframe={(layerId, keyframeId, time) => { setSelectedId(layerId); setSelectedKeyframeId(keyframeId); setProgress(Math.max(0, Math.min(1, time / Math.max(.1, scene.duration)))) }}
        onAddKeyframe={addKeyframeAtPlayhead}
        onDeleteKeyframe={deleteTimelineKeyframe}
        onCopyKeyframes={copyTimelineKeyframes}
        onPasteKeyframes={() => void pasteTimelineKeyframes()}
        onUpdateKeyframe={updateTimelineKeyframe}
        onUpdateTiming={patch => selected && updateLayerTiming(selected.id, patch)}
      />
    </section>
    <aside className="w-full shrink-0 border-t border-border bg-bg-secondary p-3 overflow-y-auto space-y-3 xl:w-[300px] xl:border-l xl:border-t-0">
      <div className="relative"><button onClick={() => setAddOpen(value => !value)} className="w-full rounded bg-accent-blue px-2.5 py-2 text-xs text-white flex items-center justify-center gap-1"><Plus size={13} /> Add layer</button>{addOpen && <div className="absolute z-[1100] mt-1 w-full rounded border border-border bg-bg-primary p-1 shadow-xl space-y-1"><button onClick={addCamera} className="w-full rounded px-2 py-1.5 text-left text-[11px] text-cyan-200 hover:bg-bg-hover">Add camera</button><button onClick={() => { setPicker('model'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated 3D model</button><button onClick={() => { setAddOpen(false); modelInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import GLB</button><button onClick={() => { setPicker('media'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated image/video</button><button onClick={() => { setAddOpen(false); mediaInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import image/video</button><button onClick={() => { setAddOpen(false); overlayInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import transparent PNG/WebP</button></div>}</div>
      {picker && <div className="rounded border border-border bg-bg-primary p-2"><div className="mb-1 flex justify-between text-[10px] text-text-muted"><span>{picker === 'model' ? 'Generated 3D models' : 'Generated images & videos'}</span><button onClick={() => setPicker(null)}><Down size={13} /></button></div><div className="grid grid-cols-3 gap-1.5 max-h-40 overflow-y-auto">{(picker === 'model' ? generatedModels : generatedMedia).map(asset => <button key={asset.name} onClick={() => addLayer(asset.type === 'model3d' ? 'model3d' : asset.type === 'video' ? 'video' : 'image', asset.url, asset.name, asset.thumbnail_url ?? undefined)} className="overflow-hidden rounded border border-border text-left hover:border-accent-blue"><div className="aspect-square bg-bg-active">{asset.thumbnail_url || asset.type === 'image' ? <img src={asset.thumbnail_url ?? asset.url} alt="" className="h-full w-full object-cover" /> : <div className="h-full flex items-center justify-center"><Video size={16} /></div>}</div><span className="block truncate px-1 py-1 text-[9px]">{asset.name}</span></button>)}</div></div>}
      <input ref={modelInputRef} type="file" accept=".glb,model/gltf-binary" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign('model3d', file) }} /><input ref={mediaInputRef} type="file" accept="image/*,video/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign(file.type.startsWith('video/') ? 'video' : 'image', file) }} /><input ref={overlayInputRef} type="file" accept="image/png,image/webp" multiple className="hidden" onChange={event => [...(event.target.files ?? [])].forEach(file => addOrReassign('overlay', file))} />
      <div><div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-text-muted">Layers</div><div className="space-y-1">{[...scene.layers].sort((a, b) => b.z - a.z).map(layer => <div key={layer.id} onClick={() => setSelectedId(layer.id)} className={`flex cursor-pointer items-center gap-1.5 rounded border p-1.5 text-[10px] ${selectedId === layer.id ? 'border-accent-blue bg-accent-blue/10' : 'border-border bg-bg-primary'}`}><div className="h-7 w-7 shrink-0 overflow-hidden rounded bg-bg-active flex items-center justify-center">{layer.thumbnail ? <img src={layer.thumbnail} alt="" className="h-full w-full object-cover" /> : iconFor(layer.type)}</div><div className="min-w-0 flex-1"><div className="truncate">{layer.name}</div><div className="text-[9px] text-text-muted">{layer.type} · z: {layer.z}{layer.missingAsset ? ' · missing asset' : ''}</div></div><button onClick={event => { event.stopPropagation(); updateLayer(layer.id, item => ({ ...item, visible: !item.visible })) }} title="Visibility">{layer.visible ? <Eye size={12} /> : <EyeOff size={12} />}</button><div className="flex flex-col"><button title="Bring forward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, 1) }}><ChevronUp size={12} /></button><button title="Send backward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, -1) }}><ChevronDown size={12} /></button></div><button onClick={event => { event.stopPropagation(); updateScene(current => ({ ...current, layers: normalizeZ(current.layers.filter(item => item.id !== layer.id)) })); if (selectedId === layer.id) setSelectedId(null) }} className="text-red-400"><Trash2 size={12} /></button></div>)}</div></div>
      {selected && <div className="grid grid-cols-2 gap-1.5"><button type="button" onClick={() => updateLayer(selected.id, layer => ({ ...layer, locked: !layer.locked }))} className={`flex items-center justify-center gap-1 rounded border py-1.5 text-[9px] ${selected.locked ? 'border-amber-400/60 bg-amber-400/10 text-amber-200' : 'border-border bg-bg-primary text-text-secondary'}`}>{selected.locked ? <Lock size={11} /> : <Unlock size={11} />}{selected.locked ? 'Locked' : 'Lock layer'}</button><button type="button" onClick={() => duplicateLayer(selected.id)} className="flex items-center justify-center gap-1 rounded border border-border bg-bg-primary py-1.5 text-[9px] text-text-secondary"><CopyPlus size={11} /> Duplicate</button>{selected.locked && <p className="col-span-2 text-[8px] text-amber-200/80">Unlock this layer to change transforms, timing, presets or keyframes.</p>}</div>}
      {selected?.type === 'camera' && <div className="space-y-2 border-t border-border pt-3">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Camera inspector</span><span className={`rounded px-1.5 py-0.5 text-[8px] ${activeCamera?.id === selected.id ? 'bg-cyan-400/15 text-cyan-200' : 'bg-bg-active text-text-muted'}`}>{activeCamera?.id === selected.id ? 'Active camera' : 'Inactive'}</span></div>
        <label className="text-[10px] text-text-muted">Name<input value={selected.name} onChange={event => updateLayer(selected.id, layer => ({ ...layer, name: event.target.value }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label>
        <label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={selected.visible} onChange={event => setLayerVisibility(selected.id, event.target.checked)} /> Use this camera</label>
        <div className="grid grid-cols-2 gap-1.5">
          {numberInput('Pan X', selected.transform.x, value => updateCameraTransform(selected.id, 'x', value), -100, 200, .5)}
          {numberInput('Pan Y', selected.transform.y, value => updateCameraTransform(selected.id, 'y', value), -100, 200, .5)}
          {numberInput('Zoom', selected.transform.scale, value => updateCameraTransform(selected.id, 'scale', Math.max(.05, value)), .05, 5, .05)}
          {numberInput('Rotation', selected.transform.rotation ?? 0, value => updateCameraTransform(selected.id, 'rotation', value), -360, 360, .5)}
          {numberInput('Z / priority', selected.z, value => updateLayer(selected.id, layer => ({ ...layer, z: value })))}
        </div>
        <div className="space-y-1.5"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Camera shots</span><span className="text-[9px] text-text-muted">Click to apply</span></div><div className="grid grid-cols-2 gap-1">{CAMERA_PRESETS.map(preset => <button key={preset.id} onClick={() => applyCameraPreset(preset.id)} className={`rounded border px-2 py-1.5 text-left text-[9px] ${selectedPresetId === preset.id ? 'border-cyan-300 bg-cyan-400/10 text-cyan-200' : 'border-border bg-bg-primary text-text-secondary hover:border-cyan-400/60'}`}>{preset.label}</button>)}</div></div>
        <div className="grid grid-cols-2 gap-1.5">{(['start', 'end'] as const).map(key => <div key={key} className="space-y-1"><div className="text-[10px] capitalize text-text-muted">{key} camera</div>{numberInput('X', selected.animation[key].x, value => updateLayerEndpoint(selected.id, key, { x: value }))}{numberInput('Y', selected.animation[key].y, value => updateLayerEndpoint(selected.id, key, { y: value }))}{numberInput('Zoom', selected.animation[key].scale, value => updateLayerEndpoint(selected.id, key, { scale: Math.max(.05, value) }), .05, 5, .05)}{numberInput('Rotation', selected.animation[key].rotation ?? selected.transform.rotation ?? 0, value => updateLayerEndpoint(selected.id, key, { rotation: value }), -360, 360, .5)}</div>)}</div>
        <div className="grid grid-cols-2 gap-1.5">{numberInput('Duration (s)', selected.animation.duration, value => updateLayerDuration(selected.id, value), .1, 30, .05)}<label className="text-[10px] text-text-muted">All segment curves<select value={selected.animation.curve} onChange={event => updateLayerCurve(selected.id, event.target.value as SceneCurve)} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="linear">Linear</option><option value="ease">Ease</option><option value="dramatic">Dramatic</option><option value="bounce">Bounce</option></select></label></div>
        <p className="text-[9px] text-text-muted">The highest visible camera is active. Its pan, zoom and rotation are applied identically to preview and WebM capture.</p>
      </div>}
      {selected?.type !== 'camera' && <>
      {selected ? <div className="border-t border-border pt-3 space-y-2"><div className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Layer inspector</div>{selected.missingAsset && <button onClick={() => { setReassignId(selected.id); (selected.type === 'model3d' ? modelInputRef : selected.type === 'overlay' ? overlayInputRef : mediaInputRef).current?.click() }} className="w-full rounded border border-red-400/50 py-1.5 text-[10px] text-red-300">Reassign missing asset</button>}<label className="text-[10px] text-text-muted">Name<input value={selected.name} onChange={event => updateLayer(selected.id, layer => ({ ...layer, name: event.target.value }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label><div className="grid grid-cols-3 gap-1.5">{numberInput('X', selected.transform.x, value => { const delta = value - selected.transform.x; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, x: value }, animation: { ...layer.animation, start: { ...layer.animation.start, x: layer.animation.start.x + delta }, end: { ...layer.animation.end, x: layer.animation.end.x + delta } } })); flashAt(value, selected.transform.y) }, -100, 200)}{numberInput('Y', selected.transform.y, value => { const delta = value - selected.transform.y; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, y: value }, animation: { ...layer.animation, start: { ...layer.animation.start, y: layer.animation.start.y + delta }, end: { ...layer.animation.end, y: layer.animation.end.y + delta } } })); flashAt(selected.transform.x, value) }, -100, 200)}{numberInput('Z', selected.z, value => updateLayer(selected.id, layer => ({ ...layer, z: value })))}{numberInput('Scale', selected.transform.scale, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, scale: value }, animation: { ...layer.animation, start: { ...layer.animation.start, scale: value }, end: { ...layer.animation.end, scale: value } } })), .05, 3, .05)}{numberInput('Opacity', selected.transform.opacity, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, opacity: value }, animation: { ...layer.animation, start: { ...layer.animation.start, opacity: value }, end: { ...layer.animation.end, opacity: value } } })), 0, 1, .05)}{numberInput('Rotation', selected.transform.rotation ?? 0, value => updateLayer(selected.id, layer => { const previous = layer.transform.rotation ?? 0; const delta = value - previous; return { ...layer, transform: { ...layer.transform, rotation: value }, animation: { ...layer.animation, start: { ...layer.animation.start, rotation: layer.animation.start.rotation === undefined ? undefined : layer.animation.start.rotation + delta }, end: { ...layer.animation.end, rotation: layer.animation.end.rotation === undefined ? undefined : layer.animation.end.rotation + delta } } } }), -360, 360)} </div><label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={selected.visible} onChange={event => updateLayer(selected.id, layer => ({ ...layer, visible: event.target.checked }))} /> Visible</label><div className="space-y-1.5"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Motion presets</span><span className="text-[9px] text-text-muted">Hover to preview · click to apply</span></div><div className="grid max-h-[370px] grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">{PRESETS.map(preset => <MotionPresetCard key={preset.id} preset={preset} selected={selectedPresetId === preset.id} onSelect={() => { setSelectedPresetId(preset.id); applyPreset(preset.id) }} />)}</div></div><div className="grid grid-cols-2 gap-1.5">{(['start', 'end'] as const).map(key => <div key={key} className="space-y-1"><div className="text-[10px] text-text-muted capitalize">{key} motion</div>{numberInput('X', selected.animation[key].x, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], x: value } } })))}{numberInput('Y', selected.animation[key].y, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], y: value } } })))}{numberInput('Scale', selected.animation[key].scale, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], scale: value } } })), .05, 3, .05)}</div>)}</div><div className="grid grid-cols-2 gap-1.5">{numberInput('Duration (s)', selected.animation.duration, value => updateLayerDuration(selected.id, value, 1), 1, 30)}<label className="text-[10px] text-text-muted">Curve<select value={selected.animation.curve} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, curve: event.target.value as SceneCurve } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="linear">Linear</option><option value="ease">Ease</option><option value="dramatic">Dramatic</option><option value="bounce">Bounce</option></select></label></div>{selected.type === 'model3d' && <div className="grid grid-cols-2 gap-1.5"><label className="flex items-end gap-1.5 pb-1 text-[10px]"><input type="checkbox" checked={Boolean(selected.animation.spin)} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, spin: event.target.checked } }))} /> Auto spin</label>{numberInput('Spin °/sec', selected.animation.rotationSpeed ?? 35, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, rotationSpeed: value } })), 0, 720)}</div>}{selected.type === 'model3d' && (clipsByLayer[selected.id]?.length ?? 0) > 0 && <label className="text-[10px] text-text-muted">Skeletal animation<select value={selected.animation.clip ?? ''} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clip: event.target.value || undefined } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="">Off</option>{(clipsByLayer[selected.id] ?? []).map(clip => <option key={clip} value={clip}>{clip}</option>)}</select><span className="mt-0.5 block text-[9px] text-text-muted/80">Baked in the Animate tab; plays live and is captured in the WebM.</span></label>}</div> : <p className="text-[10px] text-text-muted">Select a layer to edit it.</p>}
      {selected && isVisualLayer(selected) && <div className="space-y-2 rounded border border-border bg-bg-primary p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Camera parallax</span><span className="text-[9px] text-text-muted">Z order unchanged</span></div>
        <div className="grid grid-cols-3 gap-1">{(['background', 'midground', 'foreground'] as const).map(preset => <button key={preset} onClick={() => applyParallaxPreset(selected.id, preset)} className={`rounded border px-1 py-1.5 text-[8px] capitalize ${Math.abs((selected.parallax ?? 1) - PARALLAX_PRESETS[preset]) < .001 ? 'border-cyan-300 bg-cyan-400/10 text-cyan-200' : 'border-border text-text-muted hover:border-cyan-400/60'}`}>{preset}</button>)}</div>
        {numberInput('Parallax strength', selected.parallax ?? 1, value => updateLayer(selected.id, layer => ({ ...layer, parallax: Math.max(0, Math.min(2, value)) })), 0, 2, .05)}
        <p className="text-[9px] text-text-muted">0 ignores camera pan, 1 follows it normally, and values above 1 feel closer. Zoom and camera roll still affect the full shot. Background adds 20% overscan to image/video layers; extreme moves may need more scale.</p>
      </div>}
      </>}
      {selected && isVisualLayer(selected) && selected.animation.orbit && <div className="rounded border border-accent-blue/40 bg-accent-blue/10 p-2 space-y-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-accent-blue">Relational orbit</span><button onClick={() => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: undefined } }))} className="text-[9px] text-text-muted hover:text-red-400">Remove</button></div>
        <label className="text-[10px] text-text-muted">Orbit around<select value={selected.animation.orbit.targetLayerId} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, targetLayerId: event.target.value } : undefined } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs">{scene.layers.filter(layer => layer.id !== selected.id && isVisualLayer(layer)).map(layer => <option key={layer.id} value={layer.id}>{layer.name} · {layer.type}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-1.5">{numberInput('Horizontal radius', selected.animation.orbit.radiusX, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, radiusX: Math.max(0, value) } : undefined } })), 0, 100, 1)}{numberInput('Vertical radius', selected.animation.orbit.radiusY, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, radiusY: Math.max(0, value) } : undefined } })), 0, 100, 1)}{numberInput('Center offset X', selected.animation.orbit.centerOffsetX ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, centerOffsetX: value } : undefined } })), -100, 100, .5)}{numberInput('Center offset Y', selected.animation.orbit.centerOffsetY ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, centerOffsetY: value } : undefined } })), -100, 100, .5)}{numberInput('Turns', selected.animation.orbit.turns, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, turns: value } : undefined } })), -20, 20, .25)}{numberInput('Start phase °', selected.animation.orbit.phase, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, phase: value } : undefined } })), -360, 360, 5)}</div>
        <p className="text-[9px] text-text-muted">The cyan cross marks the exact orbit center. Use center offsets when an asymmetric GLB's visual center differs from its layer box. Negative turns reverse direction.</p>
      </div>}
      <div className="border-t border-border pt-3 space-y-2">
        <div className="grid grid-cols-2 gap-1.5">
          <button disabled={!selected} onClick={() => selected && navigator.clipboard.writeText(JSON.stringify({ version: 1, motion: motion(selected) }, null, 2)).then(() => setMessage('Movement JSON copied.'))} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1 disabled:opacity-40"><Copy size={11} /> Copy movement</button>
          <button onClick={() => void persistScene()} disabled={saving || !scene.layers.length} className="rounded bg-accent-blue py-1.5 text-[10px] text-white flex justify-center gap-1 disabled:opacity-40">{saving ? <Loader2 size={11} className="animate-spin" /> : <Film size={11} />} {saving ? 'Saving…' : 'Save scene'}</button>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <button onClick={() => download('maestro-scene.json', scene)} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1"><Download size={11} /> Export scene JSON</button>
          <button onClick={() => setJsonOpen(value => !value)} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1"><FileJson size={11} /> Import JSON</button>
        </div>
        {jsonOpen && <div className="space-y-1.5"><textarea value={motionText} onChange={event => setMotionText(event.target.value)} placeholder="Paste movement JSON" rows={4} className="w-full rounded border border-border bg-bg-primary p-1.5 text-[9px] font-mono" /><div className="flex gap-1.5"><button onClick={() => { try { applyMotion(JSON.parse(motionText)); setMessage('Movement applied to selected layer.') } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid motion JSON.') } }} className="rounded bg-accent-blue px-2 py-1 text-[10px] text-white">Apply movement</button><button onClick={() => motionInputRef.current?.click()} className="rounded border border-border px-2 py-1 text-[10px]">Load motion file</button><button onClick={() => sceneInputRef.current?.click()} className="rounded border border-border px-2 py-1 text-[10px]">Import scene</button></div><input ref={motionInputRef} type="file" accept="application/json,.json" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) file.text().then(setMotionText) }} /><input ref={sceneInputRef} type="file" accept="application/json,.json" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) file.text().then(importScene) }} /></div>}
        <div className="rounded border border-border bg-bg-primary p-2 text-[9px] text-text-muted whitespace-pre-wrap">Return only valid Maestro Scene Animator motion JSON.{`\n`}Use start/end x and y from 0 to 100, start/end scale,{`\n`}duration in seconds, curve as linear/ease/dramatic/bounce,{`\n`}and optional spin plus rotationSpeed. For multi-step motion, add keyframes with id, time, x, y, scale, opacity, rotation and curve.{`\n`}Do not include Markdown or explanations.{`\n\n`}{'{"version":1,"motion":{"start":{"x":10,"y":70,"scale":0.2},"end":{"x":90,"y":30,"scale":0.8},"duration":3,"curve":"dramatic","spin":true,"rotationSpeed":240}}'}</div>
      </div>
      {message && <p className="text-[10px] text-text-secondary">{message}</p>}
    </aside>
  </div>
}
