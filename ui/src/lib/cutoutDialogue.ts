import type { Scene, SceneFaceBinding, SceneFaceBindingState, SceneKeyframe, SceneLayer } from '../types'

export type CutoutViseme = 'closed' | 'small' | 'wide' | 'round'

export type CutoutDialoguePlan = {
  start: number
  end: number
  visemes: Array<{ start: number; end: number; state: CutoutViseme }>
}

export type CutoutMouthLayers = {
  open?: SceneLayer
  closed?: SceneLayer
  small?: SceneLayer
  wide?: SceneLayer
  round?: SceneLayer
}

export type SceneDialogueBeat = NonNullable<Scene['dialogueBeats']>[number]

const layerLabel = (layer: SceneLayer) => `${layer.id} ${layer.name}`.toLocaleLowerCase()
const isMouthState = (layer: SceneLayer, state: CutoutViseme | 'open') => {
  const label = layerLabel(layer)
  return label.includes('mouth') && new RegExp(`(?:mouth[ _-]*${state}|${state}[ _-]*mouth)`, 'i').test(label)
}

const FACE_STATES: SceneFaceBindingState[] = ['closed', 'small', 'wide', 'round', 'blink']

/** Parse the additive facial metadata while keeping malformed imported data inert. */
export function normalizeFaceBinding(value: unknown): SceneFaceBinding | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as Record<string, unknown>
  const poseLayerId = typeof raw.poseLayerId === 'string' ? raw.poseLayerId.trim() : ''
  const role = raw.role === 'mouth' || raw.role === 'blink' ? raw.role : undefined
  const state = FACE_STATES.includes(raw.state as SceneFaceBindingState) ? raw.state as SceneFaceBindingState : undefined
  if (!poseLayerId || !role) return undefined
  return { poseLayerId, role, ...(state ? { state } : {}) }
}

const bindingState = (layer: SceneLayer, state: CutoutViseme | 'open') =>
  layer.faceBinding?.role === 'mouth' && (state === 'open'
    ? ['small', 'wide', 'round'].includes(layer.faceBinding.state ?? '')
    : layer.faceBinding.state === state)

const inferredFaceBinding = (layer: SceneLayer, poseLayerId: string): SceneFaceBinding => {
  const label = layerLabel(layer)
  if (label.includes('blink') || /(?:closed)[ _-]*(?:eye|eyes)|(?:eye|eyes)[ _-]*(?:closed)/i.test(label)) {
    return { poseLayerId, role: 'blink', state: 'blink' }
  }
  const state = (['closed', 'small', 'wide', 'round'] as const).find(candidate => isMouthState(layer, candidate))
    ?? (isMouthState(layer, 'open') ? 'wide' : undefined)
  return { poseLayerId, role: 'mouth', ...(state ? { state } : {}) }
}

export function findCutoutMouthLayers(layers: SceneLayer[], poseLayerId?: string): CutoutMouthLayers {
  const visual = layers.filter(layer => layer.type !== 'camera' && layer.type !== 'effect')
  const scoped = poseLayerId ? visual.filter(layer =>
    layer.faceBinding?.role === 'mouth' && layer.faceBinding.poseLayerId === poseLayerId
    || !layer.faceBinding && layer.relationship?.type === 'parent' && layer.relationship.targetLayerId === poseLayerId && isCutoutFaceLayer(layer)) : []
  // A semantic or legacy-parented kit is authoritative. Old single-character
  // scenes that have never been bound retain their global name-based fallback.
  const hasAssignedMouthKit = visual.some(layer => layer.faceBinding?.role === 'mouth'
    || !layer.faceBinding && layer.relationship?.type === 'parent' && isCutoutFaceLayer(layer))
  const candidates = scoped.length ? scoped : poseLayerId && hasAssignedMouthKit ? [] : visual
  const find = (state: CutoutViseme | 'open') => candidates.find(layer => bindingState(layer, state)) ?? candidates.find(layer => isMouthState(layer, state))
  return { open: find('open'), closed: find('closed'), small: find('small'), wide: find('wide'), round: find('round') }
}

export function isCutoutFaceLayer(layer: SceneLayer): boolean {
  if (layer.faceBinding) return true
  const label = layerLabel(layer)
  return label.includes('mouth') || /(?:blink|closed)[ _-]*(?:eye|eyes)|(?:eye|eyes)[ _-]*(?:blink|closed)/i.test(label)
}

/**
 * Stores the current, pose-specific face placement by parenting ordinary face
 * overlays to the selected character layer.  The overlays keep their authored
 * scene coordinates; parent motion only adds the pose layer's later movement,
 * scale and rotation.  This deliberately reuses the persisted relationship
 * contract instead of adding a second rig format.
 */
export function bindCutoutFaceToPose(layers: SceneLayer[], poseLayerId: string): SceneLayer[] {
  const pose = layers.find(layer => layer.id === poseLayerId)
  if (!pose || pose.type === 'camera' || pose.type === 'effect' || isCutoutFaceLayer(pose)) return layers
  return layers.map(layer => {
    if (layer.id === pose.id || !isCutoutFaceLayer(layer)) return layer
    // A semantic binding to another pose is already assigned; never steal it.
    if (layer.faceBinding && layer.faceBinding.poseLayerId !== pose.id) return layer
    // Legacy scenes have no faceBinding. Treat a parent to another pose as
    // assigned too, while allowing an unparented legacy overlay to migrate.
    if (!layer.faceBinding && layer.relationship?.type === 'parent' && layer.relationship.targetLayerId !== pose.id) return layer
    const faceBinding = layer.faceBinding ?? inferredFaceBinding(layer, pose.id)
    return { ...layer, faceBinding, relationship: { type: 'parent', targetLayerId: pose.id } }
  })
}

const VOWEL = /[aeiouáéíóúäëïöü]/i
const ROUND_VOWEL = /[ouóúöü]/i
const visemeForGlyph = (glyph: string): CutoutViseme => /[.,;:!?—-]/.test(glyph) || !VOWEL.test(glyph)
  ? 'closed'
  : ROUND_VOWEL.test(glyph) ? 'round' : /[aeáé]/i.test(glyph) ? 'wide' : 'small'
const pointFor = (layer: SceneLayer, time: number, opacity: number): SceneKeyframe => {
  const reference = layer.animation.keyframes?.[0] ?? layer.animation.start
  return {
    id: `${layer.id}-dialogue-${Math.round(time * 1000)}`,
    time,
    x: reference.x,
    y: reference.y,
    scale: reference.scale,
    opacity,
    rotation: reference.rotation ?? 0,
    curve: 'hold',
  }
}

/**
 * Turns known dialogue into intentionally limited animation. This is not an
 * attempt at phoneme-perfect lipsync: it creates a readable held/snap rhythm
 * at a bounded cadence, so it remains coherent with paper-cutout characters.
 */
export function planCutoutDialogue(text: string, start: number, end: number, fps = 30): CutoutDialoguePlan {
  const safeStart = Math.max(0, start)
  const safeEnd = Math.max(safeStart + 1 / Math.max(1, fps), end)
  const glyphs = [...text.replace(/\s+/g, ' ').trim()]
  if (!glyphs.length) return { start: safeStart, end: safeEnd, visemes: [{ start: safeStart, end: safeEnd, state: 'closed' }] }
  const frame = 1 / Math.max(1, fps)
  const minHold = Math.max(frame * 2, .12)
  const available = safeEnd - safeStart
  const maxBeats = Math.max(2, Math.floor(available / minHold))
  const stride = Math.max(1, Math.ceil(glyphs.length / maxBeats))
  const glyphStates = glyphs.map(visemeForGlyph)
  const selectedIndexes = glyphs.flatMap((_, index) => index % stride === 0 || index === glyphs.length - 1 ? [index] : [])
  // Even sampling can accidentally skip every O/U or I sound in an otherwise
  // long line, making installed round/small sprites look broken. Preserve one
  // interior sample of each viseme that exists in the text when cadence allows
  // it, preferably replacing an uninformative closed sample.
  for (const required of ['small', 'wide', 'round'] as const) {
    if (selectedIndexes.slice(1, -1).some(index => glyphStates[index] === required)) continue
    const candidate = glyphStates.findIndex((state, index) => state === required && index > 0 && index < glyphs.length - 1)
    if (candidate < 0) continue
    const replacement = selectedIndexes.findIndex((index, position) => position > 0 && position < selectedIndexes.length - 1 && glyphStates[index] === 'closed')
    if (replacement >= 0) selectedIndexes[replacement] = candidate
    else if (selectedIndexes.length < maxBeats) selectedIndexes.push(candidate)
  }
  selectedIndexes.sort((a, b) => a - b)
  const beats = [...new Set(selectedIndexes)].map(index => glyphs[index])
  const interval = available / Math.max(1, beats.length)
  const visemes = beats.map((glyph, index) => {
    const beatStart = safeStart + interval * index
    const beatEnd = index === beats.length - 1 ? safeEnd : Math.max(beatStart + frame, safeStart + interval * (index + 1))
    const state = visemeForGlyph(glyph)
    return { start: beatStart, end: beatEnd, state }
  })
  // First and last frames should always settle on a closed mouth so a cut into
  // or out of the shot does not freeze on an arbitrary open shape.
  visemes[0] = { ...visemes[0], state: 'closed' }
  visemes[visemes.length - 1] = { ...visemes[visemes.length - 1], state: 'closed' }
  // Word-aligned transcription commonly supplies very short units ("la",
  // "de", "sí"). A two-beat unit would otherwise become closed/closed
  // after the edge guard. Preserve one readable centre pulse whenever the
  // word has a vowel; its terminal closed keyframe still protects edits/cuts.
  if (!visemes.some(beat => beat.state !== 'closed') && glyphs.some(glyph => VOWEL.test(glyph)) && available >= frame * 3) {
    const middle = safeStart + available / 2
    return {
      start: safeStart,
      end: safeEnd,
      visemes: [
        { start: safeStart, end: middle, state: 'closed' },
        { start: middle, end: safeEnd, state: ROUND_VOWEL.test(glyphs.join('')) ? 'round' : 'wide' },
        { start: safeEnd, end: safeEnd, state: 'closed' },
      ],
    }
  }
  return { start: safeStart, end: safeEnd, visemes }
}

/** Recompile edited beat records into ordinary mouth opacity keyframes.
 * `clearLayerIds` removes stale frames from a previous speaker/beat assignment
 * while leaving unrelated animation tracks untouched. */
export function rebuildCutoutDialogueLayers(
  layers: SceneLayer[],
  beats: SceneDialogueBeat[],
  fps: number,
  duration: number,
  clearLayerIds: string[] = [],
): SceneLayer[] {
  const layerById = new Map(layers.map(layer => [layer.id, layer]))
  const framesByLayer = new Map<string, SceneKeyframe[]>()
  const affected = new Set(clearLayerIds)
  for (const beat of beats) {
    const targets = beat.mouthLayerIds.flatMap(id => layerById.get(id) ? [layerById.get(id)!] : [])
    if (!targets.length) continue
    const mouthLayers = findCutoutMouthLayers(targets)
    if (!(mouthLayers.open ?? mouthLayers.small ?? mouthLayers.wide ?? mouthLayers.round)) continue
    const start = Math.max(0, Math.min(duration, beat.start))
    if (start >= duration) continue
    const end = Math.max(start + 1 / Math.max(1, fps), Math.min(duration, beat.end))
    const generated = applyCutoutDialogue(mouthLayers, planCutoutDialogue(beat.text, start, end, fps))
    for (const [layerId, frames] of Object.entries(generated)) {
      affected.add(layerId)
      framesByLayer.set(layerId, [...(framesByLayer.get(layerId) ?? []), ...frames])
    }
  }
  return layers.map(layer => {
    if (!affected.has(layer.id)) return layer
    const frames = framesByLayer.get(layer.id) ?? []
    const byTime = new Map<number, SceneKeyframe>()
    for (const frame of frames) byTime.set(Math.round(frame.time * 1_000_000), frame)
    const keyframes = [...byTime.values()].sort((a, b) => a.time - b.time)
    return { ...layer, animation: { ...layer.animation, keyframes: keyframes.length ? keyframes : undefined, duration, curve: 'hold' } }
  })
}

export function applyCutoutDialogue(layers: CutoutMouthLayers, plan: CutoutDialoguePlan): Record<string, SceneKeyframe[]> {
  const speakingFallback = layers.open ?? layers.wide ?? layers.small ?? layers.round
  if (!speakingFallback) return {}
  const participants = [...new Set(Object.values(layers).filter((layer): layer is SceneLayer => Boolean(layer)))]
  const framesByLayer = Object.fromEntries(participants.map(layer => [layer.id, [] as SceneKeyframe[]]))
  for (const beat of plan.visemes) {
    const active = beat.state === 'closed' ? layers.closed : layers[beat.state] ?? speakingFallback
    for (const layer of participants) framesByLayer[layer.id].push(pointFor(layer, beat.start, Number(layer === active)))
  }
  // Keyframe arrays need a terminal pose even when the final beat began before
  // the requested end, otherwise an imported scene may normalize it away.
  const last = plan.visemes.at(-1)
  if (!last || last.start < plan.end) {
    for (const layer of participants) framesByLayer[layer.id].push(pointFor(layer, plan.end, Number(layer === layers.closed)))
  }
  return framesByLayer
}
