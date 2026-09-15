import assert from 'node:assert/strict'
import test from 'node:test'
import { Texture, NearestFilter } from 'three'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { imageBackdropMesh } from '../src/features/scene3d/gpu.ts'
import { slotMountKey } from '../src/features/scene3d/backdrop.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate, remountScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { filterScene3DTemplates } from '../src/features/scene3d/templateFilters.ts'

test('image appearance round-trips, rejects invalid values and reloads only the changed layer', () => {
  assert.equal(parseImageLook({ tint: 'red', psx: NaN }), undefined)
  assert.deepEqual(parseImageLook({ tint: '#fedcba', psx: 99, unlit: true }), { tint: '#fedcba', psx: 2, unlit: true })
  const doc = createDefaultScene3DDocument()
  const slot = { ...doc.slots[0], media: 'image', surface: 'cutout', imageLook: { tint: '#112233', unlit: true, psx: 1.5 } }
  doc.slots = [slot]
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc))).slots[0].imageLook, slot.imageLook)
  assert.notEqual(slotMountKey(slot), slotMountKey({ ...slot, imageLook: undefined }))
  assert.equal(slotMountKey({ ...slot, surface: 'floor' }), slotMountKey({ ...slot, surface: 'floor', imageLook: undefined }))
})

test('PSX stays on the cutout material; backdrop texture, lighting and opacity remain intact', () => {
  const base = { ...createDefaultScene3DDocument().slots[0], media: 'image' }
  const original = new Texture({ width: 720, height: 1280 })
  const backdrop = imageBackdropMesh(base, original)
  const filter = original.magFilter
  const texture = new Texture({ width: 600, height: 900 })
  const actor = imageBackdropMesh({ ...base, surface: 'cutout', imageLook: { psx: 1.6, tint: '#fafafa', unlit: true } }, texture)
  assert.equal(actor.material.isMeshBasicMaterial, true)
  assert.equal(actor.material.alphaTest, .05)
  assert.equal(texture.magFilter, NearestFilter)
  assert.equal(original.magFilter, filter)
  assert.equal(backdrop.material.transparent, false)
  const shader = { uniforms: {}, fragmentShader: '#include <map_fragment>' }
  actor.material.onBeforeCompile(shader)
  assert.deepEqual(shader.uniforms.hpPsxGrid.value.toArray(), [67, 100])
  assert.ok(shader.fragmentShader.includes('diffuseColor *= sampledDiffuseColor'))
  for (const mesh of [actor, backdrop]) { mesh.geometry.dispose(); mesh.material.dispose() }
  original.dispose(); texture.dispose()
})

test('Dark Fantasy includes all variants, PSX narrows it, and vertical presets retain authored framing', () => {
  const input = { category: 'dark-fantasy', setting: 'all', query: '', locale: 'en', titleOf: id => id }
  assert.equal(filterScene3DTemplates(input).length, 30)
  assert.equal(filterScene3DTemplates({ ...input, category: 'psx' }).length, 56)
  assert.equal(filterScene3DTemplates({ ...input, category: 'all', query: 'dark fantasy' }).length, 30)
  const old = createDefaultScene3DDocument()
  const next = remountScene3DTemplate('dark-vertical-ivory-gate', old)
  assert.deepEqual([next.width, next.height], [720, 1280])
  assert.deepEqual(next.camera, applyScene3DTemplate(next.templateId).camera)
  const wide = remountScene3DTemplate('dark-cathedral', next)
  assert.deepEqual([wide.width, wide.height], [1280, 720])
  const legacy = remountScene3DTemplate('hero-push', next)
  assert.deepEqual([legacy.width, legacy.height], [720, 1280])
})
