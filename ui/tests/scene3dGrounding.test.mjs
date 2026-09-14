import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, Texture } from 'three'
import { imageFootprint } from '../src/features/scene3d/imageGrounding.ts'
import { imageCutoutMesh, poseImageCutout } from '../src/features/scene3d/imageCutout.ts'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { parseEnvironment } from '../src/features/scene3d/cinematicSettings.ts'
import { DARK_FANTASY_IDS } from '../src/features/scene3d/darkFantasyIds.ts'
import { CREATIVE_TEMPLATE_IDS } from '../src/features/scene3d/creativeTemplateIds.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'

const width = 32, height = 64
function paddedFeet() {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let y = 6; y < 48; y++) for (let x = 9; x < 23; x++) pixels[(y * width + x) * 4 + 3] = 255
  pixels[(63 * width + 15) * 4 + 3] = 12 // faint shadow must not lower the foot anchor
  return pixels
}

test('feet use opaque content, ignoring transparent PNG padding and faint shadows', () => {
  const foot = imageFootprint(paddedFeet(), width, height)
  assert.deepEqual(foot, { bottom: .25, center: .5, width: 14 / 32 })
  assert.equal(imageFootprint(new Uint8ClampedArray(width * height * 4), width, height), null)
})

test('grounded cutouts trim empty rows, keep pixel scale and move contact shadow with the feet', () => {
  const previous = globalThis.document
  globalThis.document = { createElement: () => ({ getContext: () => ({ drawImage() {}, getImageData: () => ({ data: paddedFeet() }) }) }) }
  try {
    const texture = new Texture({ width, height })
    const slot = { position: [2, 0, -1], scale: 1.5, rotationY: 0, imageLook: { grounded: true, shadow: .5 } }
    const mesh = imageCutoutMesh(slot, texture)
    const shadow = mesh.children.find(child => child.name === 'image-contact-shadow')
    assert.ok(shadow)
    assert.equal(Math.min(...Array.from({ length: 4 }, (_, i) => mesh.geometry.getAttribute('uv').getY(i))), .25)
    for (const scale of [.5, 1.5, 3]) {
      poseImageCutout(mesh, { ...slot, scale, position: [2, 1, -1] })
      const bounds = new Box3().setFromObject(mesh)
      assert.ok(Math.abs(bounds.min.y - 1) < 1e-6)
      assert.ok(Math.abs(bounds.max.y - (1 + 1.5 * scale)) < 1e-6)
      assert.equal(shadow.material.uniforms.opacity.value, .5)
    }
    mesh.geometry.dispose(); mesh.material.dispose(); shadow.geometry.dispose(); shadow.material.dispose(); texture.dispose()
  } finally { globalThis.document = previous }
})

test('grounding options and floor palette remain optional and reject invalid saved values', () => {
  assert.deepEqual(parseImageLook({ grounded: true, shadow: 9 }), { grounded: true, shadow: 1 })
  assert.equal(parseImageLook({ grounded: 'true', shadow: NaN }), undefined)
  const environment = { reflectiveFloor: false, platform: false, bloom: .2, floorStyle: 'tiles', floorColor: '#c0ffee' }
  assert.deepEqual(parseEnvironment(environment), environment)
  assert.equal(parseEnvironment({ ...environment, floorColor: 'invalid' }).floorColor, undefined)
  assert.equal(parseEnvironment({ ...environment, floorSourceHeight: 0 }).floorSourceHeight, .1)
  assert.equal(parseEnvironment({ ...environment, floorSourceHeight: Infinity }).floorSourceHeight, undefined)
})

test('all 50 curated compositions keep planted silhouettes and a gentle level camera', () => {
  assert.equal(CREATIVE_TEMPLATE_IDS.length, 20)
  for (const id of [...DARK_FANTASY_IDS, ...CREATIVE_TEMPLATE_IDS]) {
    const doc = applyScene3DTemplate(id), f = doc.camera.framing
    assert.ok(f)
    assert.equal(f.rollFrom, 0, id); assert.equal(f.rollTo, 0, id); assert.equal(f.orbitTurns ?? 0, 0, id)
    assert.equal(f.from[1], f.to[1], id)
    const hero = doc.slots.find(slot => slot.id === f.targetSlot)
    assert.ok(Math.hypot(...f.to.map((v, i) => (v - f.from[i]) * hero.scale)) <= .7, id)
    assert.deepEqual(f.lookFrom, f.lookTo, id)
    assert.notEqual(doc.environment.floorStyle, 'none', id)
    for (const slot of doc.slots.filter(slot => slot.id !== 'background')) {
      assert.equal(slot.position[1], 0, id); assert.equal(slot.imageLook.grounded, true, id); assert.equal(slot.motion, undefined, id)
    }
  }
})
