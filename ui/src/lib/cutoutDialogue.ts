import type { Scene, SceneFaceBinding, SceneFaceBindingState, SceneKeyframe, SceneLayer } from '../types'
import { CHARACTER_MOUTH_STATES, MOUTH_STATE_FALLBACK, type CharacterMouthState } from './characterMouthStates'
import { planPhoneticCutoutDialogue } from './cutoutPhonetic'

export type CutoutViseme = CharacterMouthState

export type CutoutDialoguePlan = {
  start: number
  end: number
  visemes: Array<{ start: number; end: number; state: CutoutViseme }>
}

export type CutoutMouthLayers = Partial<Record<CutoutViseme | 'open', SceneLayer>>

export type SceneDialogueBeat = NonNullable<Scene['dialogueBeats']>[number]

const layerLabel = (layer: SceneLayer) => `${layer.id} ${layer.name}`.toLocaleLowerCase()
const isMouthState = (layer: SceneLayer, state: CutoutViseme | 'open') => {
  const label = layerLabel(layer)
  return label.includes('mouth') && new RegExp(`(?:mouth[ _-]*${state}|${state}[ _-]*mouth)`, 'i').test(label)
}

const FACE_STATES: SceneFaceBindingState[] = [...CHARACTER_MOUTH_STATES, 'blink', 'open']

/** Parse the additive facial metadata while keeping malformed imported data inert. */
export function normalizeFaceBinding(value: unknown): SceneFaceBinding | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as Record<string, unknown>
  const poseLayerId = typeof raw.poseLayerId === 'string' ? raw.poseLayerId.trim() : ''
  const role = raw.role === 'mouth' || raw.role === 'blink' || raw.role === 'eyes' ? raw.role : undefined
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
  return { open: find('open'), ...Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, find(state)])) }
}

export function isCutoutFaceLayer(layer: SceneLayer): boolean {
  if (layer.faceBinding) return true
  const label = layerLabel(layer)
  return label.includes('mouth') || label.includes('eyes') || /(?:blink|closed)[ _-]*(?:eye|eyes)|(?:eye|eyes)[ _-]*(?:blink|closed|open)/i.test(label)
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

const VOWEL = /[aeiouyáéíóúäëïöü]/i
const ROUND_VOWEL = /[ouóúöüw]/i
const visemeForGlyph = (glyph: string): CutoutViseme => /[.,;:!?—-]/.test(glyph) || !VOWEL.test(glyph)
  ? 'closed'
  : ROUND_VOWEL.test(glyph) ? 'round' : /[aeáé]/i.test(glyph) ? 'wide' : 'small'

/** Dominant spoken mouth for a whole word (ES + EN). Closed is silence, not a consonant. */
export function visemeForToken(text: string): CutoutViseme {
  const folded = text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
  const letters = [...folded].filter(ch => /[a-z]/.test(ch))
  const classes: CutoutViseme[] = []
  for (let index = 0; index < letters.length; index += 1) {
    const ch = letters[index]
    const next = letters[index + 1]
    if ((ch === 'e' && next === 'e') || (ch === 'e' && next === 'a') || (ch === 'i' && next === 'e')) {
      classes.push('small')
      index += 1
      continue
    }
    if ((ch === 'o' && next === 'o') || (ch === 'o' && next === 'u') || (ch === 'o' && next === 'w')) {
      classes.push('round')
      index += 1
      continue
    }
    if (ch === 'o' || ch === 'u' || ch === 'w') classes.push('round')
    else if (ch === 'i' || ch === 'y') classes.push('small')
    else if (ch === 'a' || ch === 'e') classes.push('wide')
  }
  if (!classes.length) return 'small'
  return classes[classes.length - 1]
}
const pointFor = (layer: SceneLayer, time: number, opacity: number): SceneKeyframe => {
  const authored = layer.animation?.start
  const transform = layer.transform
  return {
    id: `${layer.id}-dialogue-${Math.round(time * 1000)}`,
    time,
    x: Number.isFinite(transform?.x) ? transform.x : authored?.x ?? 50,
    y: Number.isFinite(transform?.y) ? transform.y : authored?.y ?? 50,
    scale: Number.isFinite(transform?.scale) ? transform.scale : authored?.scale ?? 1,
    opacity,
    rotation: Number.isFinite(transform?.rotation) ? transform.rotation ?? 0 : authored?.rotation ?? 0,
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
  // Whisper word units are often 120–280 ms. Letter sampling + closed bookends
  // would leave "la" / "the" / "un" shut for half the word. One-frame edges,
  // open viseme from the token (Spanish and English vowels, including y).
  if (available <= minHold * 2.5) {
    const edge = Math.min(frame, available / 6)
    const spoken = visemeForToken(glyphs.join(''))
    const openState = spoken === 'closed' ? 'small' : spoken
    return {
      start: safeStart,
      end: safeEnd,
      visemes: [
        { start: safeStart, end: safeStart + edge, state: 'closed' },
        { start: safeStart + edge, end: Math.max(safeStart + edge, safeEnd - edge), state: openState },
        { start: Math.max(safeStart + edge, safeEnd - edge), end: safeEnd, state: 'closed' },
      ],
    }
  }
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
    const edge = Math.min(frame, available / 6)
    const spoken = visemeForToken(glyphs.join(''))
    return {
      start: safeStart,
      end: safeEnd,
      visemes: [
        { start: safeStart, end: safeStart + edge, state: 'closed' },
        { start: safeStart + edge, end: safeEnd - edge, state: spoken === 'closed' ? 'small' : spoken },
        { start: safeEnd - edge, end: safeEnd, state: 'closed' },
      ],
    }
  }
  return { start: safeStart, end: safeEnd, visemes }
}

export type AlignedCutoutUnit = { text: string; start: number; end: number }

/** Keep source text literal and map only usable speech onto the scene clock. */
export function normalizeAlignedCutoutUnits(
  units: AlignedCutoutUnit[], offset = 0, duration = Infinity,
): AlignedCutoutUnit[] {
  return units.flatMap(unit => {
    if (typeof unit.text !== 'string' || !unit.text.trim()
      || !Number.isFinite(unit.start) || !Number.isFinite(unit.end)) return []
    const start = Math.max(0, unit.start + offset)
    const end = Math.min(duration, unit.end + offset)
    return end > start ? [{ text: unit.text, start, end }] : []
  }).sort((a, b) => a.start - b.start || a.end - b.end)
}

/** Word times from Hocus audio analysis: closed in gaps, one viseme per spoken word. */
export function planAlignedCutoutDialogue(
  units: AlignedCutoutUnit[],
  fps = 30,
): CutoutDialoguePlan {
  const usable = normalizeAlignedCutoutUnits(units)
  if (!usable.length) return { start: 0, end: 1 / Math.max(1, fps), visemes: [{ start: 0, end: 1 / Math.max(1, fps), state: 'closed' }] }
  const start = usable[0].start
  const end = usable[usable.length - 1].end
  // Rest closed must occupy a distinct time before the first spoken viseme.
  // A zero-length closed at `start` shares a timestamp with the first word;
  // rebuild keeps the later (open) frame, so evaluateSceneLayer holds that
  // open mouth from t=0 until speech begins.
  const visemes: CutoutDialoguePlan['visemes'] = start > 0
    ? [{ start: 0, end: start, state: 'closed' }]
    : []
  let cursor = start
  for (const [index, unit] of usable.entries()) {
    const unitStart = unit.start
    const unitEnd = Math.min(unit.end, usable[index + 1]?.start ?? unit.end)
    if (unitEnd <= unitStart) continue
    if (unitStart > cursor) visemes.push({ start: cursor, end: unitStart, state: 'closed' })
    const spoken = visemeForToken(unit.text)
    visemes.push({ start: unitStart, end: unitEnd, state: spoken === 'closed' ? 'small' : spoken })
    cursor = unitEnd
  }
  visemes.push({ start: cursor, end: Math.max(cursor, end), state: 'closed' })
  return { start, end, visemes }
}

function groupCutoutDialogueBeats(beats: SceneDialogueBeat[]): SceneDialogueBeat[][] {
  const groups: SceneDialogueBeat[][] = []
  for (const beat of beats) {
    const last = groups.at(-1)
    const sameMouths = last && last[0].mouthLayerIds.join('\0') === beat.mouthLayerIds.join('\0')
    const alignedRun = !beat.lipSync && !last?.[0].lipSync && beat.confidence === 'aligned-audio' && last?.[0].confidence === 'aligned-audio'
    if (sameMouths && alignedRun) last.push(beat)
    else groups.push([beat])
  }
  return groups
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
  const groups = groupCutoutDialogueBeats(beats)
  for (const group of groups) {
    const targets = group[0].mouthLayerIds.flatMap(id => layerById.get(id) ? [layerById.get(id)!] : [])
    if (!targets.length) continue
    const mouthLayers = findCutoutMouthLayers(targets)
    if (!(mouthLayers.open ?? mouthLayers.small ?? mouthLayers.wide ?? mouthLayers.round)) continue
    const units = normalizeAlignedCutoutUnits(group, 0, duration)
    if (!units.length) continue
    const plan = planPhoneticCutoutDialogue(group[0], duration) ?? (group[0].confidence === 'aligned-audio' && !group[0].lipSync
      ? planAlignedCutoutDialogue(units, fps)
      : planCutoutDialogue(
        group[0].text,
        Math.max(0, Math.min(duration, group[0].start)),
        Math.max(group[0].start + 1 / Math.max(1, fps), Math.min(duration, group[0].end)),
        fps,
      ))
    if (plan.start >= duration) continue
    const generated = applyCutoutDialogue(mouthLayers, plan)
    for (const [layerId, frames] of Object.entries(generated)) {
      affected.add(layerId)
      const previous = framesByLayer.get(layerId) ?? []
      // A later turn's leading rest must not replace speech already at t=0.
      const appended = previous.length && plan.start > 0 ? frames.filter(frame => frame.time > 0) : frames
      framesByLayer.set(layerId, [...previous, ...appended])
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
    const fallback = MOUTH_STATE_FALLBACK[beat.state]
    const active = layers[beat.state] ?? (fallback === 'closed' ? layers.closed : layers[fallback] ?? speakingFallback)
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

const facePoint = (layer: SceneLayer, time: number, opacity: number): SceneKeyframe => pointFor(layer, time, opacity)

const layerChangesOpacity = (layer: SceneLayer) => {
  const frames = layer.animation?.keyframes ?? []
  if (frames.length < 2) return false
  const values = [layer.transform.opacity ?? 1, ...frames.map(frame => frame.opacity ?? 1)]
  return Math.max(...values) - Math.min(...values) > .2
}

function idleBlinkKeyframes(layer: SceneLayer, duration: number, visibleAtRest: boolean): SceneKeyframe[] {
  const frames = [facePoint(layer, 0, visibleAtRest ? 1 : 0)]
  const interval = 2.4
  const closed = .12
  for (let time = interval; time < duration - .25; time += interval) {
    frames.push(facePoint(layer, time, visibleAtRest ? 1 : 0))
    frames.push(facePoint(layer, time + .001, visibleAtRest ? 0 : 1))
    frames.push(facePoint(layer, Math.min(duration, time + closed), visibleAtRest ? 0 : 1))
    frames.push(facePoint(layer, Math.min(duration, time + closed + .001), visibleAtRest ? 1 : 0))
  }
  frames.push(facePoint(layer, duration, visibleAtRest ? 1 : 0))
  return frames
}

/** Make Play/Export actually flap mouths and blink when the kit is only at rest. */
export function ensureCutoutFacePlayback(
  layers: SceneLayer[],
  duration: number,
  fps = 30,
  dialogueBeats: SceneDialogueBeat[] = [],
  spokenLine = '',
): SceneLayer[] {
  const mouths = layers.filter(layer => layer.faceBinding?.role === 'mouth')
  const blinks = layers.filter(layer => layer.faceBinding?.role === 'blink')
  const openEyes = layers.filter(layer => layer.faceBinding?.role === 'eyes' && layer.faceBinding.state === 'open')
  if (!mouths.length && !blinks.length && !openEyes.length) return layers
  let next = layers
  if (mouths.length >= 2 && !mouths.some(layerChangesOpacity)) {
    if (dialogueBeats.length) {
      next = rebuildCutoutDialogueLayers(next, dialogueBeats, fps, duration)
    } else if (spokenLine.trim()) {
      // An idle character is not evidence of speech. Only an explicitly
      // authored line may create talking keyframes; silent shots stay silent.
      const line = spokenLine.trim()
      const plan = planCutoutDialogue(line, .2, Math.max(1.4, duration - .2), fps)
      const frames = applyCutoutDialogue(findCutoutMouthLayers(next), plan)
      next = next.map(layer => frames[layer.id]
        ? { ...layer, animation: { ...layer.animation, keyframes: frames[layer.id], duration, curve: 'hold' } }
        : layer)
    }
  }
  if (blinks.length && !blinks.some(layerChangesOpacity)) {
    next = next.map(layer => {
      if (layer.faceBinding?.role === 'blink') {
        return { ...layer, animation: { ...layer.animation, keyframes: idleBlinkKeyframes(layer, duration, false), duration, curve: 'hold' } }
      }
      if (layer.faceBinding?.role === 'eyes' && layer.faceBinding.state === 'open') {
        return { ...layer, animation: { ...layer.animation, keyframes: idleBlinkKeyframes(layer, duration, true), duration, curve: 'hold' } }
      }
      return layer
    })
  } else if (openEyes.length && !openEyes.some(layerChangesOpacity) && blinks.some(layerChangesOpacity)) {
    next = next.map(layer => layer.faceBinding?.role === 'eyes' && layer.faceBinding.state === 'open'
      ? { ...layer, animation: { ...layer.animation, keyframes: idleBlinkKeyframes(layer, duration, true), duration, curve: 'hold' } }
      : layer)
  }
  return next
}
