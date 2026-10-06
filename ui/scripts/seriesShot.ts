// Headless Series shot compiler. The server plans a shot (framing, cast, recorded lines) and this
// module builds the editable Video 2D document with the editor's own Character Kit mounting and
// mouth compiler. It does not save, export or fetch. Layout and limited animation come from the
// "Uncanny Valley" production, where they were tuned by eye on a full episode. A layered set
// (series_layers.py) gives the background and each layer its share of the camera push by depth.
// A pose cut by its image border is moved so the cut stays out of the frame (snapToEdges), a
// grounded prop stands on the floor (groundedY) and a video layer can play on its own clock.
import { mountCharacterKitLayers, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit.ts'
import { rebuildCutoutDialogueLayers } from '../src/lib/cutoutDialogue.ts'
import { parseMouthCues } from '../src/features/scene3d/speech/track.ts'
import type { Scene, SceneKeyframe, SceneLayer } from '../src/types/index.ts'

export type Pose = { x: number; y: number; scale: number; opacity?: number; rotation?: number }
export type Framing = 'wide' | 'two' | 'medium' | 'close' | 'insert' | 'title'
export type Motion = 'idle' | 'still' | 'shake'
export type CastSpec = {
  kitId: string; poseId?: string; x: number; z?: number; motion?: Motion
  /** Size multiplier for this character (a small robot, a tall giant). */
  boost?: number
  transform?: Pose; blinks?: number[]
  /** Sits on a prop (a laptop on its desk): the prop's image size, its top surface (fraction from the top) and width vs the character. */
  perch?: { source: string; width: number; height: number; top?: number; widthRatio?: number }
  /** Slides in from fromX (series_entrances.py). A `walk` takes a whole number of `step`-second steps: down on every
   * footfall (its start, each step, its end), up mid-step, leaning `sway` degrees to alternate sides; else it hops. */
  enter?: { fromX: number; start: number; end: number; gait?: 'hop' | 'walk'; step?: number; sway?: number }
  exit?: { toX: number; start: number; end: number }
  /** false: a pose cut by its image border stays where ``x`` puts it, cut and all (snapToEdges). */
  edgeSnap?: boolean
}
export type LineSpec = {
  id: string; kitId: string; text: string; start: number; end: number; filename: string
  cues?: unknown; driver?: string; visible?: boolean; volume?: number; name?: string
}
export type PropSpec = {
  id: string; name: string; source: string; x: number; y: number; scale: number; z?: number
  /** Stand the prop's lowest opaque row on ``floor`` (% of the frame height; the framing's floorLine when left out)
   * instead of centring it on ``y``. The server reads ``width``/``height`` (px) and ``bottom`` (that row, as a fraction
   * of the image height from the top) from the image; without them the prop keeps ``y``. */
  ground?: { floor?: number; width?: number; height?: number; bottom?: number }
}
/** A layer of the set, placed on the framed background by the planner (``series_shot_plan.plan_layers``). */
export type SetLayerSpec = {
  id: string; name: string; source: string; kind: 'image' | 'video'; x: number; y: number; scale: number; opacity?: number
  /** 0 is the far plane of the background (moves least), 1 the nearest. */
  depth: number
  /** Drawn in front of the cast (a pillar, a candle, fog in the foreground); otherwise behind it, above the background. */
  front?: boolean
  /** Idle drift in frame pixels per second, negative to the left (fog, smoke). */
  drift?: number
  /** A video's own clock (any of them gives the layer ``playback``): the clip second at the shot's start, what happens
   * at its end and its rate. Left out, the video loops from its first frame, as before. */
  start?: number; loop?: 'loop' | 'hold' | 'pingpong'; speed?: number
}
export type ShotSpec = {
  name: string; workspace: string; width: number; height: number; fps: 24 | 30 | 60; duration: number
  framing: Framing; background?: { source: string; kind: 'image' | 'video'; focusX?: number }
  cast: CastSpec[]; lines: LineSpec[]; props?: PropSpec[]
  /** Set layers; with any, the background and the layers respond to the camera by depth, the cast standing at castDepth. */
  layers?: SetLayerSpec[]; castDepth?: number
  audioTracks?: NonNullable<Scene['audioTracks']>; texts?: Scene['texts']; sfx?: Scene['sfx']; finish?: Scene['finish']
  camera?: 'static' | 'push'; narrative?: Scene['narrative']
}
type Beat = NonNullable<Scene['dialogueBeats']>[number]

const round = (value: number) => Math.round(value * 1000) / 1000
/** Standing characters: layer scale and eye line (% of frame height) per framing; wide shots stand on FEET. */
export const FRAMING: Record<'wide' | 'two' | 'medium' | 'close', { scale: number; eye: number | null }> = {
  wide: { scale: 0.5, eye: null }, two: { scale: 0.8, eye: 33 }, medium: { scale: 1.22, eye: 33 }, close: { scale: 1.78, eye: 42 },
}
/** The same framings in a vertical frame (TikTok, Reels): the frame is 0.56 as wide, so people are drawn smaller
 * against its height to fit side by side and stand on the floor even in a two-shot, and a close-up fills the width with the face. */
export const FRAMING_PORTRAIT: typeof FRAMING = {
  wide: { scale: 0.42, eye: null }, two: { scale: 0.55, eye: null }, medium: { scale: 0.78, eye: 30 }, close: { scale: 1.1, eye: 38 },
}
const FEET = 94
/** Medium shots and close-ups cut the body below the frame: the figure must end past this line (% of frame height), so not even the shoes show. */
const CROP_LINE = 112
export const BACKGROUND_ZOOM: Record<Framing, number> = { wide: 1, two: 1.12, medium: 1.28, close: 1.5, insert: 1, title: 1 }
/** Camera response of the base background, the far plane of a set (depth 0). The cast takes the full move (1). */
export const FAR_PARALLAX = 0.2
/** Depth of the cast among a set's layers when neither the location nor the shot gives one. */
export const CAST_DEPTH = 0.6

function poseAsset(kit: CharacterKit, poseId: string) {
  const asset = poseId === 'base' ? kit.base : kit.poses[poseId]
  if (!asset) throw new Error(`Character ${kit.name} has no pose ${poseId}`)
  if (!asset.width || !asset.height) throw new Error(`Pose ${poseId} of ${kit.name} has no pixel size`)
  return { width: asset.width, height: asset.height }
}

/** Height a pose occupies, in % of frame height, at a layer scale (the layer is contained in the frame). */
function drawnHeight(size: { width: number; height: number }, scale: number, aspect: number) {
  const ratio = size.width / size.height
  return ratio < aspect ? scale * 100 : scale * 100 * aspect / ratio
}

/** Eye line as a fraction of the pose image height (from the top), from the kit's eye anchor. */
function eyeFraction(kit: CharacterKit, poseId: string, size: { width: number; height: number }) {
  const eyes = kit.anchors[poseId]?.eyes ?? kit.anchors.base?.eyes
  if (!eyes) return 0.25
  return 0.5 + eyes.offsetY * Math.max(size.width, size.height) / 100 / size.height
}

/** The standing preset of a framing in this frame (inserts and title cards use the wide one). */
function framingPreset(framing: Framing, aspect: number) {
  return (aspect < 1 ? FRAMING_PORTRAIT : FRAMING)[framing === 'insert' || framing === 'title' ? 'wide' : framing]
}

/** Where a standing character goes for a framing: feet on the floor in wide shots, eyes on the line otherwise. */
export function personTransform(kit: CharacterKit, poseId: string, framing: Framing, x: number, aspect: number, boost = 1): Pose {
  const preset = framingPreset(framing, aspect)
  const size = poseAsset(kit, poseId)
  let scale = preset.scale * boost
  let height = drawnHeight(size, scale, aspect)
  if (framing === 'medium' || framing === 'close') {
    // A wide pose (open arms, a tail) in a narrow vertical frame is drawn smaller to fit the width, and a medium shot or
    // close-up would then show the whole body with its feet in mid-air. Enlarge it, eyes on the same line, until the
    // feet leave the frame.
    const needed = (CROP_LINE - preset.eye) / (1 - eyeFraction(kit, poseId, size))
    if (height < needed) {
      scale *= needed / height
      height = needed
    }
  }
  const y = preset.eye === null ? FEET - height / 2 + height * 0.015 : preset.eye + (0.5 - eyeFraction(kit, poseId, size)) * height
  return { x, y: round(y), scale: round(scale) }
}

/** The edges of a pose image its figure is cut by, as the server reads them from the alpha (``series_cutouts``): runs of
 * opaque pixels down the left and right sides ([from, to] fractions of the image height, from the top) and along the
 * bottom (fractions of its width). */
export type CutEdges = { left?: Array<[number, number]>; right?: Array<[number, number]>; bottom?: Array<[number, number]> }
/** How far past the frame edge (% of the frame) a cut goes, so the bob and tilt of a talking cutout never show it. */
export const EDGE_BLEED = 2
/** The most a cutout cut on both sides is enlarged to hide its cuts. */
export const MAX_EDGE_ZOOM = 2.5
/** A cut seen for less than this (% of the frame height) does not move the cutout. */
const EDGE_SEEN = 1

function cutRuns(value: unknown): Array<[number, number]> {
  return Array.isArray(value) ? value.filter((run): run is [number, number] => Array.isArray(run) && run.length === 2
    && run.every(edge => typeof edge === 'number' && Number.isFinite(edge)) && run[1] > run[0]) : []
}

/** How much of a side's cut runs (% of the frame height) is inside the frame, for a pose drawn from ``top`` at ``height``. */
function seenCut(runs: Array<[number, number]>, top: number, height: number) {
  return Math.max(0, ...runs.map(([from, to]) => Math.min(100, top + to * height) - Math.max(0, top + from * height)))
}

/** Where a standing cutout cut by its image border goes so no cut shows. The bottom cut goes past the frame bottom: slid
 * down where people stand on the floor (``eyes.line`` null), enlarged on the eye line otherwise. A side cut that shows
 * slides the cutout to that frame edge; with both sides showing, it is enlarged proportionally (on its eyes, or on its
 * feet when they stand on the floor) until both cuts are out of the frame, at most MAX_EDGE_ZOOM; past that it is slid
 * to hide the longer cut. A cut already outside the frame moves nothing. Deterministic: the same pose and frame give
 * the same transform. */
export function snapToEdges(base: Pose, size: { width: number; height: number }, cut: CutEdges, aspect: number,
  eyes: { line: number | null; fraction: number }): Pose {
  const left = cutRuns(cut.left), right = cutRuns(cut.right), bottomCut = cutRuns(cut.bottom).length > 0
  if (!left.length && !right.length && !bottomCut) return base
  const height = drawnHeight(size, base.scale, aspect)
  let top = base.y - height / 2
  if (eyes.line === null && bottomCut) top = Math.max(top, 100 + EDGE_BLEED - height)
  // The point of the pose that stays put while it is enlarged (fraction of its height) and where it is in the frame.
  const anchor = eyes.line === null && !bottomCut ? 1 : eyes.fraction
  const at = top + anchor * height
  const lowest = bottomCut && anchor < 1 ? Math.max(1, (100 + EDGE_BLEED - at) / ((1 - anchor) * height)) : 1
  const place = (zoom: number, fallback = false): Pose | null => {
    // Rounded up, so the stored scale still reaches past the frame edge.
    const scale = Math.ceil(base.scale * zoom * 1000 - 1e-6) / 1000
    const drawn = height * scale / base.scale, width = drawn * size.width / size.height / aspect, from = at - anchor * drawn
    const seenLeft = seenCut(left, from, drawn), seenRight = seenCut(right, from, drawn)
    // Rightmost x that hides a left cut, leftmost x that hides a right cut.
    const hideLeft = width / 2 - EDGE_BLEED, hideRight = 100 + EDGE_BLEED - width / 2
    let x = base.x
    if (seenLeft >= EDGE_SEEN && seenRight >= EDGE_SEEN) {
      if (hideRight <= hideLeft) x = Math.max(hideRight, Math.min(hideLeft, base.x))
      else if (!fallback) return null
      else x = seenLeft >= seenRight ? Math.min(base.x, hideLeft) : Math.max(base.x, hideRight)
    } else if (seenLeft >= EDGE_SEEN) x = Math.min(base.x, hideLeft)
    else if (seenRight >= EDGE_SEEN) x = Math.max(base.x, hideRight)
    return { x: round(x), y: round(from + drawn / 2), scale }
  }
  for (let step = 0; lowest + step / 100 <= MAX_EDGE_ZOOM; step++) {
    const placed = place(lowest + step / 100)
    if (placed) return placed
  }
  return place(Math.min(lowest, MAX_EDGE_ZOOM), true)!
}

/** A standing cast member: placed by its framing, then off the edges its pose is cut by unless ``edgeSnap`` is false. */
export function castTransform(kit: CharacterKit, cast: CastSpec, framing: Framing, aspect: number, boost = 1): Pose {
  const poseId = cast.poseId ?? 'base'
  const base = personTransform(kit, poseId, framing, cast.x, aspect, boost)
  const cut = ((poseId === 'base' ? kit.base : kit.poses[poseId]) as (CharacterKitAsset & { cut?: CutEdges }) | undefined)?.cut
  if (cast.edgeSnap === false || !cut) return base
  const size = poseAsset(kit, poseId)
  return snapToEdges(base, size, cut, aspect, { line: framingPreset(framing, aspect).eye, fraction: eyeFraction(kit, poseId, size) })
}

/** The floor a grounded prop stands on (% of the frame height): the cast's feet line where the framing shows people on
 * their feet; in an eye-line framing, the set's floor through the background zoom (below the frame in a medium shot or
 * a close-up, as the cast's feet are). */
export function floorLine(framing: Framing, aspect: number): number {
  return round(framingPreset(framing, aspect).eye === null ? FEET : 50 + (FEET - 50) * BACKGROUND_ZOOM[framing])
}

/** A prop's centre: its lowest opaque row on the floor (or its anchor) when it is grounded and measured, else its ``y``. */
export function groundedY(prop: PropSpec, framing: Framing, aspect: number): number {
  const ground = prop.ground
  if (!ground?.width || !ground.height || typeof ground.bottom !== 'number') return prop.y
  const height = drawnHeight({ width: ground.width, height: ground.height }, prop.scale, aspect)
  return round((ground.floor ?? floorLine(framing, aspect)) - (ground.bottom - 0.5) * height)
}

/** A perched character's height and the line it sits on (% of frame) per framing, as in 1x01's laptop on its desk. */
export const DIALOGUE_DUCK_DB = 10

export const PERCH: Record<'wide' | 'two' | 'medium' | 'close', { height: number; bottom: number }> = {
  wide: { height: 29, bottom: 70 }, two: { height: 40, bottom: 74 }, medium: { height: 56, bottom: 84 }, close: { height: 76, bottom: 94 },
}
export const PERCH_PORTRAIT: typeof PERCH = {
  wide: { height: 20, bottom: 72 }, two: { height: 28, bottom: 76 }, medium: { height: 40, bottom: 84 }, close: { height: 56, bottom: 94 },
}

/** Where a perched character and its prop go: the character's bottom on the prop's top surface. */
export function perchTransforms(size: { width: number; height: number }, framing: Framing, x: number, aspect: number,
  perch: NonNullable<CastSpec['perch']>): { character: Pose; prop: Pose } {
  const preset = (aspect < 1 ? PERCH_PORTRAIT : PERCH)[framing === 'insert' || framing === 'title' ? 'wide' : framing]
  const characterWidth = preset.height * (size.width / size.height) / aspect
  const propWidth = characterWidth * (perch.widthRatio ?? 1.45)
  const propAspect = perch.width / perch.height
  const propHeight = propWidth * aspect / propAspect
  const propScale = propAspect < aspect ? propHeight / 100 : propWidth / 100
  const propY = preset.bottom - ((perch.top ?? 0.04) - 0.5) * propHeight
  return { character: { x, y: round(preset.bottom - preset.height / 2), scale: round(preset.height / 100) },
    prop: { x, y: round(propY), scale: round(propScale) } }
}

/** The full-frame background, zoomed and panned by the framing. In a layered set it is the far plane (depth 0) and
 * takes only its parallax share of the camera zoom. */
export function backgroundLayer(background: NonNullable<ShotSpec['background']>, framing: Framing, duration: number, layered = false): SceneLayer {
  const zoom = BACKGROUND_ZOOM[framing]
  const focus = background.focusX ?? 50
  const span = 50 * (zoom - 1)
  const x = Math.max(50 - span, Math.min(50 + span, 50 - (focus / 100 - 0.5) * 100 * zoom))
  const transform = { x: round(x), y: 50, scale: zoom, opacity: 1, rotation: 0 }
  return {
    id: 'background', name: 'Background', type: background.kind, source: background.source, visible: true, locked: false, z: 0,
    fill: true, parallax: FAR_PARALLAX, transform,
    animation: { start: { ...transform }, end: { ...transform }, duration, curve: 'linear',
      ...(background.kind === 'video' ? { loop: true, offset: 0, speed: 1 } : {}) },
    ...(layered ? { parallaxZoom: true } : {}),
  } as SceneLayer
}

/** Camera response (pan and zoom) of a set layer: linear in depth, the background's at 0 and the cast's (1) at its
 * own depth, at most 2. A push grows a layer at depth d by (zoom - 1) * this, so far layers grow less than the cast. */
export function depthParallax(depth: number, castDepth = CAST_DEPTH): number {
  return round(Math.min(2, FAR_PARALLAX + (1 - FAR_PARALLAX) * depth / Math.max(0.1, castDepth)))
}

/** One set layer at its depth's share of the camera move; drift slides it on its own (frame px per second). */
export function setLayer(layer: SetLayerSpec, z: number, duration: number, width: number, castDepth: number): SceneLayer {
  const transform = { x: layer.x, y: layer.y, scale: layer.scale, opacity: layer.opacity ?? 1, rotation: 0 }
  const end = layer.drift ? { ...transform, x: round(layer.x + layer.drift / width * 100 * duration) } : transform
  return {
    id: layer.id, name: layer.name, type: layer.kind, source: layer.source, visible: true, locked: false, z: round(z), fill: false,
    parallax: depthParallax(layer.depth, castDepth), parallaxZoom: true, transform,
    animation: { start: { ...transform }, end: { ...end }, duration, curve: 'linear',
      ...(layer.kind === 'video' ? { loop: true, offset: 0, speed: 1 } : {}) },
    ...(layer.kind === 'video' && (layer.start !== undefined || layer.loop !== undefined || layer.speed !== undefined)
      ? { playback: { start: layer.start ?? 0, loop: layer.loop ?? 'loop', speed: layer.speed ?? 1 } } : {}),
  } as SceneLayer
}

/** The set's layers on one side of the cast, farthest first, from z ``from`` in steps of ``step``. */
function setLayers(shot: ShotSpec, front: boolean, from: number, step: number): SceneLayer[] {
  const castDepth = shot.castDepth ?? CAST_DEPTH
  return (shot.layers ?? []).filter(layer => Boolean(layer.front) === front).sort((a, b) => a.depth - b.depth)
    .map((layer, index) => setLayer(layer, from + index * step, shot.duration, shot.width, castDepth))
}

function key(id: string, time: number, pose: Pose, curve: SceneKeyframe['curve'] = 'linear'): SceneKeyframe {
  return { id: `${id}-${Math.round(time * 1000)}`, time: round(time), x: round(pose.x), y: round(pose.y), scale: round(pose.scale),
    opacity: pose.opacity ?? 1, rotation: round(pose.rotation ?? 0), curve }
}

/** How high a walking cutout rises mid-step, in % of the frame height per unit of layer scale. */
export const WALK_BOB = 1.2

/** A walk in: the slide at an even pace, with the body lowest on each footfall and highest mid-step (|sin| of the
 * step, sampled every quarter step), leaning to alternate sides. Footfalls are at the start, every step and the end. */
export function walkKeyframes(id: string, rest: Pose, enter: NonNullable<CastSpec['enter']>): SceneKeyframe[] {
  const span = enter.end - enter.start
  const steps = Math.max(1, Math.round(span / (enter.step || span)))
  const sway = enter.sway ?? 0
  const frames: SceneKeyframe[] = []
  for (let quarter = 0; quarter < steps * 4; quarter++) {
    const progress = quarter / (steps * 4)
    const lift = Math.sin(Math.PI * (quarter % 4) / 4)
    const side = Math.floor(quarter / 4) % 2 ? -1 : 1
    frames.push(key(id, enter.start + span * progress, {
      x: enter.fromX + (rest.x - enter.fromX) * progress, y: rest.y - lift * WALK_BOB * rest.scale, scale: rest.scale,
      rotation: lift ? side * sway * lift : 0 }))
  }
  return frames
}

/** Limited animation: a bob and tilt while talking, a slow breath otherwise, a shake in panic, hops (or a walk) on entry. */
export function bodyKeyframes(id: string, base: Pose, duration: number, talking: Array<[number, number]>, motion: Motion = 'idle',
  enter?: CastSpec['enter'], exit?: CastSpec['exit']): SceneKeyframe[] {
  const frames: SceneKeyframe[] = []
  const step = 0.25
  const seed = [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const rest = { ...base, rotation: 0, opacity: 1 }
  if (enter) {
    const from = { ...rest, x: enter.fromX }
    frames.push(key(id, 0, from, 'hold'))
    if (enter.gait === 'walk') frames.push(...walkKeyframes(id, rest, enter))
    else if (enter.start > 0) frames.push(key(id, enter.start, from, 'ease'))
    // A paper puppet slides with a little hop on every step.
    const hops = enter.gait === 'walk' ? 0 : Math.max(1, Math.round((enter.end - enter.start) / 0.22))
    for (let i = 1; i < hops; i++) {
      const progress = i / hops
      frames.push(key(id, enter.start + (enter.end - enter.start) * progress, {
        x: enter.fromX + (rest.x - enter.fromX) * progress, y: rest.y - (i % 2 ? 1.1 : 0) * rest.scale, scale: rest.scale,
        rotation: i % 2 ? 2 : -2 }))
    }
    frames.push(key(id, enter.end, rest))
  }
  const until = Math.min(duration, exit?.start ?? duration + 1)
  for (let t = enter ? enter.end + step : 0; t <= until + 1e-6; t += step) {
    const speaking = talking.some(([start, end]) => t >= start - 0.05 && t <= end + 0.05)
    const i = Math.round(t / step) + seed
    let dx = 0, dy = 0, rotation = 0
    if (motion === 'shake') { dx = Math.sin(i * 2.7) * 0.35 * rest.scale; rotation = Math.sin(i * 1.9) * 1.2 }
    else if (motion === 'idle' && speaking) { dy = -Math.abs(Math.sin(i * 1.3)) * 0.45 * rest.scale; rotation = Math.sin(i * 0.9) * 0.9 }
    else if (motion === 'idle') dy = Math.sin(t * 1.4 + seed) * 0.12 * rest.scale
    frames.push(key(id, t, { ...rest, x: rest.x + dx, y: rest.y + dy, rotation }, speaking ? 'linear' : 'ease'))
  }
  if (exit) {
    frames.push(key(id, exit.start, rest, 'ease'))
    frames.push(key(id, exit.end, { ...rest, x: exit.toX }, 'hold'))
  }
  const byTime = new Map<number, SceneKeyframe>()
  for (const frame of frames) byTime.set(Math.round(frame.time * 1000), frame)
  return [...byTime.values()].sort((a, b) => a.time - b.time)
}

/** Blinks every 2.4–4.6 s from a seed, so a shot always blinks the same way. */
export function blinkTimes(seedText: string, duration: number): number[] {
  let state = [...seedText].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7) || 1
  const next = () => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296 }
  const times: number[] = []
  for (let t = 0.6 + next() * 1.6; t < duration - 0.3; t += 2.4 + next() * 2.2) times.push(round(t))
  return times
}

function blinkAnimation(layer: SceneLayer, blinks: number[]): SceneLayer['animation'] {
  const states = [{ time: 0, on: false }, ...blinks.flatMap(time => [{ time, on: true }, { time: time + 0.11, on: false }])]
  return { ...layer.animation, curve: 'hold', keyframes: states.map(({ time, on }) => ({
    id: `${layer.id}-${Math.round(time * 1000)}`, time: round(time), x: layer.transform.x, y: layer.transform.y,
    scale: layer.transform.scale, opacity: on ? 1 : 0, rotation: layer.transform.rotation ?? 0, curve: 'hold' as const })) }
}

/** Mount one kit: pose, mouths and blink, z-shifted, with body motion and blinks. Returns the layers and mouth ids. */
export function mountCast(kit: CharacterKit, cast: CastSpec, base: Pose, duration: number, viewport: { width: number; height: number },
  workspace: string, talking: Array<[number, number]>) {
  const transform = { ...base, opacity: 1, rotation: 0 }
  // Children follow the pose from its t=0 state, so mount where the pose starts.
  const origin = cast.enter ? { ...transform, x: cast.enter.fromX } : transform
  const mounted = mountCharacterKitLayers(kit, cast.poseId ?? 'base', origin, duration, viewport)
  const pose = mounted[0]
  const shift = (cast.z ?? pose.z) - pose.z
  for (const layer of mounted) {
    layer.z = round(layer.z + shift)
    layer.characterKitRef = { id: kit.id, workspace }
  }
  pose.animation = { ...pose.animation, start: { ...transform }, end: { ...transform }, duration, curve: 'linear',
    keyframes: bodyKeyframes(pose.id, transform, duration, talking, cast.motion, cast.enter, cast.exit) }
  const blinks = cast.blinks ?? blinkTimes(`${pose.id}-${duration}`, duration)
  for (const layer of mounted) {
    if (layer.faceBinding?.role === 'blink' && blinks.length) layer.animation = blinkAnimation(layer, blinks)
  }
  return { layers: mounted, mouthIds: mounted.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id) }
}

/** A recorded line becomes a beat with phonetic lip-sync (cues on the clip's own clock) when cues exist. */
export function lineBeat(line: LineSpec, mouthIds: string[]): Beat {
  const cues = line.cues ? parseMouthCues(line.cues) : []
  const length = round(line.end - line.start)
  return {
    id: line.id, text: line.text, start: round(line.start), end: round(line.end), audioTrackId: line.id,
    mouthLayerIds: line.visible === false ? [] : mouthIds,
    confidence: cues.length ? 'aligned-audio' : 'known-text',
    ...(cues.length ? { lipSync: { version: 1 as const, driver: (line.driver ?? 'wav2vec2-phoneme') as 'wav2vec2-phoneme', text: line.text,
      audioTrackId: line.id, filename: line.filename, offset: 0, duration: Math.min(90, length),
      cues: cues.map(cue => ({ ...cue, start: round(cue.start), end: round(Math.min(cue.end, length)) })).filter(cue => cue.end > cue.start) } } : {}),
  } as Beat
}

function speechTrack(line: LineSpec): NonNullable<Scene['audioTracks']>[number] {
  return { id: line.id, filename: line.filename, name: line.name ?? line.kitId, kind: 'speech', startTime: round(line.start),
    volume: line.volume ?? 1, prompt: line.text }
}

function cameraLayer(duration: number): SceneLayer {
  const from = { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }, to = { x: 50, y: 48.5, scale: 1.07, opacity: 1, rotation: 0 }
  return { id: 'camera', name: 'Camera', type: 'camera', source: '', visible: true, locked: false, z: 1000, transform: { ...from },
    animation: { start: from, end: to, duration, curve: 'ease', keyframes: [key('camera', 0, from, 'ease'), key('camera', duration, to, 'ease')] } } as SceneLayer
}

function propLayer(prop: PropSpec, duration: number): SceneLayer {
  const transform = { x: prop.x, y: prop.y, scale: prop.scale, opacity: 1, rotation: 0 }
  return { id: prop.id, name: prop.name, type: 'image', source: prop.source, visible: true, locked: false, z: prop.z ?? 8, fill: false,
    parallax: 1, transform, animation: { start: { ...transform }, end: { ...transform }, duration, curve: 'linear' } } as SceneLayer
}

/** One editable Video 2D shot: background, set layers behind the cast, props, mounted cast, set layers in front of it,
 * recorded lines with mouths, camera and finish. */
export function compileSeriesShot(kits: Record<string, CharacterKit>, shot: ShotSpec): Scene {
  const viewport = { width: shot.width, height: shot.height }
  const aspect = shot.width / shot.height
  const layers: SceneLayer[] = []
  const layered = Boolean(shot.layers?.length)
  if (shot.background) layers.push(backgroundLayer(shot.background, shot.framing, shot.duration, layered))
  // Behind the cast and the props (z 8), above the background (z 0).
  layers.push(...setLayers(shot, false, 1, 0.5))
  for (const prop of shot.props ?? []) layers.push(propLayer({ ...prop, y: groundedY(prop, shot.framing, aspect) }, shot.duration))
  const mouthIds = new Map<string, string[]>()
  shot.cast.forEach((cast, index) => {
    const kit = kits[cast.kitId]
    if (!kit) throw new Error(`Missing Character Kit ${cast.kitId}`)
    const single = shot.cast.length === 1 && shot.framing === 'wide'
    const z = cast.z ?? 20 + index * 10
    const seat = !cast.transform && cast.perch ? perchTransforms(poseAsset(kit, cast.poseId ?? 'base'), shot.framing, cast.x, aspect, cast.perch) : null
    if (seat && cast.perch) {
      layers.push(propLayer({ id: `perch-${kit.id}`, name: `${kit.name} seat`, source: cast.perch.source, ...seat.prop, z: z - 1 }, shot.duration))
    }
    const base = cast.transform ?? seat?.character ?? castTransform(kit, cast, shot.framing, aspect, (single ? 1.25 : 1) * (cast.boost ?? 1))
    const talking = shot.lines.filter(line => line.kitId === cast.kitId && line.visible !== false)
      .map(line => [line.start, line.end] as [number, number])
    const mounted = mountCast(kit, { ...cast, z }, base, shot.duration, viewport, shot.workspace, talking)
    mouthIds.set(cast.kitId, mounted.mouthIds)
    layers.push(...mounted.layers)
  })
  if (layered) layers.push(...setLayers(shot, true, Math.max(0, ...layers.map(layer => layer.z)) + 1, 1))
  if (shot.camera === 'push') layers.push(cameraLayer(shot.duration))
  const dialogueBeats = shot.lines.map(line => lineBeat(line, mouthIds.get(line.kitId) ?? []))
  return {
    version: 1, name: shot.name, width: shot.width, height: shot.height, fps: shot.fps, duration: round(shot.duration),
    generationPolicy: 'provided_only',
    layers: rebuildCutoutDialogueLayers(layers, dialogueBeats, shot.fps, shot.duration),
    audioTracks: [...shot.lines.map(speechTrack), ...(shot.audioTracks ?? [])], dialogueBeats,
    // Music and effects dip while someone speaks, as in Video 3D.
    ...(shot.lines.length ? { audioMix: { duckDb: DIALOGUE_DUCK_DB } } : {}),
    ...(shot.texts?.length ? { texts: shot.texts } : {}),
    ...(shot.sfx?.length ? { sfx: shot.sfx } : {}),
    ...(shot.finish ? { finish: shot.finish } : {}),
    ...(shot.narrative ? { narrative: shot.narrative } : {}),
  } as Scene
}

// Scene operations on an existing document (scenes.video2d.edit) ------------------------------

function kitPoseLayers(scene: Scene, kitId: string) {
  return scene.layers.filter(layer => layer.characterKitRef?.id === kitId && !layer.faceBinding && layer.type === 'image')
}

function mouthIdsFor(scene: Scene, poseLayerId: string) {
  return scene.layers.filter(layer => layer.faceBinding?.role === 'mouth' && layer.faceBinding.poseLayerId === poseLayerId).map(layer => layer.id)
}

function talkingSpans(scene: Scene, mouthIds: string[]): Array<[number, number]> {
  return (scene.dialogueBeats ?? []).filter(beat => beat.mouthLayerIds.some(id => mouthIds.includes(id)))
    .map(beat => [beat.start, beat.end] as [number, number])
}

/** mount_character: put a Character Kit in the shot at a framing and x position. */
export function mountCharacter(scene: Scene, kit: CharacterKit, request: { poseId?: string; x: number; framing: Framing; z?: number
  motion?: Motion; workspace: string }): Scene {
  if (kitPoseLayers(scene, kit.id).length) throw new Error(`${kit.name} is already in this shot`)
  const aspect = scene.width / scene.height
  const base = personTransform(kit, request.poseId ?? 'base', request.framing, request.x, aspect)
  const z = request.z ?? 20 + 10 * new Set(scene.layers.map(layer => layer.characterKitRef?.id).filter(Boolean)).size
  const mounted = mountCast(kit, { kitId: kit.id, poseId: request.poseId, x: request.x, z, motion: request.motion }, base,
    scene.duration, { width: scene.width, height: scene.height }, request.workspace, [])
  return { ...scene, layers: rebuildCutoutDialogueLayers([...scene.layers, ...mounted.layers], scene.dialogueBeats ?? [], scene.fps ?? 24, scene.duration) }
}

/** add_line: a recorded line for a mounted character: its audio, its beat and its mouth keyframes. */
export function addLine(scene: Scene, line: LineSpec): Scene {
  const pose = kitPoseLayers(scene, line.kitId)[0]
  if (!pose) throw new Error(`Mount ${line.kitId} before adding its lines`)
  if ((scene.dialogueBeats ?? []).some(beat => beat.id === line.id)) throw new Error(`Line ${line.id} already exists`)
  const beats = [...(scene.dialogueBeats ?? []), lineBeat(line, mouthIdsFor(scene, pose.id))].sort((a, b) => a.start - b.start)
  const duration = Math.max(scene.duration, round(line.end + 0.45))
  return animateTalk({ ...scene, duration, dialogueBeats: beats, audioTracks: [...(scene.audioTracks ?? []), speechTrack(line)] })
}

/** animate_talk: rebuild body motion (bob while talking, breath otherwise) and mouths from the beats. */
export function animateTalk(scene: Scene, motion: Motion = 'idle'): Scene {
  const layers = scene.layers.map(layer => {
    if (!layer.characterKitRef || layer.faceBinding || layer.type !== 'image') return layer
    const base = { x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale }
    const talking = talkingSpans(scene, mouthIdsFor(scene, layer.id))
    return { ...layer, animation: { ...layer.animation, duration: scene.duration,
      keyframes: bodyKeyframes(layer.id, base, scene.duration, talking, motion) } }
  })
  return { ...scene, layers: rebuildCutoutDialogueLayers(layers, scene.dialogueBeats ?? [], scene.fps ?? 24, scene.duration) }
}

export type SeriesShotPayload =
  | { mode: 'shot'; kits: Record<string, CharacterKit>; shot: ShotSpec }
  | { mode: 'mount_character'; document: Scene; kit: CharacterKit; request: Parameters<typeof mountCharacter>[2] }
  | { mode: 'add_line'; document: Scene; line: LineSpec }
  | { mode: 'animate_talk'; document: Scene; motion?: Motion }

export function runSeriesShot(payload: SeriesShotPayload): { ok: true; document: Scene } | { ok: false; code: string; message: string } {
  try {
    if (payload.mode === 'shot') return { ok: true, document: compileSeriesShot(payload.kits, payload.shot) }
    if (payload.mode === 'mount_character') return { ok: true, document: mountCharacter(payload.document, payload.kit, payload.request) }
    if (payload.mode === 'add_line') return { ok: true, document: addLine(payload.document, payload.line) }
    if (payload.mode === 'animate_talk') return { ok: true, document: animateTalk(payload.document, payload.motion) }
    return { ok: false, code: 'unknown_mode', message: 'Unknown series shot mode' }
  } catch (error) {
    return { ok: false, code: 'series_shot_failed', message: (error as Error).message }
  }
}
