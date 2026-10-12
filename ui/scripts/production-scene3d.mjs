import { DUST_ID, stageRoomSet } from '../src/features/scene3d/roomSet.ts'
// Native template compilation for the production runner. The window is exported length.
import { readFileSync } from 'node:fs'
import { applyScene3DTemplate, SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { scene3dPlaybackSpeed } from '../src/features/scene3d/clock.ts'
import { adaptAuthoredCameraToFrame, fromPortraitCamera } from '../src/features/scene3d/frameFormat.ts'
import { cameraEyeAtTime } from '../src/features/scene3d/camera.ts'
import { stageDioramaSet } from '../src/features/scene3d/dioramaSet.ts'
import { scrollDirection, stageParallaxSet } from '../src/features/scene3d/parallaxSet.ts'
import { isGroundStyle } from '../src/features/scene3d/groundStyles.ts'
import { applyGrade, applyLens, applyNamedLight, copyCamera } from '../src/features/scene3d/modifiers.ts'
import { isCameraTechnique } from '../src/features/scene3d/techniqueTemplates.ts'
import { pictureInModelSlot, turnPicturesToCamera } from '../src/features/scene3d/pictureStandIn.ts'

const SET_BEHIND = 12
const SET_MAX_TURNS = 0.06
const SET_COVER = 2
const WORLD_KEYS = ['dressing', 'atmos', 'environment', 'light', 'worldSfx', 'screenBackdrop', 'pixelWorld']
/** The camera's distance to its subject, as a share of the template's. */
const FRAMES = { close: 0.6, medium: 0.8, wide: 1.35, far: 1.8 }
/** A model is drawn this tall at scale 1; framing offsets are in these units. */
const MODEL_HEIGHT = 1.7
/** The room a nearer frame keeps above the head, and the most it raises the aim above the centre (about the chin). */
const HEADROOM = 0.1
const MAX_LIFT = 0.6
const request = JSON.parse(readFileSync(0, 'utf8'))
const config = request.scene3d
/** Ids of the pictures cast where the template authored a model. */
const standIns = new Set()
const document = config.document ? structuredClone(config.document) : documentFromTemplate(config.template)
// A template drawn for a painted set already hangs its plate where its camera needs it.
const drawnAsSet = document.environment?.floorStyle === 'backdrop'
if (config.slots) document.slots = config.slots.map(explicitSlot)
if (config.subject) bindSubject(document, config)
for (const [key, entry] of Object.entries(config.cast ?? {})) bindCast(document, key, sourced(entry))
if (config.background?.room) stageRoomSet(document, { ...config.background.room, camera: config.roomCamera ?? config.background.room.camera })
else if (config.background) bindBackground(document, sourced(config.background))
if (config.world) takeWorld(document, config)
if (config.camera_template) takeCamera(document, config.camera_template)
if (config.camera) document.camera = { ...document.camera, ...config.camera }
if (config.frame !== undefined) reframe(document, config.frame)
if (config.lens) applyLens(document, config.lens)
if (config.frame !== undefined && (FRAMES[config.frame] ?? Number(config.frame)) < 1) keepHeadInFrame(document)
if (typeof config.light === 'string') applyNamedLight(document, config.light)
for (const key of ['atmos', 'environment', 'light', 'dressing', 'pixelWorld', 'renderLook', 'toon', 'rhythm']) {
  if (config[key] === undefined || (key === 'light' && typeof config.light === 'string')) continue
  document[key] = structuredClone(config[key])
}
applyFloor(document, config)
applyRequestedFrame(document, config)
const speed = scene3dPlaybackSpeed(config.playbackSpeed ?? document.playbackSpeed)
const authored = Number(request.duration) * speed
if (!(authored > 0) || authored > 600) throw new Error(`duration_exceeds_clock:${request.duration}`)
document.playbackSpeed = speed
document.duration = authored
// The room was staged at the template's length: its dust spans the whole shot.
for (const cue of document.worldSfx ?? []) if (cue.id === DUST_ID) cue.end = authored
if (config.grade) applyGrade(document, config.grade)
document.fps = config.fps ?? document.fps
delete document.soundtrack
retargetFraming(document)
if (config.background && !drawnAsSet && document.environment?.floorStyle === 'backdrop') stagePaintedSet(document)
turnPicturesToCamera(document, standIns)
// A ground style, asked by the shot (floor) or named as the set's ground, is drawn by the scene instead of the set's slab.
const groundStyle = isGroundStyle(config.floor) ? config.floor : isGroundStyle(config.background?.ground?.style) ? config.background.ground.style : undefined
if (config.background?.houses) document.slots = [...document.slots, ...stageDioramaSet(document, config.background, { styledGround: Boolean(groundStyle) })]
if (config.background?.layers) document.slots = [...document.slots, ...stageParallaxSet(document, config.background, { scroll: config.scroll, groundStyle })]
if (groundStyle) {
  const { groundScroll: _old, ...environment } = document.environment ?? { reflectiveFloor: false, platform: false, bloom: 0 }
  document.environment = { ...environment, reflectiveFloor: false, floorStyle: groundStyle,
    ...(config.scroll ? { groundScroll: { speed: config.scroll, direction: scrollDirection(document) } } : {}) }
}
// A runner on a scrolling set runs on the spot: the place moves, the cast stays under the camera.
if (config.scroll) for (const slot of document.slots) if (slot.media === 'model3d' && !slot.id.startsWith('set-')) slot.inPlace = true
const parsed = parseScene3DDocument(document)
if (!parsed) throw new Error('Invalid Video 3D document')
process.stdout.write(JSON.stringify(parsed))

function documentFromTemplate(id) {
  if (!SCENE3D_TEMPLATE_IDS.includes(id)) throw new Error(`unknown_template:${id}`)
  return applyScene3DTemplate(id)
}

function explicitSlot(binding, index) {
  const role = index === 0 ? 'subject_1' : index === 1 ? 'subject_2' : 'prop'
  const id = binding.id || role
  return {
    id, slot: role, position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl: '', media: 'model3d', clip: null,
    ...binding, id, slot: binding.slot || role,
  }
}

function bindSubject(document, config) {
  const current = document.slots.find(slot => slot.slot === 'subject_1' || slot.id === 'subject_1')
  if (!current) throw new Error('subject_slot_missing')
  const bound = { ...current, sourceUrl: config.subject, media: subjectMedia(config.subject, current.media), clip: config.clip ?? current.clip ?? null }
  const picture = current.media === 'model3d' && bound.media === 'image'
  const next = picture ? pictureInModelSlot(bound, config) : bound
  if (picture && config.rotationY === undefined) standIns.add(next.id)
  if (config.motion !== undefined) next.motion = config.motion
  if (config.position !== undefined) next.position = config.position
  if (config.scale !== undefined) next.scale = config.scale
  if (config.rotationY !== undefined) next.rotationY = config.rotationY
  if (config.grounded !== undefined) next.grounded = config.grounded
  document.slots = document.slots.map(slot => slot.id === current.id ? next : slot)
}

/** A bare URL is shorthand for { source }. */
function sourced(entry) {
  return typeof entry === 'string' ? { source: entry } : entry
}

/** Bind by object id, else by role when exactly one object has it. The template keeps its camera, props and moves. */
function bindCast(document, key, entry) {
  const byRole = document.slots.filter(slot => slot.slot === key)
  const current = document.slots.find(slot => slot.id === key) ?? (byRole.length === 1 ? byRole[0] : null)
  if (!current && !entry.add) throw new Error(byRole.length > 1 ? `cast_role_ambiguous:${key}` : `cast_slot_missing:${key}`)
  const base = current ?? { id: key, slot: 'prop', position: [0, 0, 0], rotationY: 0, scale: 1, media: 'model3d', clip: null }
  const bound = { ...base, sourceUrl: entry.source, media: subjectMedia(entry.source, base.media), clip: entry.clip ?? base.clip ?? null }
  // A picture in a model's place stands in as a grounded cutout as tall as the model; its scale and look are settled there.
  const picture = base.media === 'model3d' && bound.media === 'image'
  const next = picture ? pictureInModelSlot(bound, entry) : bound
  if (picture && entry.rotationY === undefined) standIns.add(next.id)
  // A generated model is centred on its origin; standing it on its feet keeps its animated legs above the floor.
  if (next.media === 'model3d' && entry.grounded === undefined) next.grounded = true
  for (const field of ['clips', 'motion', 'position', 'scale', 'rotationY', 'grounded', 'rhythm', 'appearance', 'imageLook', 'setItem', 'billboard', 'inPlace']) {
    if (entry[field] !== undefined && !(picture && (field === 'scale' || field === 'imageLook'))) next[field] = structuredClone(entry[field])
  }
  document.slots = current ? document.slots.map(slot => slot.id === current.id ? next : slot) : [...document.slots, next]
}

/** The template's background picture. On a cutout plane it is also projected onto the floor (see applyFloor).
 * The painted set replaces the template's procedural dressing (a street, a stage...) unless the shot asks for one.
 * A diorama set (houses, ground) or a parallax set (layers, ground) keeps its picture as the sky and builds its pieces
 * once the camera is known. */
function bindBackground(document, entry) {
  const slots = document.slots.filter(slot => slot.slot === 'background')
  if (!slots.length) throw new Error('background_slot_missing')
  document.dressing = 'none'
  // An unbound object (a second subject or a prop nobody cast) is an editor placeholder, a plain block:
  // in front of a painted set it would hide the picture.
  document.slots = document.slots.filter(slot => slot.slot === 'background' || slot.sourceUrl || slot.screen?.sourceUrl)
  const built = Boolean(entry.houses || entry.layers)
  const surface = built ? 'environment' : entry.surface
  document.slots = document.slots.map(slot => slot.slot !== 'background' ? slot
    : withoutLoop({ ...slot, sourceUrl: entry.source, media: 'image', ...(surface ? { surface } : {}) }, surface))
  if (built) document.environment = { reflectiveFloor: false, platform: false, bloom: 0, ...document.environment, floorStyle: 'none' }
}

/** The camera nearer to or farther from what it looks at, keeping its angle: a framed camera scales its offsets
 * across and ahead (not its height), an orbit its radius, a fixed eye its distance to the look point. */
function reframe(document, frame) {
  const factor = FRAMES[frame] ?? Number(frame)
  if (!(factor > 0)) throw new Error(`unknown_frame:${frame}`)
  const camera = document.camera
  const nearer = ([x, y, z]) => [x * factor, y, z * factor]
  if (camera.framing) camera.framing = { ...camera.framing, from: nearer(camera.framing.from), to: nearer(camera.framing.to) }
  else if (camera.eyeOffset) camera.eyeOffset = nearer(camera.eyeOffset)
  else if (['orbit', 'product', 'musical', 'follow'].includes(camera.family)) camera.orbitRadius = (camera.orbitRadius ?? 4.2) * factor
  else camera.eye = camera.look.map((at, axis) => at + (camera.eye[axis] - at) * factor)
}

/** A framing camera pushed nearer to a figure's middle loses the head off the top of the frame: aim it a little higher
 * (eye and look together, so the angle holds) until the frame keeps room above the head. Only a camera that looks at
 * the centre itself; one that aims at a chosen point (`lookFrom`/`lookTo`) keeps it. Offsets are in figure units:
 * a figure is MODEL_HEIGHT tall and its centre anchor stands half way up. */
function keepHeadInFrame(document) {
  const camera = document.camera
  const framing = camera.framing
  if (!framing || framing.anchor !== 'center' || framing.lookFrom || framing.lookTo) return
  const top = MODEL_HEIGHT / 2 + HEADROOM
  const lift = (eye, fov) => Math.min(MAX_LIFT, Math.max(0, top - Math.hypot(...eye) * Math.tan((fov * Math.PI) / 360)))
  const fovFrom = framing.fovFrom ?? camera.fov
  const start = lift(framing.from, fovFrom), end = lift(framing.to, framing.fovTo ?? fovFrom)
  if (!start && !end) return
  const up = ([x, y, z], by) => [x, y + by, z]
  camera.framing = { ...framing, from: up(framing.from, start), to: up(framing.to, end), lookFrom: [0, start, 0], lookTo: [0, end, 0] }
}

/** The camera and framing of a camera card (the symmetric of `world`): this shot keeps its duration, cast and place.
 * A `frame` or `lens` given with it applies after; the framing is re-targeted to this shot's subject at the end. */
function takeCamera(document, id) {
  const technique = documentFromTemplate(id)
  if (!isCameraTechnique(id)) throw new Error(`invalid_camera_template:${id}`)
  copyCamera(document, technique)
}

/** A picture moved to the sky no longer scrolls round a cylinder. */
function withoutLoop(slot, surface) {
  if (surface === 'environment') delete slot.loop
  return slot
}

/** The place of another template (its dressing, atmosphere, environment, light and world effects): this template keeps
 * its camera, cast, props and moves and plays them there. The template's own background plate and any object nobody
 * cast go, unless the shot binds a background of its own. */
function takeWorld(document, config) {
  const world = documentFromTemplate(config.world)
  for (const key of WORLD_KEYS) {
    if (world[key] === undefined) delete document[key]
    else document[key] = structuredClone(world[key])
  }
  if (config.background) return
  document.slots = document.slots.filter(slot => slot.slot !== 'background' && (slot.sourceUrl || slot.screen?.sourceUrl))
  const plates = world.slots.filter(slot => slot.slot === 'background' && (slot.sourceUrl || slot.surface === 'environment'))
  document.slots = [...document.slots, ...plates.map(slot => structuredClone(slot))]
}

/** An explicit floor wins; a painted background on a plane gets the projected floor unless the template chose one. */
function applyFloor(document, config) {
  const floorStyle = config.floor ?? (config.background && document.environment?.floorStyle === undefined
    && document.slots.some(slot => slot.slot === 'background' && (!slot.surface || slot.surface === 'cutout')) ? 'backdrop' : undefined)
  if (floorStyle) document.environment = { reflectiveFloor: false, platform: false, ...document.environment, floorStyle }
}

/** Hang the painted set as one big plane facing the camera, 12 m behind what it looks at, so the projected floor
 * continues the picture under the cast. Only for a template not drawn for a painted set (its background is a
 * cylinder or a small plane at the origin). The plane covers the view with room for the camera move (twice the
 * frustum at that distance). */
function stagePaintedSet(document) {
  const background = document.slots.find(slot => slot.slot === 'background')
  if (!background || background.surface === 'environment') return
  // A flat picture holds for a short arc: a wider orbit would swing past its edge into the void.
  const turns = document.camera.orbitTurns
  if (typeof turns === 'number' && Math.abs(turns) > SET_MAX_TURNS) document.camera = { ...document.camera, orbitTurns: Math.sign(turns) * SET_MAX_TURNS }
  // The projected floor is drawn from the camera at mid-shot (backdropFloor.referenceEye), so the plane faces it.
  const eye = cameraEyeAtTime(document.camera, document.duration / 2, document.duration, document.slots)
  const { look, fov } = document.camera
  const [dx, dz] = [look[0] - eye[0], look[2] - eye[2]]
  const flat = Math.hypot(dx, dz) || 1
  const [ux, uz] = [dx / flat, dz / flat]
  const distance = flat + SET_BEHIND
  const half = distance * Math.tan((fov * Math.PI) / 360) * SET_COVER
  // The set is painted at eye level, so its horizon is the picture's middle: that line goes at the camera's eye height,
  // and the painted floor then lies where the cast stands. A cutout stands on its position (its centre is scale
  // above it), so the plane hangs half its height lower.
  const centre = eye[1]
  const plane = { ...background, surface: 'cutout', grounded: false, scale: half, rotationY: Math.atan2(-ux, -uz),
    position: [look[0] + ux * SET_BEHIND, centre - half, look[2] + uz * SET_BEHIND] }
  delete plane.loop
  document.slots = document.slots.map(slot => slot === background ? plane : slot)
}

/** A GLB in a cutout's slot becomes a model and a picture in a model's slot a cutout; anything else keeps the slot's media. */
function subjectMedia(url, media) {
  const path = String(url).split(/[?#]/)[0].toLowerCase()
  if (/\.(glb|gltf)$/.test(path)) return 'model3d'
  if (/\.(png|jpe?g|webp|gif|avif)$/.test(path) && media === 'model3d') return 'image'
  return media
}

function applyRequestedFrame(document, config) {
  if (config.width == null && config.height == null) return
  const width = config.width ?? document.width
  const height = config.height ?? document.height
  const wasPortrait = document.height > document.width
  const wantPortrait = height > width
  if (wasPortrait && !wantPortrait) document.camera = fromPortraitCamera(document.camera)
  else if (!wasPortrait && wantPortrait) document.camera = adaptAuthoredCameraToFrame(document.camera, width, height)
  document.width = width
  document.height = height
}

function retargetFraming(document) {
  const framing = document.camera?.framing
  if (!framing || document.slots.some(slot => slot.id === framing.targetSlot)) return
  const subject = document.slots.filter(slot => slot.slot === 'subject_1')
  const models = document.slots.filter(slot => slot.media === 'model3d')
  const target = subject.length === 1 ? subject[0] : models.length === 1 ? models[0] : null
  if (!target) throw new Error(`framing_target_missing:${framing.targetSlot}`)
  framing.targetSlot = target.id
}
