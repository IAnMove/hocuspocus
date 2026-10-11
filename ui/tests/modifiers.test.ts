import assert from 'node:assert/strict'
import test from 'node:test'
import techniques from '../src/features/scene3d/cinematicTechniques.json' with { type: 'json' }
import effects from '../../app/shared/scene_effects.json' with { type: 'json' }
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import {
  CAMERA_FAMILIES, GRADE_FX_PREFIX, GRADE_NAMES, LENS_FOV_RANGE, LENS_NAMES, LIGHT_NAMES, MODIFIERS,
  applyGrade, applyLens, applyNamedLight, copyCamera, gradeCues, tinted,
} from '../src/features/scene3d/modifiers.ts'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'

const CONTRACT_LIGHTS = ['noon', 'golden', 'overcast', 'night', 'neon', 'stage', 'campfire', 'rembrandt', 'butterfly', 'split', 'low_key',
  'high_key', 'candle', 'backlight', 'window', 'moonlight', 'under', 'hard', 'soft', 'dusk', 'dawn']
const CONTRACT_GRADES = ['natural', 'teal_orange', 'bleach', 'noir', 'sepia', 'flashback', 'dream', 'giallo', 'cold', 'warm', 'vhs', 'film']
const CONTRACT_LENSES = ['14mm', '24mm', '35mm', '50mm', '85mm', '135mm', '200mm']
const techniqueById = new Map((techniques as Array<{ id: string; fov: number; light: { direction: number[]; intensity: number; color: string } }>).map(entry => [entry.id, entry]))
const fxKinds = new Set((effects as Array<{ id: string }>).map(item => item.id))

function framed(): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  doc.camera = { family: 'follow', eye: [0, 2, 5], look: [0, 1, 0], fov: 48,
    framing: { targetSlot: 'subject_1', anchor: 'head', from: [0, 0.04, 2.55], to: [0, 0.02, 2.15], fovFrom: 48, fovTo: 30 } }
  doc.sfx = [{ id: 'template-lines', kind: 'speedlines', start: 0, end: 2, x: 50, y: 50, size: 65, intensity: 1, color: '#ffffff', seed: 1, sound: false, volume: 0.25 }]
  return doc
}

test('the tables name every contract light, grade and lens with finite numbers from their technique', () => {
  assert.deepEqual([...LIGHT_NAMES].sort(), [...CONTRACT_LIGHTS].sort())
  assert.deepEqual([...GRADE_NAMES].sort(), [...CONTRACT_GRADES].sort())
  assert.deepEqual([...LENS_NAMES].sort(), [...CONTRACT_LENSES].sort())
  for (const [name, light] of Object.entries(MODIFIERS.lights)) {
    assert.ok(light.direction.length === 3 && light.direction.every(Number.isFinite) && light.intensity > 0 && light.ambient >= 0 && light.ambient <= 4, name)
    if (light.source) {
      const authored = techniqueById.get(light.source)!.light
      assert.deepEqual([light.direction, light.intensity, light.color], [authored.direction, authored.intensity, authored.color], name)
    }
  }
  for (const [name, lens] of Object.entries(MODIFIERS.lenses)) assert.equal(lens.fov, techniqueById.get(lens.source)!.fov, name)
  for (const [name, grade] of Object.entries(MODIFIERS.grades)) {
    assert.ok(['aces', 'agx', 'neutral'].includes(grade.look.toneMapping) && Math.abs(grade.look.exposure) <= 4, name)
    assert.ok(grade.fx.every(cue => fxKinds.has(cue.kind) && cue.intensity >= 0.1 && cue.intensity <= 2), name)
  }
  assert.ok(CAMERA_FAMILIES.has('framing') && !CAMERA_FAMILIES.has('lighting'))
})

test('a named light replaces the sun and sets only the ambient share', () => {
  const doc = framed()
  doc.lighting = { environment: { source: 'hdri', asset: '/sky.hdr', intensity: 2, rotation: 90, background: 'set', blur: 0 } }
  applyNamedLight(doc, 'candle')
  assert.deepEqual(doc.light, { kind: 'directional', direction: [0.35, -0.22, -0.55], intensity: 1.25, color: '#ff9a45' })
  assert.equal(doc.lighting.environment.intensity, 0.08)
  assert.equal(doc.lighting.environment.asset, '/sky.hdr')
  assert.throws(() => applyNamedLight(doc, 'torch'), /unknown_light:torch/)
})

test('a grade sets the look, gels the lamp and replaces only its own effects', () => {
  const doc = framed()
  applyGrade(doc, 'flashback')
  assert.deepEqual(doc.look, { toneMapping: 'agx', exposure: -0.3 })
  assert.deepEqual(doc.sfx!.map(cue => cue.id), ['template-lines', 'grade-vignette', 'grade-film_grain'])
  assert.ok(doc.sfx!.slice(1).every(cue => cue.id.startsWith(GRADE_FX_PREFIX) && cue.start === 0 && cue.end === doc.duration))
  const base = createDefaultScene3DDocument().light.color
  assert.equal(doc.light.color, tinted(base, '#e7d7c4'))
  applyGrade(doc, 'cold')
  assert.deepEqual(doc.sfx!.map(cue => cue.id), ['template-lines'])
  assert.equal(doc.light.color, tinted(base, '#7ea2ff'), 'the second grade tints the lamp, not the first tint')
  applyGrade(doc, 'natural')
  assert.deepEqual(doc.light, createDefaultScene3DDocument().light)
  const parsed = parseScene3DDocument(structuredClone((applyGrade(doc, 'vhs'), doc)))!
  assert.deepEqual(parsed.sfx.map(cue => [cue.kind, cue.intensity]), [['speedlines', 1], ['vhs', 1], ['scanline', 0.6]])
  assert.deepEqual(gradeCues('film', 6).map(cue => [cue.id, cue.end]), [['grade-film_grain', 6]])
  assert.throws(() => applyGrade(doc, 'pastel'), /unknown_grade:pastel/)
})

test('a lens sets the fov and scales the zoom within the parser bounds', () => {
  const doc = framed()
  applyLens(doc, '135mm')
  assert.equal(doc.camera.fov, 18)
  assert.deepEqual([doc.camera.framing!.fovFrom, doc.camera.framing!.fovTo], [18, 11.25])
  assert.deepEqual(doc.camera.framing!.from, [0, 0.04, 2.55])
  const long = framed()
  applyLens(long, '200mm')
  assert.equal(long.camera.framing!.fovTo, LENS_FOV_RANGE[0])
  const plain = createDefaultScene3DDocument()
  applyLens(plain, '14mm')
  assert.equal(plain.camera.fov, 96)
  assert.throws(() => applyLens(plain, '500mm'), /unknown_lens:500mm/)
})

test('a camera card is copied and adapted to the frame format of the shot', () => {
  const technique = framed()
  const wide = createDefaultScene3DDocument()
  copyCamera(wide, technique)
  assert.deepEqual(wide.camera, technique.camera)
  assert.notEqual(wide.camera, technique.camera)
  const tall = createDefaultScene3DDocument()
  tall.width = 720
  tall.height = 1280
  copyCamera(tall, technique)
  assert.equal(tall.camera.frameFormat, 'portrait')
  assert.ok(tall.camera.fov > technique.camera.fov)
  const back = createDefaultScene3DDocument()
  copyCamera(back, tall)
  assert.equal(back.camera.frameFormat, undefined)
  assert.ok(Math.abs(back.camera.fov - technique.camera.fov) < 1e-9)
})

test('a tint multiplies the channels and keeps an unreadable colour', () => {
  assert.equal(tinted('#ffffff', '#7ea2ff'), '#7ea2ff')
  assert.equal(tinted('#fff', '#7ea2ff'), '#7ea2ff')
  assert.equal(tinted('#808080', '#808080'), '#404040')
  assert.equal(tinted('blue', '#ffffff'), 'blue')
})
