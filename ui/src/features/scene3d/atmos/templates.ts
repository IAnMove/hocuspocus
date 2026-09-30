import { createDefaultScene3DDocument } from '../document.ts'
import type { Scene3DDocument, Scene3DSlotId, Scene3DTemplateId } from '../types.ts'
import { ATMOS_TEMPLATE_IDS, type AtmosTemplateId } from './registryIds.ts'
import { atmosTemplate } from './registry.ts'

export const ATMOS_TEMPLATES: readonly { id: AtmosTemplateId; camera: 'establishment'; duration: number; slots: Scene3DSlotId[] }[] =
  ATMOS_TEMPLATE_IDS.map(id => {
    const found = atmosTemplate(id)
    return { id, camera: 'establishment' as const, duration: found?.template.duration ?? 10, slots: ['subject_1'] }
  })

export const ATMOS_CATEGORIES = Object.fromEntries(
  ATMOS_TEMPLATE_IDS.map(id => [id, 'cinema']),
) as { [K in AtmosTemplateId]: 'cinema' }

export function atmosTemplateDocument(id: string): Scene3DDocument | null {
  const found = atmosTemplate(id)
  if (!found) return null
  const { set, template } = found
  const day = set.times[set.defaults.timeOfDay]
  if (!day) return null
  const doc = createDefaultScene3DDocument()
  doc.templateId = id as Scene3DTemplateId
  doc.duration = template.duration
  doc.fps = 24
  doc.width = 1920
  doc.height = 1080
  doc.dressing = set.id as Scene3DDocument['dressing']
  doc.atmos = { ...set.defaults }
  doc.environment = { reflectiveFloor: false, platform: false, bloom: 0.32, floorStyle: 'none' }
  doc.light = { kind: 'directional', direction: day.sun, intensity: 1.35, color: day.sunColor }
  doc.camera = { ...doc.camera, family: 'establishment', eye: template.eye, look: template.look, fov: template.fov }
  doc.slots = [{
    id: 'subject_1', slot: 'subject_1', position: set.subject, rotationY: set.subjectYaw, scale: 1,
    sourceUrl: '', media: 'model3d', clip: null,
  }]
  return doc
}
