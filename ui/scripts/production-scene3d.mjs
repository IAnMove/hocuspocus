// Native template compilation for the production runner. The window is exported length.
import { readFileSync } from 'node:fs'
import { applyScene3DTemplate, SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { scene3dPlaybackSpeed } from '../src/features/scene3d/clock.ts'
import { adaptAuthoredCameraToFrame, fromPortraitCamera } from '../src/features/scene3d/frameFormat.ts'
import { cameraEyeAtTime } from '../src/features/scene3d/camera.ts'
import { stageDioramaSet } from '../src/features/scene3d/dioramaSet.ts'
import { stageParallaxSet } from '../src/features/scene3d/parallaxSet.ts'

const SET_BEHIND = 12
const SET_MAX_TURNS = 0.06
const SET_COVER = 2
const WORLD_KEYS = ['dressing', 'atmos', 'environment', 'light', 'worldSfx', 'screenBackdrop', 'pixelWorld']
/** The camera's distance to its subject, as a share of the template's. */
const FRAMES = { close: 0.6, medium: 0.8, wide: 1.35, far: 1.8 }
/** Named lights: the sun (direction it travels, strength, colour) and the ambient share. */
const LIGHTS = {
  noon: { direction: [-0.2, -1, -0.3], intensity: 1.5, color: '#fffaf0', ambient: 0.35 },
  golden: { direction: [-0.85, -0.3, -0.4], intensity: 1.35, color: '#ffc98a', ambient: 0.28 },
  overcast: { direction: [-0.15, -1, -0.2], intensity: 0.75, color: '#e6edf5', ambient: 0.6 },
  night: { direction: [0.35, -0.75, -0.45], intensity: 0.5, color: '#9fb6ff', ambient: 0.12 },
  neon: { direction: [0.55, -0.5, -0.65], intensity: 1.0, color: '#ff6fd8', ambient: 0.3 },
  stage: { direction: [0, -0.8, -0.6], intensity: 1.8, color: '#ffffff', ambient: 0.08 },
  campfire: { direction: [0.25, -0.35, -0.9], intensity: 1.1, color: '#ff9b45', ambient: 0.1 },
}
const request = JSON.parse(readFileSync(0, 'utf8'))
const config = request.scene3d
const document = config.document ? structuredClone(config.document) : documentFromTemplate(config.template)
// A template drawn for a painted set already hangs its plate where its camera needs it.
const drawnAsSet = document.environment?.floorStyle === 'backdrop'
if (config.slots) document.slots = config.slots.map(explicitSlot)
if (config.subject) bindSubject(document, config)
for (const [key, entry] of Object.entries(config.cast ?? {})) bindCast(document, key, sourced(entry))
if (config.background) bindBackground(document, sourced(config.background))
if (config.world) takeWorld(document, config)
if (config.camera) document.camera = { ...document.camera, ...config.camera }
if (config.frame !== undefined) reframe(document, config.frame)
if (typeof config.light === 'string') lightPreset(document, config.light)
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
document.fps = config.fps ?? document.fps
delete document.soundtrack
retargetFraming(document)
if (config.background && !drawnAsSet && document.environment?.floorStyle === 'backdrop') stagePaintedSet(document)
if (config.background?.houses) document.slots = [...document.slots, ...stageDioramaSet(document, config.background)]
if (config.background?.layers) document.slots = [...document.slots, ...stageParallaxSet(document, config.background)]
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
  const next = { ...current, sourceUrl: config.subject, media: subjectMedia(config.subject, current.media), clip: config.clip ?? current.clip ?? null }
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
  const next = { ...base, sourceUrl: entry.source, media: subjectMedia(entry.source, base.media), clip: entry.clip ?? base.clip ?? null }
  // A generated model is centred on its origin; standing it on its feet keeps its animated legs above the floor.
  if (next.media === 'model3d' && entry.grounded === undefined) next.grounded = true
  for (const field of ['clips', 'motion', 'position', 'scale', 'rotationY', 'grounded', 'rhythm', 'appearance']) {
    if (entry[field] !== undefined) next[field] = structuredClone(entry[field])
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

/** A named light replaces the template's sun and sets the ambient share; the rest of the lighting stays. */
function lightPreset(document, name) {
  const preset = LIGHTS[name]
  if (!preset) throw new Error(`unknown_light:${name}`)
  const { ambient, ...sun } = preset
  document.light = { kind: 'directional', ...sun }
  const environment = { source: 'room', rotation: 0, background: 'set', blur: 0, ...document.lighting?.environment, intensity: ambient }
  document.lighting = { ...document.lighting, environment }
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
