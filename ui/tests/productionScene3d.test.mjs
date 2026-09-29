import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import test from 'node:test'

function compile(scene3d, duration = 6) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'scripts/production-scene3d.mjs'], {
    cwd: new URL('..', import.meta.url), input: JSON.stringify({ scene3d, duration }), encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

test('runner uses native template with authored camera, atmosphere and moving GLB', () => {
  const doc = compile({ template: 'product-orbit', subject: '/api/v1/file/hero.glb?workspace=movie',
    motion: { to: [2, 0, 0], turnTo: 6.283 }, camera: { family: 'orbit', orbitRadius: 5 },
    atmos: { timeOfDay: 'dawn' } })
  assert.equal(doc.templateId, 'product-orbit')
  assert.equal(doc.duration, 6)
  assert.equal(doc.width, 1280)
  assert.equal(doc.fps, 24)
  assert.equal(doc.slots.length, 1)
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
})
