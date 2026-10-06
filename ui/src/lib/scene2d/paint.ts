// Pure Video 2D frame painter shared by the Scene Animator export and the
// headless scene2d renderer. Media lookup is injected so the same drawing code
// works with live DOM elements (editor) or preloaded images/videos (headless).
import { paintSceneFx, type FxLayerPoint } from '../../features/sceneFx/paint'
import { paintKineticTexts, paintSceneLyrics, type TextInkTrap } from '../kineticText'
import { paintSceneFinish } from './finish'
import { coverDrawState } from './cover'
import { beatEnvelope, sheetCrop } from './motion'
import { paintSeamOccluder } from '../seamOccluder'
import type { SceneEvaluator } from './evaluate'
import { applyLayerMask, drawAtmosphere, effectFilter, isVisualLayer, normalizedAtmosphere, normalizedEffects, normalizedStrip } from './layerStyle'
import type { AnimatorScene, LayerState, VisualAnimatorLayer } from './types'

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

function sourceFrame(layer: VisualAnimatorLayer, media: SceneMedia, seconds: number): [number, number] {
  const [sourceWidth, sourceHeight] = mediaSize(media)
  const crop = layer.sequence?.kind === 'sheet' ? sheetCrop(layer.sequence, seconds, sourceWidth, sourceHeight) : undefined
  return [crop?.width ?? sourceWidth, crop?.height ?? sourceHeight]
}

function layerMedia(layer: VisualAnimatorLayer, instanceIndex: number, lookup: SceneMediaLookup): SceneMedia | null {
  return layer.type === 'effect' ? null : lookup(layer, instanceIndex)
}

function drawState(canvas: { width: number; height: number }, layer: VisualAnimatorLayer, state: LayerState, media: SceneMedia | null, seconds: number): LayerState {
  if (layer.cover !== true || !media || !mediaReady(media) || layer.type === 'model3d') return state
  const [sourceWidth, sourceHeight] = sourceFrame(layer, media, seconds)
  return coverDrawState(canvas.width, canvas.height, sourceWidth, sourceHeight, layer.fill, layer.focus, state)
}

/** A point given in % of a layer's picture, in frame % as the layer is drawn at this moment: its
 * motion, the camera, the fit of its picture in its box (contain, fill or cover) and its rotation.
 * A layer whose picture is not loaded yet is taken as filling its box. */
export function layerPicturePoint(canvas: { width: number; height: number }, current: AnimatorScene, evaluator: SceneEvaluator, lookup: SceneMediaLookup,
  progress: number, seconds: number): FxLayerPoint {
  return (layerId, x, y) => {
    const layer = current.layers.find(item => item.id === layerId)
    if (!layer || !layer.visible || !isVisualLayer(layer) || layer.type === 'effect') return null
    const state = evaluator.renderedLayerStates(layer, progress)[0]
    if (!state) return null
    const media = layerMedia(layer, 0, lookup)
    const draw = drawState(canvas, layer, state, media, seconds)
    const model = layer.type === 'model3d'
    const boxWidth = canvas.width * (model ? .52 : 1) * draw.scale, boxHeight = canvas.height * (model ? .75 : 1) * draw.scale
    const [sourceWidth, sourceHeight] = media && mediaReady(media) && !model ? sourceFrame(layer, media, seconds) : [boxWidth, boxHeight]
    const { drawWidth, drawHeight } = fittedSize(layer.fill, sourceWidth / Math.max(1, sourceHeight), boxWidth / Math.max(1, boxHeight), boxWidth, boxHeight)
    const dx = (x / 100 - .5) * drawWidth, dy = (y / 100 - .5) * drawHeight, angle = draw.rotation * Math.PI / 180
    return { x: draw.x + (dx * Math.cos(angle) - dy * Math.sin(angle)) / canvas.width * 100,
      y: draw.y + (dx * Math.sin(angle) + dy * Math.cos(angle)) / canvas.height * 100 }
  }
}

function textInk(finish: AnimatorScene['finish']): TextInkTrap | undefined {
  if (!finish?.riso) return undefined
  return { riso: true, paper: finish.riso.paper }
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
    const media = layerMedia(layer, instanceIndex, lookup)
    const draw = drawState(canvas, layer, state, media, sceneSeconds)
    context.save(); context.globalAlpha = draw.opacity
    context.globalCompositeOperation = effects.blendMode === 'normal' ? 'source-over' : effects.blendMode
    if ('filter' in context) context.filter = effectFilter(effects, Math.min(canvas.width, canvas.height) / 100)
    const width = canvas.width * (layer.type === 'model3d' ? .52 : 1) * draw.scale
    const height = canvas.height * (layer.type === 'model3d' ? .75 : 1) * draw.scale
    context.translate(canvas.width * draw.x / 100, canvas.height * draw.y / 100); context.rotate(draw.rotation * Math.PI / 180)
    applyLayerMask(context, effects, width, height)
    if (layer.type === 'effect') {
      drawAtmosphere(context, normalizedAtmosphere(layer.atmosphere), sceneSeconds, width, height, effectAnchor(current, layer, evaluator, sceneProgress))
    } else if (layer.type === 'model3d') {
      if (media) context.drawImage(media, -width / 2, -height / 2, width, height)
    } else if (media && mediaReady(media)) drawLayerImage(context, layer, media, width, height, sceneSeconds)
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
  paintSceneFx(context, canvas.width, canvas.height, sceneSeconds, current.sfx, undefined,
    layerPicturePoint(canvas, current, evaluator, lookup, sceneProgress, sceneSeconds))
  const envelope = beatEnvelope(current.rhythm, sceneSeconds)
  if (!current.finish?.applyToTexts) paintSceneFinish(context, canvas.width, canvas.height, sceneSeconds, current.finish, envelope, current.layers, current.duration)
  paintKineticTexts(context, canvas.width, canvas.height, sceneSeconds, current.texts, envelope, textInk(current.finish))
  paintSceneLyrics(context, canvas.width, canvas.height, sceneSeconds, current.lyrics, envelope)
  if (current.finish?.applyToTexts) paintSceneFinish(context, canvas.width, canvas.height, sceneSeconds, current.finish, envelope, current.layers, current.duration)
  return true
}
