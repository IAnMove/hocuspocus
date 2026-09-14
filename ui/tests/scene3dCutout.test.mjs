import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, Texture, Vector3 } from 'three'
import { imageBackdropMesh, poseLoadedSlot } from '../src/features/scene3d/gpu.ts'
import { isCylinderBackdrop, slotMountKey } from '../src/features/scene3d/backdrop.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { parseEnvironment } from '../src/features/scene3d/cinematicSettings.ts'
import fs from 'node:fs'
import { DARK_FANTASY_IDS } from '../src/features/scene3d/darkFantasyIds.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates.ts'

test('transparent portrait cutouts retain aspect, feet and depth after movement and resizing', () => {
  const doc = createDefaultScene3DDocument()
  const slot = { ...doc.slots[0], media: 'image', surface: 'cutout', position: [3, 1, -2], scale: 1.5, rotationY: 0, loop: { cylinder: true, speed: 1 } }
  const texture = new Texture({ width: 600, height: 900 })
  const mesh = imageBackdropMesh(slot, texture)
  const bounds = new Box3().setFromObject(mesh)
  assert.ok(Math.abs(bounds.getSize(new Vector3()).x - 2) < 1e-6)
  assert.equal(bounds.min.y, 1)
  assert.equal(bounds.max.y, 4)
  assert.equal(mesh.material.transparent, true)
  assert.equal(mesh.material.depthWrite, true)
  assert.equal(mesh.material.alphaTest, .05)
  assert.equal(mesh.material.isMeshStandardMaterial, true)
  assert.deepEqual(texture.repeat.toArray(), [1, 1])
  assert.equal(isCylinderBackdrop(slot), false)
  assert.notEqual(slotMountKey(slot), slotMountKey({ ...slot, surface: 'wall' }))
  poseLoadedSlot({ root: mesh, kind: 'image' }, { ...slot, scale: .5, position: [-2, 4, 1] })
  assert.equal(new Box3().setFromObject(mesh).min.y, 4)
  doc.slots = [slot]
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(doc))).slots[0].surface, 'cutout')
  mesh.geometry.dispose(); mesh.material.dispose(); texture.dispose()
})

test('ordinary backdrops keep their existing landscape geometry and position', () => {
  const slot = { ...createDefaultScene3DDocument().slots[0], media: 'image', position: [0, 0, -5], scale: 1, rotationY: 0 }
  const mesh = imageBackdropMesh(slot, new Texture({ width: 600, height: 900 }))
  assert.equal(mesh.geometry.parameters.width, 2)
  assert.equal(mesh.geometry.parameters.height, 1.125)
  assert.equal(mesh.position.y, 2.2)
  assert.equal(mesh.material.transparent, false)
  mesh.geometry.dispose(); mesh.material.dispose()
})

test('optional floor finishes survive save/reopen and preserve old defaults', () => {
  const base = { reflectiveFloor: true, platform: false, bloom: .3 }
  assert.deepEqual(parseEnvironment(base), base)
  for (const floorStyle of ['tiles', 'mirror', 'none', 'backdrop']) {
    const doc = createDefaultScene3DDocument()
    doc.environment = { ...base, floorStyle }
    assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc))).environment, doc.environment)
  }
  assert.deepEqual(parseEnvironment({ ...base, floorStyle: 'invalid' }), base)
})

test('all fantasy presets reopen with bundled resources and independent camera/effect documents', () => {
  assert.equal(DARK_FANTASY_IDS.length, 30)
  const cameras = new Set()
  for (const id of DARK_FANTASY_IDS) {
    assert.ok(SCENE3D_TEMPLATES.some(template => template.id === id))
    const doc = applyScene3DTemplate(id)
    const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
    assert.ok(parsed)
    assert.equal(parsed.templateId, id)
    assert.equal(parsed.duration, 6)
    assert.ok(parsed.slots.some(slot => slot.surface === 'cutout'))
    assert.ok(parsed.worldSfx.length > 0)
    for (const cue of doc.worldSfx) assert.ok(Number.isFinite(cue.rotation.x))
    for (const slot of parsed.slots) {
      assert.ok(slot.sourceUrl.startsWith('/examples/dark-fantasy/'))
      assert.ok(fs.existsSync(new URL('../public' + slot.sourceUrl, import.meta.url)))
    }
    cameras.add(JSON.stringify(parsed.camera))
    doc.slots[0].position[0] = 999
    assert.notEqual(applyScene3DTemplate(id).slots[0].position[0], 999)
  }
  assert.equal(cameras.size, 20)
})
