import { createDefaultScene3DDocument } from './document'
import { createScreenSlot, mediaTemplateDocument } from './mediaTemplates'
import { parseWorldSfx } from '../sceneFx/world'
import type { Scene3DDocument, Scene3DSlotId } from './types'

export const EFFECTS_TEMPLATES = (['reflective-stage', 'character-materialization', 'blast-stage'] as const).map(id => ({
  id, camera: 'establishment' as const, duration: id === 'blast-stage' ? 6 : 8, slots: ['subject_1', 'background', 'prop'] as Scene3DSlotId[],
}))

export function effectsTemplateDocument(id: string): Scene3DDocument | null {
  if (id !== 'reflective-stage' && id !== 'character-materialization' && id !== 'blast-stage') return null
  const doc = createDefaultScene3DDocument(), arrival = id === 'character-materialization', blast = id === 'blast-stage'
  doc.templateId = id; doc.duration = blast ? 6 : 8
  doc.environment = { reflectiveFloor: true, platform: arrival, bloom: blast ? .62 : .48 }
  doc.light = { kind: 'directional', direction: [-.4, -.8, -.6], intensity: blast ? 3.8 : 3.2, color: blast ? '#ffd7b0' : '#e9e3ff' }
  const actor = mediaTemplateDocument('tv-head-walk')!.slots[0]
  actor.position = [0, arrival ? .235 : 0, blast ? 1.15 : 0]; actor.performance = 'idle'; actor.clipPlayback = { start: .15, speed: 1, loop: true }
  if (arrival) actor.appearance = { start: 2, duration: .8, color: '#83e8ff' }
  doc.slots = [actor, { id: 'background', slot: 'background', media: 'image', sourceUrl: '', clip: null,
    position: [0, 0, 0], scale: 1, rotationY: 0, surface: 'environment' }]
  if (arrival) {
    for (const sign of [-1, 1]) {
      const screen = createScreenSlot(`portrait-${sign}`, [sign * 2.5, .7, -1.7], 2.5, 2.5)
      screen.screen!.sourceUrl = '/examples/tv-head-face.png'
      doc.slots.push(screen)
    }
  }
  doc.camera = { family: 'establishment', eye: [arrival ? .15 : blast ? 2.1 : 1.7, blast ? 1.55 : 1.9, arrival ? 7.8 : blast ? 6.2 : 5.3], look: [0, blast ? 0.85 : 1.2, 0], fov: blast ? 40 : 42 }
  doc.worldSfx = parseWorldSfx(blast ? [
    { id: 'blast', kind: 'explosion', start: 1.05, end: 3.4, position: { x: 0, y: .42, z: -.15 }, scale: 1.8, color: '#ff6a32', intensity: 1.35, sound: true, volume: .4 },
    { id: 'ring', kind: 'shockwave', start: 1.12, end: 2.7, position: { x: 0, y: .02, z: -.15 }, scale: 1.9, color: '#ffb068', intensity: 1.15 },
    { id: 'embers', kind: 'sparks', start: 1.2, end: 4.6, position: { x: 0, y: .35, z: -.1 }, scale: 1.3, color: '#ffcc77', intensity: 1.2 },
    { id: 'plume', kind: 'smoke', start: 1.35, end: 6, position: { x: 0, y: .3, z: -.2 }, scale: 1.7, color: '#6b5348', intensity: .85 },
  ] : [
    { id: 'mist', kind: 'smoke', start: 0, end: 8, position: { x: 0, y: .23, z: -.6 }, scale: 1.4, color: '#987dcc', intensity: .65 },
    { id: 'gate', kind: 'summoning_gate', start: arrival ? .7 : 0, end: arrival ? 3.5 : 8, position: { x: 0, y: 1.45, z: -.7 }, scale: 1.6, color: '#b997ff' },
    ...(arrival ? [
      { id: 'strike', kind: 'lightning', start: 1.95, end: 2.55, position: { x: .5, y: 7, z: -.2 }, targetPosition: { x: 0, y: .24, z: 0 }, color: '#a5edff', intensity: 1.5 },
      { id: 'shock', kind: 'shockwave', start: 2, end: 3.4, position: { x: 0, y: .26, z: 0 }, color: '#b997ff', scale: 1.6 },
      { id: 'sparks', kind: 'sparks', start: 2, end: 4.5, position: { x: 0, y: .3, z: 0 }, color: '#f7c186', intensity: 1.3 },
    ] : []),
  ])

  return doc
}
