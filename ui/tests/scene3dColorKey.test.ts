import assert from 'node:assert/strict'
import test from 'node:test'
import { MeshBasicMaterial, Texture } from 'three'
import { parseImageColorKey, applyImageColorKey } from '../src/features/scene3d/imageColorKey'
import { applyPsxImageMaterial } from '../src/features/scene3d/imageLook'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document'
import { slotMountKey } from '../src/features/scene3d/backdrop'

test('cleanup is optional, bounded and survives scene save/reopen independently per layer', () => {
  assert.equal(parseImageColorKey(null), undefined)
  assert.equal(parseImageColorKey({ color: 'white' }), undefined)
  assert.deepEqual(parseImageColorKey({ color: '#c4cdbc', tolerance: -1, softness: 0 }), { color: '#c4cdbc', tolerance: 0, softness: .001 })
  assert.deepEqual(parseImageColorKey({ color: '#ffffff', tolerance: NaN, softness: Infinity }), { color: '#ffffff', tolerance: .06, softness: .04 })
  const doc = createDefaultScene3DDocument()
  const slot = { ...doc.slots[0], media: 'image' as const, surface: 'cutout' as const,
    imageLook: { colorKey: { color: '#c4cdbc', tolerance: .08, softness: .03 } } }
  doc.slots = [slot]
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!.slots[0].imageLook, slot.imageLook)
  assert.notEqual(slotMountKey(slot), slotMountKey({ ...slot, imageLook: undefined }))
})

test('cleanup preserves material tint and composes with PSX while multiplying existing alpha', () => {
  const texture = new Texture({ width: 720, height: 1280 })
  const material = new MeshBasicMaterial({ map: texture, color: '#123456' })
  const originalColor = material.color.clone()
  applyPsxImageMaterial(material, texture, 1.4)
  const psxKey = material.customProgramCacheKey()
  applyImageColorKey(material, { color: '#c4cdbc', tolerance: .08, softness: .03 })
  assert.notEqual(material.customProgramCacheKey(), psxKey)
  const shader = { uniforms: {}, fragmentShader: '#include <map_fragment>\n#include <alphatest_fragment>' }
  // Minimal shader fixture exercises the same callback used by both material types.
  material.onBeforeCompile(shader as never, undefined as never)
  assert.ok('hpPsxGrid' in shader.uniforms)
  assert.ok('hpKeyColor' in shader.uniforms)
  assert.ok(shader.fragmentShader.includes('diffuseColor.a *='))
  assert.ok(shader.fragmentShader.includes('texture2D(map, vMapUv)'))
  assert.ok(material.color.equals(originalColor))
  assert.equal(material.transparent, true)
  assert.equal(material.alphaTest, .05)
  material.dispose(); texture.dispose()
})
