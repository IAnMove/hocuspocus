// Process-owned Video 2D renderer used by the server export worker
// (scenes.video2d.export). It loads a frozen scene, preloads its media and paints
// deterministic frames with the same evaluator/painter as the Scene Animator.
import '../../i18n'
import '../../lib/kineticText/fonts.css'
import { createSceneEvaluator } from '../../lib/scene2d/evaluate'
import { isVisualLayer } from '../../lib/scene2d/layerStyle'
import { normalizeScene2D } from '../../lib/scene2d/normalize'
import { ensureTextFonts } from '../../lib/kineticText'
import { sequenceFrame } from '../../lib/scene2d/motion'
import { mixFxAudio } from '../sceneFx/mix'
import { sceneAudioWavDataUrl } from '../sceneFx/audioExport'
import { paintScene2D, type SceneMedia } from '../../lib/scene2d/paint'
import type { AnimatorLayer, AnimatorScene } from '../../lib/scene2d/types'
import { sceneProgressFromSeconds, sceneVideoTime } from '../../lib/sceneTimeline'
import { FrameAccumulator } from '../scene3d/exportQuality.ts'
import { heldFrameTime, holdBlock, motionStepOf, shiftHeldFrame, stopMotionJitterOf, stopMotionOffset } from '../stopMotion.ts'
import { qualityPaintSize, qualitySampleTimes, type QualityPlan } from './qualityFrame.ts'

type Size = QualityPlan
type Renderer = { load: (raw: unknown, size: Size) => Promise<void>; frame: (seconds: number) => Promise<string>; audio: () => Promise<string>; dispose: () => void }
declare global { interface Window { __scene2dExport: Renderer } }

const canvas = document.createElement('canvas')
let scene: AnimatorScene | null = null
let fps = 30
let plan: QualityPlan = { width: 0, height: 0 }
const media = new Map<string, HTMLImageElement | HTMLVideoElement>()
const sequenceImages = new Map<string, HTMLImageElement>()

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error(`Scene image could not load: ${source.slice(0, 200)}`))
    image.src = source
  })
}

function loadVideo(source: string): Promise<HTMLVideoElement> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video')
    video.crossOrigin = 'anonymous'
    video.muted = true
    video.preload = 'auto'
    video.playsInline = true
    video.onloadeddata = () => resolve(video)
    video.onerror = () => reject(new Error(`Scene video could not load: ${source.slice(0, 200)}`))
    video.src = source
  })
}

function seek(video: HTMLVideoElement, target: number): Promise<void> {
  if (Math.abs(video.currentTime - target) <= 1 / (fps * 4)) return Promise.resolve()
  return new Promise(resolve => {
    const done = () => { video.removeEventListener('seeked', done); resolve() }
    video.addEventListener('seeked', done)
    try { video.currentTime = target } catch { done() }
    window.setTimeout(done, 5000)
  })
}

async function syncVideos(current: AnimatorScene, seconds: number) {
  for (const layer of current.layers) {
    const element = media.get(layer.id)
    if (layer.type !== 'video' || !(element instanceof HTMLVideoElement) || !(element.duration > 0)) continue
    await seek(element, sceneVideoTime(layer, seconds, element.duration, fps))
  }
}

function hasSequence(layer: AnimatorLayer) {
  if (layer.sequence?.kind === 'frames') return layer.sequence.sources.length > 0
  return layer.sequence?.kind === 'sheet'
}

function assertRenderable(layer: AnimatorLayer) {
  if (layer.type === 'model3d') throw new Error('Headless Video 2D export does not support 3D model layers yet; render them in Video 3D.')
  if (layer.visible && isVisualLayer(layer) && layer.type !== 'effect' && !layer.source.trim() && !hasSequence(layer)) throw new Error(`Layer ${layer.name} has no media source.`)
}

/** Picture time. A hold repeats one frame; without motionStep the clock is the one the caller asked for. */
function pictureSeconds(seconds: number): number {
  if (!scene) return seconds
  const step = motionStepOf(scene.motionStep)
  const played = step ? heldFrameTime(seconds, fps, step) : seconds
  return Math.min(scene.duration, Math.max(0, played))
}

/** Shake the finished canvas once per hold. Jitter 0 does not read the pixels back. */
function shiftOutput(seconds: number) {
  if (!scene) return
  const step = motionStepOf(scene.motionStep)
  const jitter = stopMotionJitterOf(scene.stopMotionJitter)
  if (!step || !(jitter > 0)) return
  const context = canvas.getContext('2d')
  if (!context) return
  const held = pictureSeconds(seconds)
  shiftHeldFrame(context, canvas.width, canvas.height, stopMotionOffset(holdBlock(held, fps, step), jitter))
}

async function paintAt(seconds: number, target: HTMLCanvasElement) {
  if (!scene) throw new Error('Load a Video 2D snapshot first')
  const time = pictureSeconds(seconds)
  for (const layer of scene.layers) {
    if (layer.sequence?.kind === 'frames') {
      const image = sequenceImages.get(`${layer.id}:${sequenceFrame(layer.sequence, time)}`)
      if (image) media.set(layer.id, image)
    } else if (layer.sequence?.kind === 'sheet') {
      const image = sequenceImages.get(`${layer.id}:sheet`)
      if (image) media.set(layer.id, image)
    }
  }
  await syncVideos(scene, time)
  const progress = sceneProgressFromSeconds(time, scene.duration)
  const painted = paintScene2D(target, scene, progress, createSceneEvaluator(scene), layer => (media.get(layer.id) as SceneMedia | undefined) ?? null)
  if (!painted) throw new Error('Could not paint the Video 2D frame')
}

window.__scene2dExport = {
  async load(raw, size) {
    const next = normalizeScene2D(raw)
    next.layers.forEach(assertRenderable)
    fps = size.fps || next.fps || 30
    plan = size
    canvas.width = size.width
    canvas.height = size.height
    media.clear()
    await Promise.all(next.layers.filter(layer => layer.visible && (layer.type === 'image' || layer.type === 'overlay' || layer.type === 'video') && layer.source.trim()).map(async layer => {
      media.set(layer.id, layer.type === 'video' ? await loadVideo(layer.source) : await loadImage(layer.source))
    }))
    await ensureTextFonts(next.texts)
    sequenceImages.clear()
    await Promise.all(next.layers.flatMap(layer => {
      if (layer.sequence?.kind === 'frames') return layer.sequence.sources.map(async (source, index) => { sequenceImages.set(`${layer.id}:${index}`, await loadImage(source)) })
      if (layer.sequence?.kind === 'sheet') return [loadImage(layer.sequence.source).then(image => { sequenceImages.set(`${layer.id}:sheet`, image) })]
      return []
    }))
    scene = { ...next, width: size.width, height: size.height }
  },
  async frame(seconds) {
    if (!scene) throw new Error('Load a Video 2D snapshot first')
    const times = qualitySampleTimes(plan, seconds, scene.duration)
    const paintSize = qualityPaintSize(plan)
    if (times.length === 1 && paintSize.width === canvas.width && paintSize.height === canvas.height) {
      await paintAt(times[0], canvas)
      shiftOutput(times[0])
      return canvas.toDataURL('image/png')
    }
    const work = document.createElement('canvas')
    work.width = paintSize.width
    work.height = paintSize.height
    const sample = document.createElement('canvas')
    sample.width = canvas.width
    sample.height = canvas.height
    const sampleContext = sample.getContext('2d')
    const output = canvas.getContext('2d')
    if (!sampleContext || !output) throw new Error('Could not paint the Video 2D frame')
    const accumulator = new FrameAccumulator(canvas.width * canvas.height * 4)
    for (const time of times) {
      await paintAt(time, work)
      sampleContext.imageSmoothingQuality = 'high'
      sampleContext.clearRect(0, 0, sample.width, sample.height)
      sampleContext.drawImage(work, 0, 0, sample.width, sample.height)
      accumulator.add(sampleContext.getImageData(0, 0, sample.width, sample.height).data)
    }
    const image = new ImageData(canvas.width, canvas.height)
    image.data.set(accumulator.result())
    output.putImageData(image, 0, 0)
    shiftOutput(times[0] ?? seconds)
    return canvas.toDataURL('image/png')
  },
  async audio() {
    if (!scene?.sfx?.some(cue => cue.sound && cue.volume > 0)) return ''
    const buffer = await mixFxAudio(scene.sfx, scene.duration)
    return buffer ? sceneAudioWavDataUrl(buffer) : ''
  },
  dispose() {
    media.forEach(element => { if (element instanceof HTMLVideoElement) element.removeAttribute('src') })
    media.clear()
    scene = null
  },
}
