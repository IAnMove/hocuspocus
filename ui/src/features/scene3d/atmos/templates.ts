import { createDefaultScene3DDocument } from '../document.ts'
import type { Scene3DDocument, Scene3DSlotId, Scene3DTemplateId } from '../types.ts'
import { ATMOS_TEMPLATE_IDS, type AtmosTemplateId } from './templateIds.ts'
import { BACKLIGHT_EYE, BACKLIGHT_LOOK, CLEARING_EYE, CLEARING_LOOK, CLEARING_SUBJECT } from './layout.ts'
import { parseAtmosSettings } from './params.ts'

export const ATMOS_TEMPLATES: readonly { id: AtmosTemplateId; camera: 'establishment'; duration: number; slots: Scene3DSlotId[] }[] = [
  { id: 'atmos-clearing-wide', camera: 'establishment', duration: 10, slots: ['subject_1'] },
  { id: 'atmos-clearing-backlight', camera: 'establishment', duration: 10, slots: ['subject_1'] },
]
export const ATMOS_CATEGORIES = {
  'atmos-clearing-wide': 'cinema',
  'atmos-clearing-backlight': 'cinema',
} as const

const SHOTS = {
  'atmos-clearing-wide': { eye: CLEARING_EYE, look: CLEARING_LOOK, fov: 42 },
  'atmos-clearing-backlight': { eye: BACKLIGHT_EYE, look: BACKLIGHT_LOOK, fov: 40 },
} as const

export function atmosTemplateDocument(id: string): Scene3DDocument | null {
  if (!(ATMOS_TEMPLATE_IDS as readonly string[]).includes(id)) return null
  const shot = SHOTS[id as AtmosTemplateId]
  const doc = createDefaultScene3DDocument()
  doc.templateId = id as Scene3DTemplateId
  doc.duration = 10
  doc.fps = 24
  doc.width = 1920
  doc.height = 1080
  doc.dressing = 'atmos-clearing'
  doc.atmos = parseAtmosSettings({ timeOfDay: 'golden', fogDensity: 0.58, wind: 0.46, motes: 0.72, palette: 'green' })
  doc.environment = { reflectiveFloor: false, platform: false, bloom: 0.32, floorStyle: 'none' }
  doc.light = { kind: 'directional', direction: [0.82, -0.55, 0.16], intensity: 1.35, color: '#ffd39a' }
  doc.camera = { ...doc.camera, family: 'establishment', eye: shot.eye, look: shot.look, fov: shot.fov }
  doc.slots = [{
    id: 'subject_1', slot: 'subject_1', position: CLEARING_SUBJECT, rotationY: 0.15, scale: 1,
    sourceUrl: '', media: 'model3d', clip: null,
  }]
  return doc
}
