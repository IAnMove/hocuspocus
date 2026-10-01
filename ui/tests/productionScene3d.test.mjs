import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'

function compile(scene3d, duration = 6) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'scripts/production-scene3d.mjs'], {
    cwd: new URL('..', import.meta.url), input: JSON.stringify({ scene3d, duration }), encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

test('an unknown template id is rejected instead of becoming the first shot', () => {
  assert.throws(() => applyScene3DTemplate('nope'), /unknown_template:nope/)
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'scripts/production-scene3d.mjs'], {
    cwd: new URL('..', import.meta.url), input: JSON.stringify({ scene3d: { template: 'nope', subject: '/api/v1/file/robot.glb?workspace=movie' }, duration: 6 }), encoding: 'utf8',
  })
  assert.notEqual(result.status, 0)
  assert.match(`${result.stderr}`, /unknown_template:nope/)
})

test('a personal template id survives reopening', () => {
  const doc = compile({ template: 'product-orbit', subject: '/api/v1/file/robot.glb?workspace=movie' })
  doc.templateId = 'user-robot'
  const parsed = parseScene3DDocument(doc)
  assert.equal(parsed.templateId, 'user-robot')
  assert.equal(parsed.slots.some(slot => slot.slot === 'background'), true)
})

test('runner uses native template with authored camera, atmosphere and moving GLB', () => {
  const doc = compile({ template: 'product-orbit', subject: '/api/v1/file/hero.glb?workspace=movie',
    motion: { to: [2, 0, 0], turnTo: 6.283 }, camera: { family: 'orbit', orbitRadius: 5 },
    atmos: { timeOfDay: 'dawn' } })
  assert.equal(doc.templateId, 'product-orbit')
  assert.equal(doc.duration, 6)
  assert.equal(doc.width, 1280)
  assert.equal(doc.fps, 30)
  assert.deepEqual(doc.slots.map(slot => slot.slot), ['subject_1', 'background'])
  assert.equal(doc.slots[0].media, 'model3d')
  assert.equal(doc.slots[0].clip, null)
  assert.equal(doc.slots[0].motion.turnTo, 6.283)
  assert.equal(doc.camera.orbitRadius, 5)
  assert.equal(doc.atmos.timeOfDay, 'dawn')
  assert.equal(doc.soundtrack, undefined)
})

test('explicit slots receive distinct identities and full documents remain editable', () => {
  const doc = compile({ template: 'two-shot', slots: [
    { sourceUrl: '/api/v1/file/a.glb?workspace=movie' },
    { sourceUrl: '/api/v1/file/b.glb?workspace=movie', position: [2, 0, 0] },
  ] })
  assert.notEqual(doc.slots[0].id, doc.slots[1].id)
  const edited = compile({ document: doc, camera: { fov: 40 } }, 8)
  assert.deepEqual(edited.slots, doc.slots)
  assert.equal(edited.camera.fov, 40)
  assert.equal(edited.duration, 8)
})


test('the production compiler preserves the N64 render look on native scenes', () => {
  const doc = compile({ template: 'product-orbit', subject: '/api/v1/file/hero.glb?workspace=movie', renderLook: 'n64' })
  assert.equal(doc.renderLook, 'n64')
  assert.equal(doc.slots[0].media, 'model3d')
  assert.equal(doc.slots[1].slot, 'background')
})

test('named camera shots keep speed, portrait format, framing and the other character hole', () => {
  const dolly = compile({ template: 'cine-dolly-zoom', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(typeof dolly.camera.framing.fovTo, 'number')
  assert.equal(dolly.camera.framing.targetSlot, 'subject_1')
  assert.equal(dolly.slots.find(slot => slot.slot === 'background').sourceUrl, '')
  const renamed = compile({ template: 'cine-dolly-zoom', slots: [
    { id: 'hero-robot', slot: 'subject_1', sourceUrl: '/api/v1/file/robot.glb?workspace=movie' },
    { id: 'backdrop', slot: 'background', media: 'image', sourceUrl: '/api/v1/file/room.png?workspace=movie' },
  ] })
  assert.equal(renamed.camera.framing.targetSlot, 'hero-robot')
  assert.equal(typeof renamed.camera.framing.fovTo, 'number')
  const orbit = compile({ template: 'cine-orbit-360', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(orbit.camera.framing.orbitTurns > 0, true)
  const rain = compile({ template: 'cine-rain', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(rain.worldSfx.some(cue => cue.kind === 'rain'), true)
  const portrait = compile({ template: 'cine-ratio-switch', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(portrait.width, 720)
  assert.equal(portrait.height, 1280)
  const landscape = compile({ template: 'cine-ratio-switch', subject: '/api/v1/file/robot.glb?workspace=movie', width: 1280, height: 720 })
  assert.equal(landscape.width, 1280)
  assert.equal(landscape.height, 720)
  assert.notEqual(landscape.camera.fov, portrait.camera.fov)
  const slow = compile({ template: 'cine-slow-motion', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(slow.playbackSpeed, 0.25)
  assert.equal(slow.duration, 1.5)
  const fast = compile({ template: 'cine-fast-motion', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.equal(fast.playbackSpeed, 2)
  assert.equal(fast.duration, 12)
  const pair = compile({ template: 'two-shot', subject: '/api/v1/file/robot.glb?workspace=movie' })
  assert.deepEqual(pair.slots.map(slot => slot.slot), ['subject_1', 'subject_2', 'background'])
  assert.equal(pair.slots[1].sourceUrl, '')
})
