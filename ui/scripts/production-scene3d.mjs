// Native template compilation for the production runner; no parallel scene engine.
import { readFileSync } from 'node:fs'
import { applyScene3DTemplate, SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'

const request = JSON.parse(readFileSync(0, 'utf8'))
const config = request.scene3d
let document
if (config.document) document = structuredClone(config.document)
else {
  if (!SCENE3D_TEMPLATE_IDS.includes(config.template)) throw new Error('Unknown Video 3D template')
  document = applyScene3DTemplate(config.template)
}
const slot = binding => ({
  id: 'subject_1', slot: 'subject_1', position: [0, 0, 0], rotationY: 0, scale: 1,
  sourceUrl: '', media: 'model3d', clip: null, ...binding,
})
if (config.slots) document.slots = config.slots.map((binding, index) => slot({
  id: `subject_${index + 1}`, slot: index === 0 ? 'subject_1' : index === 1 ? 'subject_2' : 'prop', ...binding,
}))
if (config.subject) document.slots = [slot({
  ...document.slots.find(s => s.slot === 'subject_1'), sourceUrl: config.subject,
  clip: config.clip ?? null, motion: config.motion, position: config.position ?? [0, 0, 0],
  scale: config.scale ?? 1, rotationY: config.rotationY ?? 0, grounded: config.grounded ?? true,
})]
if (config.camera) document.camera = { ...document.camera, ...config.camera }
if (document.camera.framing && !document.slots.some(s => s.id === document.camera.framing.targetSlot)) delete document.camera.framing
for (const key of ['atmos', 'environment', 'light', 'dressing', 'pixelWorld', 'renderLook']) {
  if (config[key] !== undefined) document[key] = structuredClone(config[key])
}
document.duration = request.duration
document.width = config.width ?? 1280
document.height = config.height ?? 720
document.fps = config.fps ?? 24
document.playbackSpeed = 1
delete document.soundtrack // The production montage owns the song.
const parsed = parseScene3DDocument(document)
if (!parsed) throw new Error('Invalid Video 3D document')
process.stdout.write(JSON.stringify(parsed))
