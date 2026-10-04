// Native template compilation for the production runner. The window is exported length.
import { readFileSync } from 'node:fs'
import { applyScene3DTemplate, SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { scene3dPlaybackSpeed } from '../src/features/scene3d/clock.ts'
import { adaptAuthoredCameraToFrame, fromPortraitCamera } from '../src/features/scene3d/frameFormat.ts'

const request = JSON.parse(readFileSync(0, 'utf8'))
const config = request.scene3d
const document = config.document ? structuredClone(config.document) : documentFromTemplate(config.template)
if (config.slots) document.slots = config.slots.map(explicitSlot)
if (config.subject) bindSubject(document, config)
if (config.camera) document.camera = { ...document.camera, ...config.camera }
for (const key of ['atmos', 'environment', 'light', 'dressing', 'pixelWorld', 'renderLook', 'rhythm']) {
  if (config[key] !== undefined) document[key] = structuredClone(config[key])
}
applyRequestedFrame(document, config)
const speed = scene3dPlaybackSpeed(config.playbackSpeed ?? document.playbackSpeed)
const authored = Number(request.duration) * speed
if (!(authored > 0) || authored > 600) throw new Error(`duration_exceeds_clock:${request.duration}`)
document.playbackSpeed = speed
document.duration = authored
document.fps = config.fps ?? document.fps
delete document.soundtrack
retargetFraming(document)
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
  const next = { ...current, sourceUrl: config.subject, clip: config.clip ?? current.clip ?? null }
  if (config.motion !== undefined) next.motion = config.motion
  if (config.position !== undefined) next.position = config.position
  if (config.scale !== undefined) next.scale = config.scale
  if (config.rotationY !== undefined) next.rotationY = config.rotationY
  if (config.grounded !== undefined) next.grounded = config.grounded
  document.slots = document.slots.map(slot => slot.id === current.id ? next : slot)
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
