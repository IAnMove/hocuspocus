import assert from 'node:assert/strict'
import test from 'node:test'
import { NoToneMapping, ACESFilmicToneMapping, NeutralToneMapping, Scene } from 'three'
import { createDefaultScene3DDocument, parseScene3DDocument, cloneScene3DDocument } from '../src/features/scene3d/document.ts'
import { EnvironmentLighting, applyLook } from '../src/features/scene3d/environmentLighting.ts'
import { NEW_SCENE_LIGHTING, NEW_SCENE_LOOK, exposureFactor, parseLighting, parseLook } from '../src/features/scene3d/look.ts'

test('new scenes are lit by the environment with the filmic look', () => {
  const doc = createDefaultScene3DDocument()
  assert.deepEqual(doc.lighting, NEW_SCENE_LIGHTING)
  assert.deepEqual(doc.look, NEW_SCENE_LOOK)
  doc.lighting!.environment.intensity = 2
  assert.equal(createDefaultScene3DDocument().lighting!.environment.intensity, NEW_SCENE_LIGHTING.environment.intensity, 'defaults are not shared')
})

test('a scene saved without lighting or look keeps today\'s rendering', () => {
  const stored = createDefaultScene3DDocument() as Record<string, unknown>
  delete stored.lighting; delete stored.look
  const parsed = parseScene3DDocument(structuredClone(stored))!
  assert.equal('lighting' in parsed, false)
  assert.equal('look' in parsed, false)
})

test('lighting and look survive parse and clone, bounded', () => {
  const doc = createDefaultScene3DDocument()
  doc.lighting = { environment: { source: 'hdri', asset: ' /api/v1/library/files/abc.hdr ', intensity: 9, rotation: -90, background: 'blurred', blur: 3 } }
  doc.look = { toneMapping: 'neutral', exposure: 12, lut: { asset: '/luts/warm.cube', strength: 2 } }
  const parsed = parseScene3DDocument(cloneScene3DDocument(doc))!
  assert.deepEqual(parsed.lighting, { environment: { source: 'hdri', asset: '/api/v1/library/files/abc.hdr', intensity: 4, rotation: 270, background: 'blurred', blur: 1 } })
  assert.deepEqual(parsed.look, { toneMapping: 'neutral', exposure: 4, lut: { asset: '/luts/warm.cube', strength: 1 } })
})

test('unusable blocks are dropped instead of guessing', () => {
  assert.equal(parseLighting({ environment: { source: 'sun' } }), undefined)
  assert.equal(parseLighting('room'), undefined)
  assert.equal(parseLook({ toneMapping: 'reinhard', exposure: 0 }), undefined)
  assert.equal(parseLook({ toneMapping: 'aces', lut: { asset: 'blob:abc' } })?.lut, undefined)
  assert.equal(parseLighting({ environment: { source: 'hdri', asset: 'file:///etc/x.hdr' } })?.environment.asset, undefined)
})

test('the look sets tone mapping and exposure; pixel worlds and old scenes restore the previous grade', () => {
  const renderer = { toneMapping: NoToneMapping, toneMappingExposure: 1 }
  const doc = createDefaultScene3DDocument()
  applyLook(renderer as never, doc)
  assert.equal(renderer.toneMapping, ACESFilmicToneMapping)
  assert.equal(renderer.toneMappingExposure, exposureFactor(NEW_SCENE_LOOK))
  applyLook(renderer as never, { ...doc, look: { toneMapping: 'neutral', exposure: 1 } })
  assert.deepEqual([renderer.toneMapping, renderer.toneMappingExposure], [NeutralToneMapping, 2])
  applyLook(renderer as never, { ...doc, look: undefined })
  assert.deepEqual([renderer.toneMapping, renderer.toneMappingExposure], [NoToneMapping, 1], 'an old scene must not keep the previous look')
  applyLook(renderer as never, { ...doc, look: undefined }, true)
  assert.deepEqual([renderer.toneMapping, renderer.toneMappingExposure], [ACESFilmicToneMapping, 1], 'old cinematic scenes stay ACES at 0 EV')
  applyLook(renderer as never, { ...doc, pixelWorld: { pixelSize: 4, levels: 16 } as never }, true)
  assert.deepEqual([renderer.toneMapping, renderer.toneMappingExposure], [NoToneMapping, 1])
})

test('environment light needs a real renderer; without lighting the scene keeps no environment', () => {
  const scene = new Scene()
  const lighting = new EnvironmentLighting()
  lighting.sync({} as never, scene, createDefaultScene3DDocument())
  assert.equal(scene.environment, null, 'a test double cannot bake the room')
  const doc = createDefaultScene3DDocument(); delete doc.lighting
  lighting.sync({} as never, scene, doc)
  assert.equal(scene.environment, null)
})

test('only scenes with a real model bake the environment; placeholders and effects-only scenes skip it', () => {
  const scene = new Scene()
  const lighting = new EnvironmentLighting()
  const doc = createDefaultScene3DDocument()
  doc.slots = doc.slots.map(slot => ({ ...slot, sourceUrl: '' }))
  let baked = 0
  const renderer = { getRenderTarget() { baked++; return null } }
  lighting.sync(renderer as never, scene, doc)
  assert.equal(baked, 0)
  assert.equal(scene.environment, null)
})
