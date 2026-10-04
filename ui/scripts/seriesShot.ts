// Headless Series shot compiler. The server plans a shot (framing, cast, recorded lines) and this
// module builds the editable Video 2D document with the editor's own Character Kit mounting and
// mouth compiler. It does not save, export or fetch. Layout and limited animation come from the
// "Uncanny Valley" production, where they were tuned by eye on a full episode.
import { mountCharacterKitLayers, type CharacterKit } from '../src/lib/characterKit.ts'
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
  enter?: { fromX: number; start: number; end: number }
  exit?: { toX: number; start: number; end: number }
}
export type LineSpec = {
  id: string; kitId: string; text: string; start: number; end: number; filename: string
  cues?: unknown; driver?: string; visible?: boolean; volume?: number; name?: string
}
export type PropSpec = { id: string; name: string; source: string; x: number; y: number; scale: number; z?: number }
export type ShotSpec = {
  name: string; workspace: string; width: number; height: number; fps: 24 | 30 | 60; duration: number
  framing: Framing; background?: { source: string; kind: 'image' | 'video'; focusX?: number }
  cast: CastSpec[]; lines: LineSpec[]; props?: PropSpec[]
  audioTracks?: NonNullable<Scene['audioTracks']>; texts?: Scene['texts']; sfx?: Scene['sfx']; finish?: Scene['finish']
  camera?: 'static' | 'push'; narrative?: Scene['narrative']
}
type Beat = NonNullable<Scene['dialogueBeats']>[number]

const round = (value: number) => Math.round(value * 1000) / 1000
/** Standing characters: layer scale and eye line (% of frame height) per framing; wide shots stand on FEET. */
export const FRAMING: Record<'wide' | 'two' | 'medium' | 'close', { scale: number; eye: number | null }> = {
  wide: { scale: 0.5, eye: null }, two: { scale: 0.8, eye: 33 }, medium: { scale: 1.22, eye: 33 }, close: { scale: 1.78, eye: 42 },
}
const FEET = 94
export const BACKGROUND_ZOOM: Record<Framing, number> = { wide: 1, two: 1.12, medium: 1.28, close: 1.5, insert: 1, title: 1 }

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

/** Where a standing character goes for a framing: feet on the floor in wide shots, eyes on the line otherwise. */
export function personTransform(kit: CharacterKit, poseId: string, framing: Framing, x: number, aspect: number, boost = 1): Pose {
  const preset = FRAMING[framing === 'insert' || framing === 'title' ? 'wide' : framing]
  const size = poseAsset(kit, poseId)
  const scale = preset.scale * boost
  const height = drawnHeight(size, scale, aspect)
  const y = preset.eye === null ? FEET - height / 2 + height * 0.015 : preset.eye + (0.5 - eyeFraction(kit, poseId, size)) * height
  return { x, y: round(y), scale: round(scale) }
}

/** A perched character's height and the line it sits on (% of frame) per framing, as in 1x01's laptop on its desk. */
export const DIALOGUE_DUCK_DB = 10

export const PERCH: Record<'wide' | 'two' | 'medium' | 'close', { height: number; bottom: number }> = {
  wide: { height: 29, bottom: 70 }, two: { height: 40, bottom: 74 }, medium: { height: 56, bottom: 84 }, close: { height: 76, bottom: 94 },
}

/** Where a perched character and its prop go: the character's bottom on the prop's top surface. */
export function perchTransforms(size: { width: number; height: number }, framing: Framing, x: number, aspect: number,
  perch: NonNullable<CastSpec['perch']>): { character: Pose; prop: Pose } {
  const preset = PERCH[framing === 'insert' || framing === 'title' ? 'wide' : framing]
  const characterWidth = preset.height * (size.width / size.height) / aspect
  const propWidth = characterWidth * (perch.widthRatio ?? 1.45)
  const propAspect = perch.width / perch.height
  const propHeight = propWidth * aspect / propAspect
  const propScale = propAspect < aspect ? propHeight / 100 : propWidth / 100
  const propY = preset.bottom - ((perch.top ?? 0.04) - 0.5) * propHeight
  return { character: { x, y: round(preset.bottom - preset.height / 2), scale: round(preset.height / 100) },
    prop: { x, y: round(propY), scale: round(propScale) } }
}

export function backgroundLayer(background: NonNullable<ShotSpec['background']>, framing: Framing, duration: number): SceneLayer {
  const zoom = BACKGROUND_ZOOM[framing]
  const focus = background.focusX ?? 50
  const span = 50 * (zoom - 1)
  const x = Math.max(50 - span, Math.min(50 + span, 50 - (focus / 100 - 0.5) * 100 * zoom))
  const transform = { x: round(x), y: 50, scale: zoom, opacity: 1, rotation: 0 }
  return {
    id: 'background', name: 'Background', type: background.kind, source: background.source, visible: true, locked: false, z: 0,
    fill: true, parallax: 0.2, transform,
    animation: { start: { ...transform }, end: { ...transform }, duration, curve: 'linear',
      ...(background.kind === 'video' ? { loop: true, offset: 0, speed: 1 } : {}) },
  } as SceneLayer
}

function key(id: string, time: number, pose: Pose, curve: SceneKeyframe['curve'] = 'linear'): SceneKeyframe {
  return { id: `${id}-${Math.round(time * 1000)}`, time: round(time), x: round(pose.x), y: round(pose.y), scale: round(pose.scale),
    opacity: pose.opacity ?? 1, rotation: round(pose.rotation ?? 0), curve }
}

/** Limited animation: a bob and tilt while talking, a slow breath otherwise, a shake in panic, hops on entry. */
export function bodyKeyframes(id: string, base: Pose, duration: number, talking: Array<[number, number]>, motion: Motion = 'idle',
  enter?: CastSpec['enter'], exit?: CastSpec['exit']): SceneKeyframe[] {
  const frames: SceneKeyframe[] = []
  const step = 0.25
  const seed = [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const rest = { ...base, rotation: 0, opacity: 1 }
  if (enter) {
    const from = { ...rest, x: enter.fromX }
    frames.push(key(id, 0, from, 'hold'))
    if (enter.start > 0) frames.push(key(id, enter.start, from, 'ease'))
    // A paper puppet slides with a little hop on every step.
    const hops = Math.max(1, Math.round((enter.end - enter.start) / 0.22))
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

/** One editable Video 2D shot: background, props, mounted cast, recorded lines with mouths, camera and finish. */
export function compileSeriesShot(kits: Record<string, CharacterKit>, shot: ShotSpec): Scene {
  const viewport = { width: shot.width, height: shot.height }
  const aspect = shot.width / shot.height
  const layers: SceneLayer[] = []
  if (shot.background) layers.push(backgroundLayer(shot.background, shot.framing, shot.duration))
  for (const prop of shot.props ?? []) layers.push(propLayer(prop, shot.duration))
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
    const base = cast.transform ?? seat?.character ?? personTransform(kit, cast.poseId ?? 'base', shot.framing, cast.x, aspect, (single ? 1.25 : 1) * (cast.boost ?? 1))
    const talking = shot.lines.filter(line => line.kitId === cast.kitId && line.visible !== false)
      .map(line => [line.start, line.end] as [number, number])
    const mounted = mountCast(kit, { ...cast, z }, base, shot.duration, viewport, shot.workspace, talking)
    mouthIds.set(cast.kitId, mounted.mouthIds)
    layers.push(...mounted.layers)
  })
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
