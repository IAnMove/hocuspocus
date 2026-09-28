// Pure Video 2D frame painter shared by the Scene Animator export and the
// headless scene2d renderer. Media lookup is injected so the same drawing code
// works with live DOM elements (editor) or preloaded images/videos (headless).
import { paintSceneFx } from '../../features/sceneFx/paint'
import { paintKineticTexts, paintSceneLyrics } from '../kineticText'
import { paintSceneFinish } from './finish'
import { beatEnvelope, sheetCrop } from './motion'
import { paintSeamOccluder } from '../seamOccluder'
import type { SceneEvaluator } from './evaluate'
import { applyLayerMask, drawAtmosphere, effectFilter, isVisualLayer, normalizedAtmosphere, normalizedEffects, normalizedStrip } from './layerStyle'
import type { AnimatorScene, VisualAnimatorLayer } from './types'

export type SceneMedia = HTMLImageElement | HTMLVideoElement | HTMLCanvasElement | ImageBitmap
/** Return the drawable for a visual layer instance, or null when it is not ready. */
export type SceneMediaLookup = (layer: VisualAnimatorLayer, instanceIndex: number) => SceneMedia | null

function mediaSize(media: SceneMedia): [number, number] {
  if (typeof HTMLVideoElement !== 'undefined' && media instanceof HTMLVideoElement) return [media.videoWidth, media.videoHeight]
  if (typeof HTMLImageElement !== 'undefined' && media instanceof HTMLImageElement) return [media.naturalWidth, media.naturalHeight]
  return [(media as HTMLCanvasElement).width, (media as HTMLCanvasElement).height]
}

function mediaReady(media: SceneMedia): boolean {
  if (typeof HTMLVideoElement !== 'undefined' && media instanceof HTMLVideoElement) return media.readyState >= 2
  if (typeof HTMLImageElement !== 'undefined' && media instanceof HTMLImageElement) return media.complete && media.naturalWidth > 0
  return true
}

function effectAnchor(current: AnimatorScene, layer: VisualAnimatorLayer, evaluator: SceneEvaluator, progress: number) {
  const emitter = normalizedAtmosphere(layer.atmosphere).emitter
  if (!emitter || emitter.mode === 'frame') return undefined
  if (emitter.mode === 'point') return { x: emitter.x ?? 50, y: emitter.y ?? 50 }
  const target = current.layers.find(item => item.id === emitter.targetLayerId)
  if (!target) return undefined
  const state = evaluator.layerState(target, progress)
  return { x: state.x + (emitter.offsetX ?? 0), y: state.y + (emitter.offsetY ?? 0) }
}

function fittedSize(fill: boolean | undefined, sourceRatio: number, targetRatio: number, width: number, height: number) {
  if (!fill) return sourceRatio > targetRatio ? { drawWidth: width, drawHeight: width / sourceRatio } : { drawWidth: height * sourceRatio, drawHeight: height }
  return sourceRatio > targetRatio ? { drawWidth: height * sourceRatio, drawHeight: height } : { drawWidth: width, drawHeight: width / sourceRatio }
}

function drawLayerImage(context: CanvasRenderingContext2D, layer: VisualAnimatorLayer, media: SceneMedia, width: number, height: number, seconds: number) {
  const [sourceWidth, sourceHeight] = mediaSize(media)
  const crop = layer.sequence?.kind === 'sheet' ? sheetCrop(layer.sequence, seconds, sourceWidth, sourceHeight) : undefined
  const sourceRatio = (crop?.width ?? sourceWidth) / Math.max(1, crop?.height ?? sourceHeight)
  const { drawWidth, drawHeight } = fittedSize(layer.fill, sourceRatio, width / Math.max(1, height), width, height)
  context.beginPath()
  context.rect(-width / 2, -height / 2, width, height)
  context.clip()
  if (crop) context.drawImage(media, crop.x, crop.y, crop.width, crop.height, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight)
  else context.drawImage(media, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight)
}

/** Paint one frame at scene progress [0, 1]. Returns false without a 2D context. */
export function paintScene2D(canvas: HTMLCanvasElement, current: AnimatorScene, progress: number, evaluator: SceneEvaluator, lookup: SceneMediaLookup): boolean {
  const { renderedLayerStates, seamCoverStates } = evaluator
  const sceneProgress = Math.max(0, Math.min(1, progress))
  const sceneSeconds = sceneProgress * current.duration
  const context = canvas.getContext('2d')
  if (!context) return false
  context.fillStyle = '#0b1020'; context.fillRect(0, 0, canvas.width, canvas.height)
  current.layers
    .filter((layer): layer is VisualAnimatorLayer => layer.visible && isVisualLayer(layer))
    .flatMap(layer => renderedLayerStates(layer, sceneProgress).map((state, instanceIndex) => ({ layer, state, instanceIndex })))
    .sort((a, b) => a.state.z - b.state.z)
    .forEach(({ layer, state, instanceIndex }) => {
    const effects = normalizedEffects(layer.effects)
    context.save(); context.globalAlpha = state.opacity
    context.globalCompositeOperation = effects.blendMode === 'normal' ? 'source-over' : effects.blendMode
    if ('filter' in context) context.filter = effectFilter(effects, Math.min(canvas.width, canvas.height) / 100)
    const width = canvas.width * (layer.type === 'model3d' ? .52 : 1) * state.scale
    const height = canvas.height * (layer.type === 'model3d' ? .75 : 1) * state.scale
    context.translate(canvas.width * state.x / 100, canvas.height * state.y / 100); context.rotate(state.rotation * Math.PI / 180)
    applyLayerMask(context, effects, width, height)
    if (layer.type === 'effect') {
      drawAtmosphere(context, normalizedAtmosphere(layer.atmosphere), sceneSeconds, width, height, effectAnchor(current, layer, evaluator, sceneProgress))
    } else if (layer.type === 'model3d') {
      const viewer = lookup(layer, instanceIndex)
      if (viewer) context.drawImage(viewer, -width / 2, -height / 2, width, height)
    } else {
      const media = lookup(layer, instanceIndex)
      if (media && mediaReady(media)) drawLayerImage(context, layer, media, width, height, sceneSeconds)
    }
    context.restore()
  })
  current.layers
    .filter(layer => layer.visible && isVisualLayer(layer) && normalizedStrip(layer.strip).seamOccluder.enabled)
    .forEach(layer => {
      const kind = normalizedStrip(layer.strip).seamOccluder.kind
      seamCoverStates(layer, sceneProgress).forEach(state => {
        context.save()
        context.globalAlpha = state.opacity
        context.translate(canvas.width * state.x / 100, canvas.height * state.y / 100)
        context.rotate(state.rotation * Math.PI / 180)
        paintSeamOccluder(context, kind, canvas.width, canvas.height, normalizedStrip(layer.strip).seamOccluder.scale)
        context.restore()
      })
    })
  paintSceneFx(context, canvas.width, canvas.height, sceneSeconds, current.sfx)
  const envelope = beatEnvelope(current.rhythm, sceneSeconds)
  if (!current.finish?.applyToTexts) paintSceneFinish(context, canvas.width, canvas.height, sceneSeconds, current.finish, envelope, current.layers, current.duration)
  paintKineticTexts(context, canvas.width, canvas.height, sceneSeconds, current.texts, envelope)
  paintSceneLyrics(context, canvas.width, canvas.height, sceneSeconds, current.lyrics, envelope)
  if (current.finish?.applyToTexts) paintSceneFinish(context, canvas.width, canvas.height, sceneSeconds, current.finish, envelope, current.layers, current.duration)
  return true
}
