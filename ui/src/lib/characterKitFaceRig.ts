import { planCutoutDialogue } from './cutoutDialogue'
import {
  DEFAULT_CHARACTER_BLINK_ANCHOR,
  DEFAULT_CHARACTER_MOUTH_ANCHOR,
  type CharacterFaceAnchor,
  type CharacterKit,
  type CharacterKitAsset,
  type CharacterKitReviewState,
  type CharacterMouthState,
} from './characterKit'

export const CHARACTER_FACE_RIG_STATES = ['closed', 'small', 'wide', 'round', 'blink'] as const
export type CharacterKitFaceRigState = typeof CHARACTER_FACE_RIG_STATES[number]

export interface FaceRigGenerationRequest {
  state: CharacterKitFaceRigState
  prompt: string
  poseId: string
  reference: string
}

export interface FaceRigValidation {
  poseId: string
  pose: CharacterKitAsset
}

export interface CharacterKitAlphaMetrics {
  pixelCount: number
  transparentRatio: number
  translucentRatio: number
  opaqueRatio: number
  status: 'transparent' | 'opaque' | 'unknown'
}

export interface FaceRigProvenance {
  method: 'character-kit-face-rig'
  state: CharacterKitFaceRigState
  poseId: string
  reference: string
  prompt: string
  [key: string]: unknown
}

const MOUTH_STATES = new Set<CharacterMouthState>(['closed', 'small', 'wide', 'round'])
const MATERIAL_ALPHA_RATIO = .01
export const DEFAULT_FACE_RIG_ANCHOR: CharacterFaceAnchor = DEFAULT_CHARACTER_MOUTH_ANCHOR
export const DEFAULT_FACE_RIG_BLINK_ANCHOR: CharacterFaceAnchor = DEFAULT_CHARACTER_BLINK_ANCHOR

export const FACE_RIG_STYLE_PRESETS = [
  { id: 'paper-cut', label: 'Recorte de papel', prompt: 'flat paper-cut collage, torn paper edges, thick uneven black outline, layered construction paper' },
  { id: 'plasticine', label: 'Plastilina', prompt: 'hand-sculpted plasticine clay, visible fingerprints, matte clay material, stop-motion puppet' },
  { id: 'cartoon', label: 'Cartoon', prompt: 'bold cartoon, clean cel shading, thick ink outline, simple graphic shapes' },
  { id: 'watercolor', label: 'Acuarela', prompt: 'soft watercolor illustration, paper grain, gentle pigment bleeds, children\'s book' },
  { id: 'comic-ink', label: 'Tinta cómic', prompt: 'high-contrast comic-book ink, halftone dots, graphic novel linework' },
  { id: 'felt-puppet', label: 'Títere de fieltro', prompt: 'felt puppet, stitched edges, wool texture, handmade craft' },
  { id: 'limited-anime', label: 'Anime limitado', prompt: 'limited-animation anime, flat color fills, simple shapes, 2D TV cutout' },
  { id: 'children-illustration', label: 'Ilustración infantil', prompt: 'children\'s picture-book illustration, friendly proportions, soft lighting' },
] as const

export const FACE_RIG_TRAIT_CHIPS = [
  'afro hair',
  'braids',
  'pigtails',
  'beanie',
  'round glasses',
  'goggles',
  'freckles',
  'dark skin',
  'pale skin',
  'winter coat',
  'school uniform',
] as const

export function composeCharacterKitLook(parts: { name?: string; stylePrompt?: string; traits?: string; extra?: string }): string {
  return [parts.name, parts.traits, parts.stylePrompt, parts.extra]
    .map(part => String(part || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(', ')
}

/** Classify an RGBA buffer without guessing when its shape/content is invalid. */
export function classifyCharacterKitAlpha(rgba: Uint8ClampedArray): CharacterKitAlphaMetrics {
  const invalid = { pixelCount: 0, transparentRatio: 0, translucentRatio: 0, opaqueRatio: 0, status: 'unknown' as const }
  if (!(rgba instanceof Uint8ClampedArray) || rgba.length === 0 || rgba.length % 4 !== 0) return invalid
  let transparent = 0
  let translucent = 0
  let opaque = 0
  for (let index = 3; index < rgba.length; index += 4) {
    const alpha = rgba[index]
    if (alpha < 250) {
      transparent++
      if (alpha > 0) translucent++
    }
    if (alpha === 255) opaque++
  }
  const pixelCount = rgba.length / 4
  const transparentRatio = transparent / pixelCount
  const translucentRatio = translucent / pixelCount
  const opaqueRatio = opaque / pixelCount
  return {
    pixelCount,
    transparentRatio,
    translucentRatio,
    opaqueRatio,
    status: transparentRatio >= MATERIAL_ALPHA_RATIO ? 'transparent' : opaqueRatio >= 0.99 ? 'opaque' : 'unknown',
  }
}

function poseFor(kit: CharacterKit, poseId: string): CharacterKitAsset | undefined {
  return poseId === 'base' ? kit.base : kit.poses[poseId]
}

/** Require a reviewed, durable pose before Face Rig generation can use it. */
export function validateFaceRigPose(kit: CharacterKit, poseId = 'base'): FaceRigValidation {
  const normalizedPoseId = poseId.trim() || 'base'
  const pose = poseFor(kit, normalizedPoseId)
  if (!pose) throw new Error(`Character Kit “${kit.name}” has no ${normalizedPoseId} pose.`)
  if (pose.reviewState !== 'approved') throw new Error(`Review and approve ${pose.name} before generating Face Rig states.`)
  if (!pose.source || pose.source.startsWith('blob:')) throw new Error('Face Rig requires a persistent pose source.')
  return { poseId: normalizedPoseId, pose }
}

/** Full-body puppet prompt. The user only supplies style and traits. */
export function characterKitPosePrompt(kit: CharacterKit, description = ''): string {
  const identity = description.trim() || kit.lookNotes?.trim() || `${kit.name} character`
  return `Generate a full-body standing character cutout of ${identity}; one reusable puppet, feet planted, facing camera; transparent PNG/WebP, tightly cropped to the character, no background, no ground shadow, no text, no extra characters, no turnaround sheet, no collage of views.`
}

/** Keep prompts identity-focused; the user only fills style and traits. */
export function faceRigPrompt(kit: CharacterKit, state: CharacterKitFaceRigState, description = ''): string {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const identity = description.trim() || kit.lookNotes?.trim() || `${kit.name} character`
  const expression = state === 'blink'
    ? 'an eyes overlay sprite with closed eyelids only'
    : `a ${state} mouth overlay sprite only`
  return `Generate ONLY ${expression} for ${identity}; use the pose as identity and art-style reference; preserve the facial proportions and colors; isolated transparent PNG/WebP overlay, tightly cropped to the facial piece, aligned to the reference; no full character, no head, no body, no skin rectangle, no background, no text, no glow, no shadow, no extra objects.`
}

export function faceRigGenerationRequests(kit: CharacterKit, poseId = 'base', description = ''): FaceRigGenerationRequest[] {
  const { poseId: normalizedPoseId, pose } = validateFaceRigPose(kit, poseId)
  return CHARACTER_FACE_RIG_STATES.map(state => ({
    state,
    prompt: faceRigPrompt(kit, state, description),
    poseId: normalizedPoseId,
    reference: pose.source,
  }))
}

function assetForState(kit: CharacterKit, state: CharacterKitFaceRigState): CharacterKitAsset | undefined {
  return MOUTH_STATES.has(state as CharacterMouthState)
    ? kit.mouth[state as CharacterMouthState]
    : kit.eyes.blink
}

/** Return a new kit with one generated state attached as pending and provenance recorded. */
export function registerGeneratedFaceRigAsset(
  kit: CharacterKit,
  state: CharacterKitFaceRigState,
  asset: CharacterKitAsset,
  provenance: Pick<FaceRigProvenance, 'poseId' | 'reference' | 'prompt'> & Record<string, unknown>,
): CharacterKit {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  if (!asset.source || asset.source.startsWith('blob:')) throw new Error('Generated Face Rig assets need a persistent source.')
  const nextAsset: CharacterKitAsset = { ...asset, reviewState: 'pending', kind: 'overlay' }
  const nextProvenance: FaceRigProvenance = { ...provenance, method: 'character-kit-face-rig', state }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: nextAsset } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: nextAsset } : kit.eyes,
    provenance: [...kit.provenance, nextProvenance],
    updatedAt: new Date().toISOString(),
  }
}

export interface FaceRigCleanupResult {
  source: string
  filename: string
  original: string
  width: number
  height: number
  alpha: CharacterKitAlphaMetrics
  method: string
  padding: number
  model?: string
}

/** Replace one overlay with a cleaned PNG while keeping it pending for review. */
export function registerCleanedFaceRigAsset(
  kit: CharacterKit,
  state: CharacterKitFaceRigState,
  cleaned: FaceRigCleanupResult,
): CharacterKit {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const current = assetForState(kit, state)
  if (!current) throw new Error(`Character Kit “${kit.name}” has no generated ${state} asset to clean.`)
  if (!cleaned.source || cleaned.source.startsWith('blob:')) throw new Error('Cleaned Face Rig assets need a persistent source.')
  const nextAsset: CharacterKitAsset = {
    ...current,
    source: cleaned.source,
    kind: 'overlay',
    alphaStatus: cleaned.alpha?.status ?? 'unknown',
    reviewState: 'pending',
  }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: nextAsset } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: nextAsset } : kit.eyes,
    provenance: [...kit.provenance, {
      method: 'character-kit-face-rig-cleanup',
      state,
      original: cleaned.original,
      source: cleaned.source,
      filename: cleaned.filename,
      cleanupMethod: cleaned.method,
      model: cleaned.model,
      padding: cleaned.padding,
      alphaMetrics: cleaned.alpha,
      width: cleaned.width,
      height: cleaned.height,
    }],
    updatedAt: new Date().toISOString(),
  }
}

export function normalizeFaceRigAnchor(value?: Partial<CharacterFaceAnchor> | null): CharacterFaceAnchor {
  const source = value && typeof value === 'object' ? value : {}
  const scale = Number(source.scale)
  return {
    offsetX: Number.isFinite(Number(source.offsetX)) ? Number(source.offsetX) : 0,
    offsetY: Number.isFinite(Number(source.offsetY)) ? Number(source.offsetY) : 0,
    scale: Number.isFinite(scale) && scale > 0 ? scale : DEFAULT_FACE_RIG_ANCHOR.scale,
    rotation: Number.isFinite(Number(source.rotation)) ? Number(source.rotation) : 0,
  }
}

/** Resolve the saved relative anchor for one Face Rig state, falling back to the legacy mouth slot. */
export function faceRigAnchorFor(kit: CharacterKit, poseId: string, state: CharacterKitFaceRigState): CharacterFaceAnchor {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const poseAnchors = kit.anchors[poseId.trim() || 'base'] ?? kit.anchors.base
  if (state === 'blink') return normalizeFaceRigAnchor(poseAnchors?.eyes ?? DEFAULT_FACE_RIG_BLINK_ANCHOR)
  return normalizeFaceRigAnchor(poseAnchors?.mouthStates?.[state as CharacterMouthState] ?? poseAnchors?.mouth ?? DEFAULT_FACE_RIG_ANCHOR)
}

/** Copy one calibrated mouth placement onto closed/small/wide/round for this pose. */
export function lockFaceRigMouthPlacement(
  kit: CharacterKit,
  poseId: string,
  anchor: Partial<CharacterFaceAnchor>,
): CharacterKit {
  const normalizedPoseId = poseId.trim() || 'base'
  const nextAnchor = normalizeFaceRigAnchor(anchor)
  const current = kit.anchors[normalizedPoseId] ?? kit.anchors.base ?? { mouth: DEFAULT_FACE_RIG_ANCHOR }
  const mouthStates = {
    closed: nextAnchor,
    small: nextAnchor,
    wide: nextAnchor,
    round: nextAnchor,
  }
  return {
    ...kit,
    anchors: {
      ...kit.anchors,
      [normalizedPoseId]: { mouth: nextAnchor, mouthStates, eyes: current.eyes },
    },
    provenance: [...kit.provenance, {
      method: 'character-kit-face-rig-lock-mouths',
      poseId: normalizedPoseId,
      anchor: nextAnchor,
    }],
    updatedAt: new Date().toISOString(),
  }
}

/** Persist a calibrated overlay anchor without approving the generated piece. */
export function setFaceRigAnchor(
  kit: CharacterKit,
  poseId: string,
  state: CharacterKitFaceRigState,
  anchor: Partial<CharacterFaceAnchor>,
): CharacterKit {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const normalizedPoseId = poseId.trim() || 'base'
  const nextAnchor = normalizeFaceRigAnchor(anchor)
  const current = kit.anchors[normalizedPoseId] ?? kit.anchors.base ?? { mouth: DEFAULT_FACE_RIG_ANCHOR }
  const nextPoseAnchors = state === 'blink'
    ? { mouth: normalizeFaceRigAnchor(current.mouth), mouthStates: current.mouthStates, eyes: nextAnchor }
    : {
      mouth: normalizeFaceRigAnchor(current.mouth ?? nextAnchor),
      mouthStates: { ...current.mouthStates, [state]: nextAnchor },
      eyes: current.eyes,
    }
  return {
    ...kit,
    anchors: { ...kit.anchors, [normalizedPoseId]: nextPoseAnchors },
    provenance: [...kit.provenance, {
      method: 'character-kit-face-rig-anchor',
      state,
      poseId: normalizedPoseId,
      anchor: nextAnchor,
    }],
    updatedAt: new Date().toISOString(),
  }
}

const cssPercent = (value: number) => `${Number(value.toFixed(4))}%`

export type FaceRigMouthRegion = {
  x: number
  y: number
  width: number
  height: number
}

export function containedImageRect(
  imageWidth: number,
  imageHeight: number,
  boxWidth: number,
  boxHeight: number,
): { x: number; y: number; width: number; height: number } {
  const src = imageWidth / Math.max(1, imageHeight)
  const box = boxWidth / Math.max(1, boxHeight)
  if (src > box) {
    const height = boxWidth / Math.max(.0001, src)
    return { x: 0, y: (boxHeight - height) / 2, width: boxWidth, height }
  }
  const width = boxHeight * src
  return { x: (boxWidth - width) / 2, y: 0, width, height: boxHeight }
}

/** Mouth box in preview-square percents (top-left + size). */
export function faceRigRegionFromAnchor(anchor: Partial<CharacterFaceAnchor>): FaceRigMouthRegion {
  const next = normalizeFaceRigAnchor(anchor)
  const size = Math.max(.5, next.scale * 100)
  return {
    x: 50 + next.offsetX - size / 2,
    y: 50 + next.offsetY - size / 2,
    width: size,
    height: size,
  }
}

export function faceRigAnchorFromRegion(region: FaceRigMouthRegion): CharacterFaceAnchor {
  const width = Math.max(.5, Number(region.width) || 0)
  const height = Math.max(.5, Number(region.height) || 0)
  return normalizeFaceRigAnchor({
    offsetX: Number(region.x) + width / 2 - 50,
    offsetY: Number(region.y) + height / 2 - 50,
    scale: Math.max(width, height) / 100,
    rotation: 0,
  })
}

export function previewPercentToImagePixel(
  percentX: number,
  percentY: number,
  imageWidth: number,
  imageHeight: number,
): { x: number; y: number } {
  const content = containedImageRect(imageWidth, imageHeight, 100, 100)
  const u = (percentX - content.x) / Math.max(.0001, content.width)
  const v = (percentY - content.y) / Math.max(.0001, content.height)
  return {
    x: Math.max(0, Math.min(imageWidth - 1, u * imageWidth)),
    y: Math.max(0, Math.min(imageHeight - 1, v * imageHeight)),
  }
}

/** Fill an elliptical mouth box with sampled nearby skin. Leaves the rest of the pose intact. */
export function wipeMouthRegion(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  region: { cx: number; cy: number; rx: number; ry: number },
): Uint8ClampedArray {
  if (!(rgba instanceof Uint8ClampedArray) || rgba.length !== width * height * 4) {
    return new Uint8ClampedArray(rgba)
  }
  const next = new Uint8ClampedArray(rgba)
  const rx = Math.max(1, region.rx)
  const ry = Math.max(1, region.ry)
  const samples: number[] = []
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const nx = (x - region.cx) / rx
      const ny = (y - region.cy) / ry
      const d = nx * nx + ny * ny
      if (d < 1.05 || d > 1.45) continue
      const i = (y * width + x) * 4
      if (next[i + 3] < 16) continue
      samples.push(next[i], next[i + 1], next[i + 2])
    }
  }
  let fillR = 210
  let fillG = 170
  let fillB = 140
  if (samples.length >= 12) {
    const channel = (offset: number) => {
      const values = []
      for (let index = offset; index < samples.length; index += 3) values.push(samples[index])
      values.sort((a, b) => a - b)
      return values[Math.floor(values.length / 2)]
    }
    fillR = channel(0)
    fillG = channel(1)
    fillB = channel(2)
  }
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const nx = (x - region.cx) / rx
      const ny = (y - region.cy) / ry
      const d = nx * nx + ny * ny
      if (d > 1) continue
      const i = (y * width + x) * 4
      const mix = d > .72 ? (1 - d) / .28 : 1
      next[i] = Math.round(next[i] * (1 - mix) + fillR * mix)
      next[i + 1] = Math.round(next[i + 1] * (1 - mix) + fillG * mix)
      next[i + 2] = Math.round(next[i + 2] * (1 - mix) + fillB * mix)
      if (next[i + 3] > 0) next[i + 3] = 255
    }
  }
  return next
}

export function faceRigOverlayPreviewStyle(anchor: CharacterFaceAnchor): {
  left: string
  top: string
  width: string
  height: string
  transform: string
} {
  const next = normalizeFaceRigAnchor(anchor)
  const size = Math.max(.5, next.scale * 100)
  return {
    left: cssPercent(50 + next.offsetX),
    top: cssPercent(50 + next.offsetY),
    width: cssPercent(size),
    height: cssPercent(size),
    transform: `translate(-50%, -50%) rotate(${next.rotation}deg)`,
  }
}

export const FACE_RIG_MOUTH_STATES = ['closed', 'small', 'wide', 'round'] as const
export const FACE_RIG_PRESET_ROOT = '/character-kit-presets/mouths'

export interface FaceRigMouthPresetPack {
  id: string
  label: string
  style?: string
  notes?: string
  states: Partial<Record<CharacterMouthState, { file: string }>>
}

/** Attach a reusable viseme pack as pending overlays. Does not approve placement. */
export function applyFaceRigMouthPreset(
  kit: CharacterKit,
  pack: FaceRigMouthPresetPack,
  workspace?: string,
): CharacterKit {
  if (!pack.id.trim()) throw new Error('Choose a mouth style pack first.')
  let next = kit
  for (const state of FACE_RIG_MOUTH_STATES) {
    const file = pack.states[state]?.file
    if (!file) continue
    const source = `${FACE_RIG_PRESET_ROOT}/${file.replace(/^\/+/, '')}`
    next = registerGeneratedFaceRigAsset(next, state, {
      id: `${kit.id}-${pack.id}-${state}`,
      name: `${kit.name} · ${state} · ${pack.label}`,
      source,
      kind: 'overlay',
      alphaStatus: 'transparent',
      reviewState: 'pending',
      workspace,
    }, {
      poseId: 'preset',
      reference: source,
      prompt: pack.notes || pack.label,
      packId: pack.id,
      methodHint: 'character-kit-face-rig-preset',
    })
  }
  if (next === kit) throw new Error(`Pack “${pack.label}” has no closed/small/wide/round overlays.`)
  return next
}
export const FACE_RIG_DIALOGUE_MIN_SECONDS = 2
export const FACE_RIG_DIALOGUE_MAX_SECONDS = 4

export type FaceRigDialogueViseme = {
  start: number
  end: number
  state: CharacterMouthState
  sourceState: CharacterMouthState
  fallback: boolean
}

export type FaceRigDialoguePreview = {
  text: string
  start: number
  end: number
  visemes: FaceRigDialogueViseme[]
  available: CharacterMouthState[]
  missing: CharacterMouthState[]
}

export function clampFaceRigDialogueDuration(value: number): number {
  if (!Number.isFinite(value)) return 3
  return Math.min(FACE_RIG_DIALOGUE_MAX_SECONDS, Math.max(FACE_RIG_DIALOGUE_MIN_SECONDS, value))
}

function mouthAvailability(kit: CharacterKit): { available: CharacterMouthState[]; missing: CharacterMouthState[]; fallback?: CharacterMouthState } {
  const available = FACE_RIG_MOUTH_STATES.filter(state => Boolean(kit.mouth[state]?.source))
  const missing = FACE_RIG_MOUTH_STATES.filter(state => !kit.mouth[state]?.source)
  const fallback = (['wide', 'small', 'round', 'closed'] as const).find(state => available.includes(state))
  return { available, missing, fallback }
}

function withMouthFallback(
  kit: CharacterKit,
  text: string,
  visemes: Array<{ start: number; end: number; state: CharacterMouthState }>,
  start: number,
  end: number,
): FaceRigDialoguePreview {
  const { available, missing, fallback } = mouthAvailability(kit)
  return {
    text,
    start,
    end,
    available,
    missing,
    visemes: visemes.map(beat => {
      const has = available.includes(beat.state)
      const sourceState = has ? beat.state : fallback ?? beat.state
      return { ...beat, sourceState, fallback: !has && sourceState !== beat.state }
    }),
  }
}

/** Plan a 2–4s viseme preview from text using the existing cutout cadence. */
export function previewFaceRigDialogue(kit: CharacterKit, text: string, durationSeconds = 3, fps = 30): FaceRigDialoguePreview {
  const duration = clampFaceRigDialogueDuration(durationSeconds)
  const plan = planCutoutDialogue(text.trim(), 0, duration, fps)
  return withMouthFallback(kit, text.trim(), plan.visemes, plan.start, plan.end)
}

/** Rebuild the same preview from analyzed speech units without writing the kit. */
export function previewFaceRigDialogueFromAudio(
  kit: CharacterKit,
  text: string,
  units: Array<{ text: string; start: number; end: number }>,
  fps = 30,
): FaceRigDialoguePreview {
  const usable = units.filter(unit => unit.text.trim() && Number.isFinite(unit.start) && Number.isFinite(unit.end) && unit.end > unit.start)
  if (!usable.length) return previewFaceRigDialogue(kit, text, 3, fps)
  const end = clampFaceRigDialogueDuration(usable[usable.length - 1].end)
  const visemes = usable.flatMap(unit => {
    const start = Math.max(0, unit.start)
    if (start >= end) return []
    return planCutoutDialogue(unit.text, start, Math.min(end, unit.end), fps).visemes
  })
  return withMouthFallback(kit, text.trim() || usable.map(unit => unit.text).join(' '), visemes, 0, end)
}

export function faceRigVisemeAt(preview: FaceRigDialoguePreview, time: number): FaceRigDialogueViseme | undefined {
  if (!preview.visemes.length) return undefined
  return preview.visemes.find(beat => time >= beat.start && time < beat.end) ?? preview.visemes[preview.visemes.length - 1]
}

/** Warn when an overlay is far from the face or obviously the wrong size. Never auto-approves. */
export function assessFaceRigPlacement(anchor: CharacterFaceAnchor, state: CharacterKitFaceRigState): { ok: boolean; warnings: string[] } {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const next = normalizeFaceRigAnchor(anchor)
  const warnings: string[] = []
  if (Math.abs(next.offsetX) > 28 || Math.abs(next.offsetY) > 42) {
    warnings.push('This overlay sits far from the pose center and may miss the face.')
  }
  if (next.scale < .012) warnings.push('This overlay is unusually small compared with the pose.')
  if (state === 'blink' ? next.scale > .2 : next.scale > .12) {
    warnings.push(state === 'blink'
      ? 'This blink overlay is larger than a typical eye mask. Scale it down until it only covers the eyes.'
      : 'This mouth overlay is larger than a typical viseme. Scale it down until it sits on the lips.')
  }
  if (state !== 'blink' && next.offsetY > -8) {
    warnings.push('Mouths on a full-body cutout usually sit above the chest. Nudge Down/Up until the overlay covers the lips, then lock all mouths.')
  }
  return { ok: warnings.length === 0, warnings }
}

/** Change review status without mutating the kit or its nested asset. */
export function setFaceRigReviewState(kit: CharacterKit, state: CharacterKitFaceRigState, reviewState: CharacterKitReviewState): CharacterKit {
  const current = assetForState(kit, state)
  if (!current) throw new Error(`Character Kit “${kit.name}” has no generated ${state} asset.`)
  const next = { ...current, reviewState }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: next } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: next } : kit.eyes,
    updatedAt: new Date().toISOString(),
  }
}
