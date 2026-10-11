import assert from 'node:assert/strict'
import test from 'node:test'
import { MirroredRepeatWrapping, Texture } from 'three'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { stageParallaxSet } from '../src/features/scene3d/parallaxSet.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { imageCutoutMesh } from '../src/features/scene3d/imageCutout.ts'

const SET = { layers: [{ source: '/mid.png', depth: 'mid', foot: 0.1 }, { source: '/near.png', depth: 'near', foot: 0.2 }],
  ground: { source: '/ground.glb', height: 0.2, size: 80 }, key: '#ff00ff' }

const layer = (slots, depth) => slots.find(slot => slot.id === `set-layer-${depth}`)

test('a camera that turns gets a layer tiled wide enough to never show its edge; a still one gets fewer tiles', () => {
  const orbit = applyScene3DTemplate('dance-orbit'); orbit.duration = 6
  const turning = layer(stageParallaxSet(orbit, SET), 'mid')
  assert.ok(turning.imageLook.tiles >= 3, `tiles ${turning.imageLook.tiles}`)
  const still = layer(stageParallaxSet(applyScene3DTemplate('cine-two-shot'), SET), 'mid')
  assert.ok((still.imageLook.tiles ?? 1) < turning.imageLook.tiles)
})

test('layers sink a little into the ground under their painted feet, and the near layer stands on the floor', () => {
  const slots = stageParallaxSet(applyScene3DTemplate('cine-two-shot'), SET)
  const mid = layer(slots, 'mid'), near = layer(slots, 'near')
  const height = slot => slot.scale * 2
  assert.ok(mid.position[1] <= -(0.1 + 0.05) * height(mid) + 1e-9, 'the mid layer is lowered by its foot and sunk')
  assert.ok(near, 'a static medium shot keeps its near layer')
  assert.ok(near.position[1] <= -(0.2 + 0.05) * height(near) + 1e-9 && near.position[1] > -height(near), 'the near layer stands on the floor, not under the line of sight')
  assert.equal(mid.drift, undefined)
})

test('scroll slides every layer and the ground past the cast, turning the ground to the view, and parsing keeps it', () => {
  const doc = applyScene3DTemplate('cine-two-shot')
  const slots = stageParallaxSet(doc, SET, { scroll: 2 })
  for (const slot of slots) assert.ok(typeof slot.drift === 'number' && slot.drift > 0, slot.id)
  const ground = slots.find(slot => slot.id === 'set-ground'), mid = layer(slots, 'mid'), near = layer(slots, 'near')
  assert.ok(ground.drift < mid.drift && mid.drift < near.drift, 'the same speed turns a wide slab less than a near tile')
  assert.ok(Math.abs(ground.rotationY - mid.rotationY) < 1e-9, 'the slab faces the camera so its texture runs along the view')
  assert.ok(stageParallaxSet(doc, SET, { scroll: -2 }).find(slot => slot.id === 'set-ground').drift < 0)
  doc.slots = [...doc.slots, ...slots]
  const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.equal(layer(parsed.slots, 'mid').drift, mid.drift)
  assert.equal(layer(parsed.slots, 'mid').imageLook.tiles, mid.imageLook.tiles)
  assert.equal(parsed.slots.find(slot => slot.id === 'set-ground').drift, ground.drift)
})

test('a tiled cutout is as wide as its tiles, keeps the original copy in the middle and wraps its texture mirrored', () => {
  const texture = new Texture(); texture.image = { width: 1664, height: 928 }
  const slot = { id: 'x', slot: 'prop', media: 'image', surface: 'cutout', sourceUrl: '/layer.png', clip: null, position: [0, 0, 0], rotationY: 0, scale: 1,
    imageLook: { unlit: true, tiles: 3 } }
  const mesh = imageCutoutMesh(slot, texture)
  mesh.geometry.computeBoundingBox()
  const width = mesh.geometry.boundingBox.max.x - mesh.geometry.boundingBox.min.x
  assert.ok(Math.abs(width - 2 * (1664 / 928) * 3) < 1e-6)
  assert.equal(texture.wrapS, MirroredRepeatWrapping)
  const uv = mesh.geometry.getAttribute('uv')
  let low = Infinity, high = -Infinity
  for (let i = 0; i < uv.count; i++) { low = Math.min(low, uv.getX(i)); high = Math.max(high, uv.getX(i)) }
  assert.ok(Math.abs(low + 1) < 1e-9 && Math.abs(high - 2) < 1e-9, 'uv runs -1..2: the middle tile is the picture itself')
  const plain = imageCutoutMesh({ ...slot, imageLook: { unlit: true } }, new Texture())
  plain.geometry.computeBoundingBox()
  assert.ok(Math.abs(plain.geometry.boundingBox.max.x - plain.geometry.boundingBox.min.x - 2) < 1e-6)
})
