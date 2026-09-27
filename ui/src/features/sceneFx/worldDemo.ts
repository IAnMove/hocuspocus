import { createDefaultScene3DDocument } from '../scene3d/document'
import type { Scene3DDocument, Scene3DSlot } from '../scene3d/types'
import { parseWorldSfx } from './world'

function box(id: string, slot: Scene3DSlot['slot'], position: Scene3DSlot['position'], rotationY = 0, scale = 1): Scene3DSlot {
  return { id, slot, position, rotationY, scale, sourceUrl: '', media: 'model3d', clip: null }
}

export function worldSfxDepthDocument(): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  document.duration = 10
  document.dressing = 'citadel'
  document.camera = {
    family: 'orbit',
    eye: [0, 1.8, 6.2],
    look: [0, 0.95, -0.4],
    fov: 46,
    orbitRadius: 6.2,
    orbitHeight: 1.8,
    orbitTurns: 0.38,
  }
  document.slots = [
    box('subject_1', 'subject_1', [0.7, 0, 1.35], 0.15, 1),
    box('subject_2', 'subject_2', [-0.55, 0, 0.4], -0.4, 1),
    box('column', 'prop', [-1.35, 0, -0.55], 0.3, 2.6),
  ]
  document.worldSfx = parseWorldSfx([
    { id: 'demo-portal', kind: 'portal', start: 0, end: 10, position: { x: 0.05, y: 1.2, z: -1.55 }, scale: 1.7, color: '#bb77ff', seed: 11, sound: true, volume: 0.22 },
    { id: 'demo-circle', kind: 'magic_circle', start: 0, end: 10, position: { x: 0.1, y: 0.02, z: 0.2 }, scale: 1.45, color: '#66e0ff', seed: 23, sound: true, volume: 0.16 },
  ])
  document.sfx = [
    { id: 'demo-speed', kind: 'speedlines', start: 6.2, end: 9.6, x: 50, y: 48, size: 110, intensity: 0.75, color: '#ffffff', seed: 5, sound: false, volume: 0, rotation: 10 },
  ]
  return document
}

export function worldSfxDuelDocument(): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  document.duration = 10
  document.dressing = 'citadel'
  document.camera = {
    family: 'orbit',
    eye: [0.4, 2.1, 7],
    look: [0, 1, 0],
    fov: 44,
    orbitRadius: 7,
    orbitHeight: 2.1,
    orbitTurns: 0.22,
  }
  document.slots = [
    { ...box('subject_1', 'subject_1', [-2.2, 0, 0.2], 1.2, 1), motion: { to: [2.1, 0, 0.4], faceTravel: true } },
    { ...box('subject_2', 'subject_2', [2.2, 0, -0.2], -1.2, 1), motion: { to: [-2.0, 0, 0.1], faceTravel: true } },
  ]
  document.worldSfx = parseWorldSfx([
    { id: 'duel-circle', kind: 'magic_circle', start: 0, end: 10, anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.02, z: 0 } }, scale: 1.2, color: '#66e0ff', seed: 4, sound: true, volume: 0.14 },
    { id: 'duel-aura', kind: 'anime_aura', start: 0, end: 10, anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.9, z: 0 } }, scale: 1, color: '#88aaff', seed: 8, sound: false, volume: 0 },
    { id: 'duel-beam', kind: 'energy_beam', start: 1.2, end: 8.5, anchor: { slotId: 'subject_1', offset: { x: 0, y: 1.15, z: 0.2 } }, target: { slotId: 'subject_2', offset: { x: 0, y: 1.15, z: 0 } }, scale: 1, color: '#66ddff', seed: 19, sound: true, volume: 0.2 },
    { id: 'duel-orb', kind: 'energy_orb', start: 0.4, end: 10, anchor: { slotId: 'subject_2', offset: { x: 0.35, y: 1.3, z: 0 } }, scale: 0.9, color: '#ff88dd', seed: 12, sound: true, volume: 0.12 },
    { id: 'duel-missiles', kind: 'arcane_missiles', start: 2, end: 8, anchor: { slotId: 'subject_2', offset: { x: 0, y: 1.4, z: 0 } }, target: { slotId: 'subject_1', offset: { x: 0, y: 1.1, z: 0 } }, scale: 1, color: '#ffaa66', seed: 27, sound: true, volume: 0.18 },
  ])
  return document
}

export function worldSfxMixedDocument(): Scene3DDocument {
  const document = createDefaultScene3DDocument()
  document.duration = 10
  document.dressing = 'chase-street'
  document.camera = {
    family: 'pursuit',
    eye: [3.4, 1.6, 5.5],
    look: [0, 1, 0],
    fov: 48,
    orbitRadius: 6,
    orbitHeight: 1.5,
    orbitTurns: 0.12,
  }
  document.slots = [
    { ...box('subject_1', 'subject_1', [-4, 0, 0], 1.57, 1), motion: { to: [4.2, 0, 0.3], faceTravel: true } },
    { ...box('subject_2', 'subject_2', [-5.4, 0, 1.1], 1.57, 0.95), motion: { to: [2.8, 0, 1.3], faceTravel: true } },
  ]
  document.worldSfx = parseWorldSfx([
    { id: 'mix-portal', kind: 'summoning_gate', start: 0, end: 10, position: { x: 2.4, y: 1.15, z: -1.1 }, rotation: { x: 0, y: 25, z: 0 }, scale: 1.5, color: '#bb77ff', seed: 6, sound: true, volume: 0.16 },
    { id: 'mix-shock', kind: 'shockwave', start: 3.2, end: 6.4, anchor: { slotId: 'subject_1' }, scale: 1.3, color: '#77ddff', seed: 14, sound: true, volume: 0.2 },
    { id: 'mix-lightning', kind: 'lightning', start: 4, end: 7.5, anchor: { slotId: 'subject_2', offset: { x: 0, y: 1.4, z: 0 } }, target: { slotId: 'subject_1', offset: { x: 0, y: 1.1, z: 0 } }, scale: 1, color: '#cceeff', seed: 31, sound: true, volume: 0.18 },
    { id: 'mix-blast', kind: 'explosion', start: 6.1, end: 8.6, position: { x: 1.6, y: 0.4, z: 0.2 }, scale: 1.4, color: '#ff6a32', seed: 44, sound: true, volume: 0.28 },
  ])
  document.sfx = [
    { id: 'mix-speed', kind: 'speedlines', start: 0.4, end: 10, x: 50, y: 50, size: 130, intensity: 0.9, color: '#ffffff', seed: 2, sound: false, volume: 0, rotation: -8 },
    { id: 'mix-impact', kind: 'manga_impact', start: 3.2, end: 4.1, x: 46, y: 42, size: 70, intensity: 1.1, color: '#ffe066', seed: 9, sound: true, volume: 0.22, rotation: 18 },
  ]
  return document
}

export type WorldSfxDemoId = 'depth' | 'duel' | 'mixed'
export function worldSfxDemoDocument(id: WorldSfxDemoId): Scene3DDocument {
  if (id === 'duel') return worldSfxDuelDocument()
  if (id === 'mixed') return worldSfxMixedDocument()
  return worldSfxDepthDocument()
}
