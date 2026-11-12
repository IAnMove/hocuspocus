import { createDefaultScene3DDocument } from '../document'
import type { Scene3DDocument, Vec3 } from '../types'
import type { Scene3DTemplate, Scene3DTemplateCategory } from '../templates'
import { DEFAULT_MOTION_LAB, isMotionLab, MOTION_LAB_IDS, type MotionLabId } from './types'

type Spec = { duration: number; category: Scene3DTemplateCategory; eye: Vec3; look: Vec3; fov: number }
const SPECS: Record<MotionLabId, Spec> = {
  'motion-bouncing-ball': { duration: 16, category: 'music', eye: [8, 7, 11], look: [0, 1.2, 0], fov: 46 },
  'motion-music-machine': { duration: 20, category: 'music', eye: [7, 6, 10], look: [0, 1.8, 0], fov: 48 },
  'motion-sunset-flight': { duration: 24, category: 'action', eye: [10, 7, 12], look: [0, 3, 0], fov: 48 },
  'motion-seasonal-carriage': { duration: 32, category: 'cinema', eye: [4.8, 3.3, 6.5], look: [0, 1.5, -1.5], fov: 50 },
  'motion-data-assembly': { duration: 32, category: 'product', eye: [8, 6.8, 10], look: [0, 2, 0], fov: 48 },
  'motion-lighthouse-story': { duration: 32, category: 'cinema', eye: [10, 7.8, 13], look: [0, 3, 0], fov: 48 },
  'motion-poster-breakout': { duration: 10, category: 'product', eye: [.5, 2.9, 10.5], look: [0, 2.4, 0], fov: 46 },
  'motion-particle-morph': { duration: 24, category: 'music', eye: [0, 3.2, 11], look: [0, 2.6, 0], fov: 43 },
}
export const MOTION_LAB_TEMPLATES: Scene3DTemplate[] = MOTION_LAB_IDS.map(id => ({
  id, camera: 'fixed', duration: SPECS[id].duration, slots: [], tags: ['creative', 'animated'],
}))
export const MOTION_LAB_CATEGORIES = Object.fromEntries(MOTION_LAB_IDS.map(id => [id, SPECS[id].category])) as Record<MotionLabId, Scene3DTemplateCategory>

export function motionLabTemplateDocument(id: string): Scene3DDocument | null {
  if (!isMotionLab(id)) return null
  const spec = SPECS[id], document = createDefaultScene3DDocument()
  return { ...document, templateId: id, dressing: id, duration: spec.duration, slots: [],
    camera: { family: 'fixed', eye: spec.eye, look: spec.look, fov: spec.fov },
    light: { kind: 'directional', direction: [-.5, -1, -.4], color: '#fff3dc', intensity: 2 },
    motionLab: { ...DEFAULT_MOTION_LAB }, environment: { reflectiveFloor: false, platform: false, bloom: .12, floorStyle: 'none' },
    lighting: { environment: { source: 'room', intensity: .8, rotation: 0, background: 'set', blur: 0 } },
    look: { toneMapping: 'aces', exposure: -.1 },
  }
}
