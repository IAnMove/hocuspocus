import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Box, ChevronDown, ChevronDown as Down, ChevronUp, Copy, Download, Eye, EyeOff, FileJson, Film, Image as ImageIcon, Loader2, Play, Plus, Trash2, Video } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { saveScene as saveSceneOutput, uploadImage } from '../../api/client'
import { PENDING_SCENE_KEY } from '../../lib/sceneOutput'
import type { Scene, SceneCurve, SceneLayer, SceneLayerType } from '../../types'

type Point = { x: number; y: number; scale: number; opacity?: number }
type Preset = { id: string; label: string; start: Point; end: Point; duration: number; spin: boolean; curve: SceneCurve; requiresTarget?: boolean; preview: string; poster: string }
type Gesture = { id: string; mode: 'move' | 'resize' | 'orbit'; startX: number; startY: number; x: number; y: number; scale: number; rotationX: number; rotationY: number }

const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const ease = (t: number, curve: SceneCurve) => curve === 'ease' ? t * t * (3 - 2 * t) : curve === 'dramatic' ? t * t : curve === 'bounce' ? Math.min(1, t + Math.sin(t * Math.PI * 3) * (1 - t) * .18) : t
const makePoint = (x: number, y: number, scale: number): Point => ({ x, y, scale })
const PRESETS: Preset[] = [
  ['turntable', 'Product turntable', 50, 50, 50, 50, .8, .8, 5, true, 'linear'], ['meteor', 'Meteor fly-by', -10, 82, 112, 18, .22, .65, 2, true, 'dramatic'], ['space-cruise', 'Spacecraft cruise', 8, 54, 92, 43, .48, .68, 5, true, 'ease'], ['hover', 'Hovering reveal', 50, 54, 50, 46, .7, .76, 4, true, 'ease'], ['landing', 'Landing', 50, -12, 50, 60, .2, .82, 4, false, 'bounce'], ['liftoff', 'Lift-off', 50, 68, 54, -15, .82, .28, 3, false, 'dramatic'], ['zoom-in', 'Hero zoom in', 50, 50, 50, 50, .18, 1.35, 3, true, 'dramatic'], ['zoom-out', 'Retreat into distance', 50, 50, 50, 50, 1.25, .18, 3, true, 'ease'], ['drift-right', 'Slow drift right', 25, 50, 75, 50, .68, .68, 6, false, 'linear'], ['drift-left', 'Slow drift left', 75, 50, 25, 50, .68, .68, 6, false, 'linear'], ['diagonal-rise', 'Diagonal rise', 20, 82, 78, 22, .38, .82, 4, true, 'ease'], ['diagonal-drop', 'Diagonal drop', 78, 16, 24, 84, .82, .35, 3, true, 'dramatic'], ['pop', 'Pop into frame', 50, 50, 50, 50, .05, .85, 1, true, 'bounce'], ['glide', 'Low glide', -8, 72, 108, 70, .4, .52, 4, false, 'ease'], ['pass-camera', 'Pass the camera', 16, 50, 90, 50, .18, 1.5, 3, true, 'dramatic'], ['vibrate', 'Nave vibrando', 49, 51, 51, 49, .72, .75, 2, false, 'bounce'], ['orbit-sweep', 'Orbit sweep', 18, 70, 86, 30, .32, .9, 5, true, 'ease'], ['center-reveal', 'Center reveal', 50, 105, 50, 52, .35, .9, 3, true, 'ease'], ['exit-frame', 'Emergency exit', 50, 50, 120, -10, .8, .25, 2, true, 'dramatic'], ['floating-logo', 'Floating logo', 50, 45, 50, 55, .72, .72, 4, true, 'ease'],
].map(([id, label, sx, sy, ex, ey, ss, es, duration, spin, curve]) => ({ id: id as string, label: label as string, start: makePoint(sx as number, sy as number, ss as number), end: makePoint(ex as number, ey as number, es as number), duration: duration as number, spin: spin as boolean, curve: curve as SceneCurve })).concat([
  { id: 'orbit-layer', label: 'Orbit around another layer', start: makePoint(50, 50, .45), end: makePoint(50, 50, .45), duration: 5, spin: true, curve: 'linear', requiresTarget: true } as Omit<Preset, 'preview' | 'poster'>,
]).map(preset => ({ ...preset, preview: `/preset-previews/${preset.id}.webm`, poster: `/preset-previews/${preset.id}.webp` }))

const blankScene = (): Scene => ({ version: 1, name: 'Untitled scene', width: 1280, height: 720, duration: 5, layers: [] })
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const isMissing = (source: string) => source.startsWith('blob:')
const iconFor = (type: SceneLayerType) => type === 'model3d' ? <Box size={13} /> : type === 'video' ? <Video size={13} /> : <ImageIcon size={13} />
const RESOLUTIONS = [
  ['HD landscape', 1280, 720], ['Full HD landscape', 1920, 1080], ['4K landscape', 3840, 2160],
  ['Square', 1080, 1080], ['HD portrait', 720, 1280], ['Full HD portrait', 1080, 1920], ['4K portrait', 2160, 3840],
] as const

const assignZ = (layers: SceneLayer[]) => layers.map((layer, index) => ({ ...layer, z: index * 10 }))
const normalizeZ = (layers: SceneLayer[]) => assignZ([...layers].sort((a, b) => a.z - b.z))

function MotionPresetCard({ preset, selected, onSelect }: { preset: Preset; selected: boolean; onSelect: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [hovered, setHovered] = useState(false)
  const play = () => { setHovered(true); const video = videoRef.current; if (!video) return; video.currentTime = 0; void video.play().catch(() => {}) }
  const stop = () => { setHovered(false); const video = videoRef.current; if (!video) return; video.pause(); video.currentTime = 0 }
  return <button type="button" onClick={onSelect} onPointerEnter={play} onPointerLeave={stop} onFocus={play} onBlur={stop} className={`overflow-hidden rounded border text-left transition-colors ${selected ? 'border-accent-blue bg-accent-blue/10 ring-1 ring-accent-blue/40' : 'border-border bg-bg-primary hover:border-accent-blue/70'}`}>
    <div className="relative aspect-video overflow-hidden bg-[#07111f]"><img src={preset.poster} alt="" className="absolute inset-0 h-full w-full object-cover" /><video ref={videoRef} src={preset.preview} poster={preset.poster} muted loop playsInline preload="metadata" className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity ${hovered ? 'opacity-100' : 'opacity-0'}`} /></div>
    <div className="flex min-h-9 items-center justify-between gap-1 px-1.5 py-1"><span className="line-clamp-2 text-[9px] leading-tight text-text-secondary">{preset.label}</span>{preset.requiresTarget && <span className="shrink-0 rounded bg-accent-blue/15 px-1 py-0.5 text-[8px] text-accent-blue">2 layers</span>}</div>
  </button>
}

export function SceneAnimatorPanel() {
  const outputs = useStore(s => s.outputs)
  const loadOutputs = useStore(s => s.loadOutputs)
  const [scene, setScene] = useState<Scene>(blankScene)
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
  const selected = scene.layers.find(layer => layer.id === selectedId) ?? null
  const generatedModels = outputs.filter(output => output.type === 'model3d' && /\.glb$/i.test(output.name))
  const generatedMedia = outputs.filter(output => output.type === 'image' || output.type === 'video')

  useEffect(() => { void import('@google/model-viewer') }, [])
  useEffect(() => { void loadOutputs() }, [loadOutputs])
  useEffect(() => () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); if (flashTimerRef.current) clearTimeout(flashTimerRef.current) }, [])

  const updateScene = (updater: (current: Scene) => Scene) => setScene(current => updater(current))
  const updateLayer = (id: string, updater: (layer: SceneLayer) => SceneLayer) => updateScene(current => ({ ...current, layers: current.layers.map(layer => layer.id === id ? updater(layer) : layer) }))
  const flashAt = (x: number, y: number) => { setFlash({ x, y }); if (flashTimerRef.current) clearTimeout(flashTimerRef.current); flashTimerRef.current = window.setTimeout(() => setFlash(null), 550) }
  const addLayer = (type: SceneLayerType, source: string, name: string, thumbnail?: string, localFile?: File) => {
    const id = uid()
    if (localFile) localFilesRef.current[id] = localFile
    updateScene(current => {
      const foregroundCount = current.layers.filter(layer => layer.type === 'model3d' || layer.type === 'overlay').length
      const offset = type === 'model3d' || type === 'overlay' ? Math.min(24, foregroundCount * 6) : 0
      const scale = type === 'model3d' ? .7 : 1
      const layer: SceneLayer = { id, name, type, source, thumbnail, visible: true, z: 0, transform: { x: 50 + offset, y: 50 + offset / 3, scale, opacity: 1, rotation: 0, rotationX: 75, rotationY: 0 }, animation: { start: makePoint(50 + offset, 50 + offset / 3, scale), end: makePoint(50 + offset, 50 + offset / 3, scale), duration: current.duration, curve: 'linear', spin: type === 'model3d', rotationSpeed: 35 } }
      const ordered = normalizeZ(current.layers)
      const layers = type === 'image' || type === 'video' ? [layer, ...ordered] : [...ordered, layer]
      return { ...current, layers: normalizeZ(layers) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null)
  }
  const addOrReassign = (type: SceneLayerType, file: File) => {
    const source = URL.createObjectURL(file)
    if (reassignId) {
      localFilesRef.current[reassignId] = file
      updateLayer(reassignId, layer => ({ ...layer, type, source, name: file.name, missingAsset: false }))
      setReassignId(null)
    } else addLayer(type, source, file.name, undefined, file)
  }
  const translateLayer = (id: string, x: number, y: number) => updateLayer(id, layer => {
    const dx = x - layer.transform.x; const dy = y - layer.transform.y
    return { ...layer, transform: { ...layer.transform, x, y }, animation: { ...layer.animation, start: { ...layer.animation.start, x: layer.animation.start.x + dx, y: layer.animation.start.y + dy }, end: { ...layer.animation.end, x: layer.animation.end.x + dx, y: layer.animation.end.y + dy } } }
  })
  const resizeLayer = (id: string, scale: number) => updateLayer(id, layer => ({ ...layer, transform: { ...layer.transform, scale }, animation: { ...layer.animation, start: { ...layer.animation.start, scale }, end: { ...layer.animation.end, scale } } }))
  const startGesture = (event: ReactPointerEvent<HTMLElement>, layer: SceneLayer, mode: Gesture['mode']) => {
    event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id)
    gestureRef.current = { id: layer.id, mode, startX: event.clientX, startY: event.clientY, x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, rotationX: layer.transform.rotationX ?? 75, rotationY: layer.transform.rotationY ?? 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = gestureRef.current; const bounds = canvasRef.current?.getBoundingClientRect(); if (!gesture || !bounds) return
    if (gesture.mode === 'move') { const x = gesture.x + (event.clientX - gesture.startX) / bounds.width * 100; const y = gesture.y + (event.clientY - gesture.startY) / bounds.height * 100; translateLayer(gesture.id, x, y); flashAt(x, y) }
    else if (gesture.mode === 'resize') resizeLayer(gesture.id, Math.max(.05, Math.min(3, gesture.scale + (event.clientX - gesture.startX + event.clientY - gesture.startY) / Math.min(bounds.width, bounds.height))))
    else updateLayer(gesture.id, layer => ({ ...layer, transform: { ...layer.transform, rotationY: gesture.rotationY + (event.clientX - gesture.startX) * .8, rotationX: Math.max(1, Math.min(179, gesture.rotationX + (event.clientY - gesture.startY) * .5)) } }))
  }
  const endGesture = () => { gestureRef.current = null }
  const baseLayerState = (layer: SceneLayer, time: number) => { const t = ease(Math.min(1, time * scene.duration / Math.max(1, layer.animation.duration)), layer.animation.curve); return { x: lerp(layer.animation.start.x, layer.animation.end.x, t), y: lerp(layer.animation.start.y, layer.animation.end.y, t), scale: lerp(layer.animation.start.scale, layer.animation.end.scale, t), opacity: lerp(layer.animation.start.opacity ?? layer.transform.opacity, layer.animation.end.opacity ?? layer.transform.opacity, t), rotation: layer.transform.rotation ?? 0, z: layer.z } }
  const layerState = (layer: SceneLayer, time = progress) => {
    const state = baseLayerState(layer, time)
    const orbit = layer.animation.orbit
    const target = orbit && scene.layers.find(item => item.id === orbit.targetLayerId)
    if (!orbit || !target || target.id === layer.id) return state
    const targetState = baseLayerState(target, time)
    const orbitProgress = Math.min(1, time * scene.duration / Math.max(1, layer.animation.duration))
    const angle = orbit.phase * Math.PI / 180 + orbitProgress * orbit.turns * Math.PI * 2
    const depth = Math.sin(angle)
    const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
    const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
    return { ...state, x: centerX + Math.cos(angle) * orbit.radiusX, y: centerY + depth * orbit.radiusY, scale: state.scale * (1 + depth * .12), z: target.z + (depth >= 0 ? 1 : -1) }
  }
  const moveLayerZ = (id: string, direction: 1 | -1) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const index = layers.findIndex(layer => layer.id === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= layers.length) return current
    const next = [...layers]; [next[index], next[target]] = [next[target], next[index]]
    return { ...current, layers: assignZ(next) }
  })
  const sendToBack = (id: string) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const layer = layers.find(item => item.id === id)
    if (!layer) return current
    return { ...current, layers: assignZ([layer, ...layers.filter(item => item.id !== id)]) }
  })
  const animate = (done?: () => void) => { const started = performance.now(); setPlaying(true); Object.values(videoRefs.current).forEach(video => { if (video) { video.currentTime = 0; void video.play().catch(() => {}) } }); const frame = (now: number) => { const next = Math.min(1, (now - started) / (scene.duration * 1000)); setProgress(next); if (next < 1) animationRef.current = requestAnimationFrame(frame); else { setPlaying(false); Object.values(videoRefs.current).forEach(video => video?.pause()); done?.() } }; animationRef.current = requestAnimationFrame(frame) }
  const play = () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); setProgress(0); animate() }
  const applyPreset = (presetId: string) => {
    if (!selected) return
    const preset = PRESETS.find(item => item.id === presetId)
    if (!preset) return
    const target = scene.layers.find(layer => layer.id !== selected.id && layer.type === 'model3d') ?? scene.layers.find(layer => layer.id !== selected.id)
    if (preset.requiresTarget && !target) { setMessage('Add a second layer before applying this relational movement.'); return }
    updateLayer(selected.id, layer => ({ ...layer, animation: { start: preset.start, end: preset.end, duration: preset.duration, curve: preset.curve, spin: preset.spin, rotationSpeed: layer.animation.rotationSpeed, orbit: preset.requiresTarget && target ? { targetLayerId: target.id, radiusX: 18, radiusY: 9, turns: 2, phase: 0, centerOffsetX: 0, centerOffsetY: 0 } : undefined } }))
    updateScene(current => ({ ...current, duration: Math.max(current.duration, preset.duration) }))
    setMessage(preset.requiresTarget ? `Orbit target: ${target?.name}` : null); setProgress(0)
  }
  const motion = (layer: SceneLayer) => ({ start: layer.animation.start, end: layer.animation.end, duration: layer.animation.duration, curve: layer.animation.curve, spin: layer.animation.spin, rotationSpeed: layer.animation.rotationSpeed, orbit: layer.animation.orbit })
  const applyMotion = (raw: unknown) => { if (!selected || !raw || typeof raw !== 'object') throw new Error('Select a layer and provide a motion object.'); const value = (raw as { motion?: unknown }).motion ?? raw; if (!value || typeof value !== 'object') throw new Error('JSON must contain motion.'); const item = value as Partial<SceneLayer['animation']>; if (!item.start || !item.end || typeof item.duration !== 'number') throw new Error('Motion needs start, end and duration.'); const duration = item.duration; updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, ...item, start: { ...layer.animation.start, ...item.start }, end: { ...layer.animation.end, ...item.end }, duration: Math.max(1, duration), curve: ['linear', 'ease', 'dramatic', 'bounce'].includes(item.curve ?? '') ? item.curve as SceneCurve : 'linear' } })); setProgress(0) }
  const download = (name: string, data: unknown) => { const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url) }
  const importScene = (text: string) => { try { const incoming = JSON.parse(text) as Scene; if (incoming.version !== 1 || !Array.isArray(incoming.layers)) throw new Error('This is not a Maestro Scene Animator scene.'); const layers = normalizeZ(incoming.layers.map(layer => ({ ...layer, transform: { ...layer.transform, rotationX: layer.transform.rotationX ?? 75, rotationY: layer.transform.rotationY ?? 0 }, missingAsset: Boolean(layer.missingAsset || isMissing(layer.source)) }))); localFilesRef.current = {}; setScene({ ...blankScene(), ...incoming, layers }); setSelectedId(layers[0]?.id ?? null); setMessage('Scene imported. Reassign layers marked missing asset.'); setJsonOpen(false) } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid scene JSON.') } }
  useEffect(() => {
    const pending = sessionStorage.getItem(PENDING_SCENE_KEY)
    if (!pending) return
    sessionStorage.removeItem(PENDING_SCENE_KEY)
    importScene(pending)
  }, [])
  const paintScene = (canvas: HTMLCanvasElement, time: number) => {
    const context = canvas.getContext('2d')
    if (!context) return false
    context.fillStyle = '#0b1020'; context.fillRect(0, 0, canvas.width, canvas.height)
    scene.layers.filter(layer => layer.visible).map(layer => ({ layer, state: layerState(layer, time) })).sort((a, b) => a.state.z - b.state.z).forEach(({ layer, state }) => {
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
    if (!scene.layers.some(layer => layer.visible)) { setMessage('Add a visible layer before recording.'); return }
    if (!('MediaRecorder' in window)) { setMessage('This browser cannot record the scene.'); return }
    const canvas = document.createElement('canvas'); canvas.width = scene.width; canvas.height = scene.height; if (!canvas.getContext('2d')) return
    const stream = canvas.captureStream(30); const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm'; const recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8_000_000 }); const chunks: Blob[] = []
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }; recorder.onstop = () => { const url = URL.createObjectURL(new Blob(chunks, { type: mime })); const link = document.createElement('a'); link.href = url; link.download = `maestro-scene-${Date.now()}.webm`; link.click(); URL.revokeObjectURL(url); setRecording(false) }
    setRecording(true); setProgress(0); recorder.start(250); const started = performance.now(); Object.values(videoRefs.current).forEach(video => { if (video) { video.currentTime = 0; void video.play().catch(() => {}) } }); const frame = (now: number) => { const next = Math.min(1, (now - started) / (scene.duration * 1000)); setProgress(next); paintScene(canvas, next); if (next < 1) requestAnimationFrame(frame); else { Object.values(videoRefs.current).forEach(video => video?.pause()); recorder.stop() } }; requestAnimationFrame(frame)
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
        if (!layer.source.startsWith('blob:')) return layer
        const file = localFilesRef.current[layer.id]
        if (!file) return { ...layer, missingAsset: true }
        const uploaded = await uploadImage(file)
        return { ...layer, source: uploaded.url, missingAsset: false }
      }))
      const persisted = { ...scene, layers }
      const saved = await saveSceneOutput(persisted, preview.toDataURL('image/png'))
      setScene(persisted); localFilesRef.current = {}; await loadOutputs()
      setMessage(`Scene saved to Maestro as ${saved.name}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save scene.')
    } finally {
      setSaving(false)
    }
  }
  const numberInput = (label: string, value: number, change: (value: number) => void, min = -100, max = 200, step = 1) => <label className="text-[10px] text-text-muted">{label}<input type="number" min={min} max={max} step={step} value={value} onChange={event => change(Number(event.target.value))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label>
  const orbitPivot = (() => {
    const orbit = selected?.animation.orbit
    const target = orbit && scene.layers.find(layer => layer.id === orbit.targetLayerId)
    if (!orbit || !target) return null
    const targetState = baseLayerState(target, progress)
    return { x: targetState.x + (orbit.centerOffsetX ?? 0), y: targetState.y + (orbit.centerOffsetY ?? 0) }
  })()
  const renderLayer = (layer: SceneLayer) => {
    const state = layerState(layer); const common = { left: `${state.x}%`, top: `${state.y}%`, width: `${(layer.type === 'model3d' ? 52 : 100) * state.scale}%`, height: `${(layer.type === 'model3d' ? 75 : 100) * state.scale}%`, opacity: state.opacity, zIndex: state.z, transform: `translate(-50%, -50%) rotate(${state.rotation}deg)` }; const selection = selectedId === layer.id
    if (!layer.visible) return null
    if (layer.missingAsset) return <button key={layer.id} onClick={() => setSelectedId(layer.id)} className={`absolute flex items-center justify-center border border-dashed border-red-400/70 bg-red-500/10 text-[10px] text-red-300 ${selection ? 'ring-2 ring-accent-blue ring-inset' : ''}`} style={common}>Missing asset</button>
    const edgeMove = (event: ReactPointerEvent<HTMLElement>) => { if (layer.type !== 'model3d') return startGesture(event, layer, 'move'); const box = event.currentTarget.getBoundingClientRect(); const edge = (event.clientX - box.left) / box.width < .18 || (event.clientX - box.left) / box.width > .82 || (event.clientY - box.top) / box.height < .18 || (event.clientY - box.top) / box.height > .82; startGesture(event, layer, edge ? 'move' : 'orbit') }
    const media = layer.type === 'model3d'
      ? <model-viewer data-layer-id={layer.id} src={layer.source} camera-orbit={`${layer.transform.rotationY ?? 0}deg ${layer.transform.rotationX ?? 75}deg auto`} interaction-prompt="none" auto-rotate={layer.animation.spin && (playing || recording) ? true : undefined} rotation-per-second={`${layer.animation.rotationSpeed ?? 35}deg`} shadow-intensity="1" exposure="1" loading="eager" className="scene-animator-model pointer-events-none h-full w-full" />
      : layer.type === 'video'
        ? <video data-layer-id={layer.id} ref={element => { videoRefs.current[layer.id] = element }} src={layer.source} muted loop className={`h-full w-full ${layer.fill ? 'object-cover' : 'object-contain'}`} />
        : <img data-layer-id={layer.id} src={layer.source} alt={layer.name} draggable={false} className={`h-full w-full select-none ${layer.fill ? 'object-cover' : 'object-contain'}`} />
    return <div key={layer.id} style={common} onPointerDown={edgeMove} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} className={`absolute touch-none cursor-grab active:cursor-grabbing ${selection ? 'ring-2 ring-accent-blue ring-inset' : ''}`}>{media}{selection && <button aria-label="Resize layer" onPointerDown={event => startGesture(event, layer, 'resize')} onPointerMove={moveGesture} onPointerUp={endGesture} className="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-white bg-accent-blue shadow" />}</div>
  }

  return <div className="flex min-h-[620px] flex-col overflow-hidden rounded-xl border border-border bg-bg-tertiary xl:flex-row">
    <section className="flex min-w-0 flex-1 flex-col p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-1.5 text-xs font-medium"><Film size={15} className="text-accent-blue" /><input value={scene.name} onChange={event => updateScene(current => ({ ...current, name: event.target.value }))} aria-label="Scene name" className="w-44 rounded border border-transparent bg-transparent px-1 py-0.5 text-xs font-medium hover:border-border focus:border-accent-blue focus:outline-none" /><span className="text-[10px] font-normal text-text-muted">{scene.width}×{scene.height}</span></div><div className="flex gap-2"><button onClick={play} disabled={!scene.layers.length || playing || recording} className="rounded border border-border bg-bg-primary px-2.5 py-1.5 text-[10px] flex items-center gap-1 disabled:opacity-50"><Play size={12} /> Preview</button><button onClick={record} disabled={recording} className="rounded bg-cta px-2.5 py-1.5 text-[10px] text-white flex items-center gap-1 disabled:opacity-50">{recording ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}{recording ? 'Recording…' : 'Record WebM'}</button></div></div>
      <div className="mb-3 flex flex-wrap gap-1">{RESOLUTIONS.map(([label, width, height]) => <button key={label} onClick={() => updateScene(current => ({ ...current, width, height }))} className={`rounded border px-1.5 py-1 text-[9px] ${scene.width === width && scene.height === height ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-muted'}`}>{label}</button>)}</div>
      {selected && selected.type !== 'model3d' && <button onClick={() => updateLayer(selected.id, layer => ({ ...layer, fill: !layer.fill, transform: { ...layer.transform, x: 50, y: 50, scale: 1 }, animation: { ...layer.animation, start: { ...layer.animation.start, x: 50, y: 50, scale: 1 }, end: { ...layer.animation.end, x: 50, y: 50, scale: 1 } } }))} className={`mb-3 rounded border px-2 py-1 text-[10px] ${selected.fill ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-secondary'}`}>{selected.fill ? 'Fill screen enabled' : 'Fill screen'}</button>}
      {selected && selected.type !== 'model3d' && <button onClick={() => sendToBack(selected.id)} className="mb-3 ml-1 rounded border border-border bg-bg-primary px-2 py-1 text-[10px] text-text-secondary">Use as background</button>}
      <div ref={canvasRef} className="relative isolate mx-auto w-full min-h-[240px] overflow-hidden rounded-lg border border-border bg-[#0b1020]" style={{ aspectRatio: `${scene.width} / ${scene.height}`, maxHeight: '68vh' }}>{[...scene.layers].sort((a, b) => a.z - b.z).map(renderLayer)}{orbitPivot && <div className="pointer-events-none absolute z-[998] h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-300 bg-cyan-400/20 shadow-[0_0_8px_rgba(103,232,249,.9)]" style={{ left: `${orbitPivot.x}%`, top: `${orbitPivot.y}%` }}><span className="absolute left-1/2 top-[-5px] h-6 w-px -translate-x-1/2 bg-cyan-300/80" /><span className="absolute left-[-5px] top-1/2 h-px w-6 -translate-y-1/2 bg-cyan-300/80" /></div>}{flash && <div className="pointer-events-none absolute z-[999]" style={{ left: `${flash.x}%`, top: `${flash.y}%` }}><span className="absolute -left-6 -top-6 h-12 w-12 rounded-full border-2 border-white/90 animate-ping" /><span className="absolute -left-1.5 -top-1.5 h-3 w-3 rounded-full bg-white shadow-[0_0_20px_8px_rgba(96,165,250,.9)]" /></div>}<div className="absolute inset-x-0 bottom-0 z-[1000] h-1 bg-black/40"><div className="h-full bg-accent-blue" style={{ width: `${progress * 100}%` }} /></div></div>
      <p className="mt-2 text-[9px] text-text-muted">Center-drag a 3D layer to orbit it 360°; drag its outer edge to move it. Drag the blue corner handle to resize. Images and videos drag directly. WebM uses the selected scene resolution and Z order.</p>
    </section>
    <aside className="w-full shrink-0 border-t border-border bg-bg-secondary p-3 overflow-y-auto space-y-3 xl:w-[300px] xl:border-l xl:border-t-0">
      <div className="relative"><button onClick={() => setAddOpen(value => !value)} className="w-full rounded bg-accent-blue px-2.5 py-2 text-xs text-white flex items-center justify-center gap-1"><Plus size={13} /> Add layer</button>{addOpen && <div className="absolute z-[1100] mt-1 w-full rounded border border-border bg-bg-primary p-1 shadow-xl space-y-1"><button onClick={() => { setPicker('model'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated 3D model</button><button onClick={() => { setAddOpen(false); modelInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import GLB</button><button onClick={() => { setPicker('media'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated image/video</button><button onClick={() => { setAddOpen(false); mediaInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import image/video</button><button onClick={() => { setAddOpen(false); overlayInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import transparent PNG/WebP</button></div>}</div>
      {picker && <div className="rounded border border-border bg-bg-primary p-2"><div className="mb-1 flex justify-between text-[10px] text-text-muted"><span>{picker === 'model' ? 'Generated 3D models' : 'Generated images & videos'}</span><button onClick={() => setPicker(null)}><Down size={13} /></button></div><div className="grid grid-cols-3 gap-1.5 max-h-40 overflow-y-auto">{(picker === 'model' ? generatedModels : generatedMedia).map(asset => <button key={asset.name} onClick={() => addLayer(asset.type === 'model3d' ? 'model3d' : asset.type === 'video' ? 'video' : 'image', asset.url, asset.name, asset.thumbnail_url ?? undefined)} className="overflow-hidden rounded border border-border text-left hover:border-accent-blue"><div className="aspect-square bg-bg-active">{asset.thumbnail_url || asset.type === 'image' ? <img src={asset.thumbnail_url ?? asset.url} alt="" className="h-full w-full object-cover" /> : <div className="h-full flex items-center justify-center"><Video size={16} /></div>}</div><span className="block truncate px-1 py-1 text-[9px]">{asset.name}</span></button>)}</div></div>}
      <input ref={modelInputRef} type="file" accept=".glb,model/gltf-binary" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign('model3d', file) }} /><input ref={mediaInputRef} type="file" accept="image/*,video/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign(file.type.startsWith('video/') ? 'video' : 'image', file) }} /><input ref={overlayInputRef} type="file" accept="image/png,image/webp" multiple className="hidden" onChange={event => [...(event.target.files ?? [])].forEach(file => addOrReassign('overlay', file))} />
      <div><div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-text-muted">Layers</div><div className="space-y-1">{[...scene.layers].sort((a, b) => b.z - a.z).map(layer => <div key={layer.id} onClick={() => setSelectedId(layer.id)} className={`flex cursor-pointer items-center gap-1.5 rounded border p-1.5 text-[10px] ${selectedId === layer.id ? 'border-accent-blue bg-accent-blue/10' : 'border-border bg-bg-primary'}`}><div className="h-7 w-7 shrink-0 overflow-hidden rounded bg-bg-active flex items-center justify-center">{layer.thumbnail ? <img src={layer.thumbnail} alt="" className="h-full w-full object-cover" /> : iconFor(layer.type)}</div><div className="min-w-0 flex-1"><div className="truncate">{layer.name}</div><div className="text-[9px] text-text-muted">{layer.type} · z: {layer.z}{layer.missingAsset ? ' · missing asset' : ''}</div></div><button onClick={event => { event.stopPropagation(); updateLayer(layer.id, item => ({ ...item, visible: !item.visible })) }} title="Visibility">{layer.visible ? <Eye size={12} /> : <EyeOff size={12} />}</button><div className="flex flex-col"><button title="Bring forward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, 1) }}><ChevronUp size={12} /></button><button title="Send backward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, -1) }}><ChevronDown size={12} /></button></div><button onClick={event => { event.stopPropagation(); updateScene(current => ({ ...current, layers: normalizeZ(current.layers.filter(item => item.id !== layer.id)) })); if (selectedId === layer.id) setSelectedId(null) }} className="text-red-400"><Trash2 size={12} /></button></div>)}</div></div>
      {selected ? <div className="border-t border-border pt-3 space-y-2"><div className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Layer inspector</div>{selected.missingAsset && <button onClick={() => { setReassignId(selected.id); (selected.type === 'model3d' ? modelInputRef : selected.type === 'overlay' ? overlayInputRef : mediaInputRef).current?.click() }} className="w-full rounded border border-red-400/50 py-1.5 text-[10px] text-red-300">Reassign missing asset</button>}<label className="text-[10px] text-text-muted">Name<input value={selected.name} onChange={event => updateLayer(selected.id, layer => ({ ...layer, name: event.target.value }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label><div className="grid grid-cols-3 gap-1.5">{numberInput('X', selected.transform.x, value => { const delta = value - selected.transform.x; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, x: value }, animation: { ...layer.animation, start: { ...layer.animation.start, x: layer.animation.start.x + delta }, end: { ...layer.animation.end, x: layer.animation.end.x + delta } } })); flashAt(value, selected.transform.y) }, -100, 200)}{numberInput('Y', selected.transform.y, value => { const delta = value - selected.transform.y; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, y: value }, animation: { ...layer.animation, start: { ...layer.animation.start, y: layer.animation.start.y + delta }, end: { ...layer.animation.end, y: layer.animation.end.y + delta } } })); flashAt(selected.transform.x, value) }, -100, 200)}{numberInput('Z', selected.z, value => updateLayer(selected.id, layer => ({ ...layer, z: value })))}{numberInput('Scale', selected.transform.scale, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, scale: value }, animation: { ...layer.animation, start: { ...layer.animation.start, scale: value }, end: { ...layer.animation.end, scale: value } } })), .05, 3, .05)}{numberInput('Opacity', selected.transform.opacity, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, opacity: value }, animation: { ...layer.animation, start: { ...layer.animation.start, opacity: value }, end: { ...layer.animation.end, opacity: value } } })), 0, 1, .05)}{numberInput('Rotation', selected.transform.rotation ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, rotation: value } })), -360, 360)} </div><label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={selected.visible} onChange={event => updateLayer(selected.id, layer => ({ ...layer, visible: event.target.checked }))} /> Visible</label><div className="space-y-1.5"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Motion presets</span><span className="text-[9px] text-text-muted">Hover to preview · click to apply</span></div><div className="grid max-h-[370px] grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">{PRESETS.map(preset => <MotionPresetCard key={preset.id} preset={preset} selected={selectedPresetId === preset.id} onSelect={() => { setSelectedPresetId(preset.id); applyPreset(preset.id) }} />)}</div></div><div className="grid grid-cols-2 gap-1.5">{(['start', 'end'] as const).map(key => <div key={key} className="space-y-1"><div className="text-[10px] text-text-muted capitalize">{key} motion</div>{numberInput('X', selected.animation[key].x, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], x: value } } })))}{numberInput('Y', selected.animation[key].y, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], y: value } } })))}{numberInput('Scale', selected.animation[key].scale, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], scale: value } } })), .05, 3, .05)}</div>)}</div><div className="grid grid-cols-2 gap-1.5">{numberInput('Duration (s)', selected.animation.duration, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, duration: Math.max(1, value) } })), 1, 30)}<label className="text-[10px] text-text-muted">Curve<select value={selected.animation.curve} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, curve: event.target.value as SceneCurve } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="linear">Linear</option><option value="ease">Ease</option><option value="dramatic">Dramatic</option><option value="bounce">Bounce</option></select></label></div>{selected.type === 'model3d' && <div className="grid grid-cols-2 gap-1.5"><label className="flex items-end gap-1.5 pb-1 text-[10px]"><input type="checkbox" checked={Boolean(selected.animation.spin)} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, spin: event.target.checked } }))} /> Auto spin</label>{numberInput('Spin °/sec', selected.animation.rotationSpeed ?? 35, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, rotationSpeed: value } })), 0, 720)}</div>}</div> : <p className="text-[10px] text-text-muted">Select a layer to edit it.</p>}
      {selected?.animation.orbit && <div className="rounded border border-accent-blue/40 bg-accent-blue/10 p-2 space-y-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-accent-blue">Relational orbit</span><button onClick={() => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: undefined } }))} className="text-[9px] text-text-muted hover:text-red-400">Remove</button></div>
        <label className="text-[10px] text-text-muted">Orbit around<select value={selected.animation.orbit.targetLayerId} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, targetLayerId: event.target.value } : undefined } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs">{scene.layers.filter(layer => layer.id !== selected.id).map(layer => <option key={layer.id} value={layer.id}>{layer.name} · {layer.type}</option>)}</select></label>
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
        <div className="rounded border border-border bg-bg-primary p-2 text-[9px] text-text-muted whitespace-pre-wrap">Return only valid Maestro Scene Animator motion JSON.{`\n`}Use start/end x and y from 0 to 100, start/end scale,{`\n`}duration in seconds, curve as linear/ease/dramatic/bounce,{`\n`}and optional spin plus rotationSpeed.{`\n`}Do not include Markdown or explanations.{`\n\n`}{'{"version":1,"motion":{"start":{"x":10,"y":70,"scale":0.2},"end":{"x":90,"y":30,"scale":0.8},"duration":3,"curve":"dramatic","spin":true,"rotationSpeed":240}}'}</div>
      </div>
      {message && <p className="text-[10px] text-text-secondary">{message}</p>}
    </aside>
  </div>
}
