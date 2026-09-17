import assert from 'node:assert/strict'
import test from 'node:test'
import { DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Vector3 } from 'three'
import { imageWindowGeometry, parseImageWindows } from '../src/features/scene3d/imageWindows.ts'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { slotMountKey } from '../src/features/scene3d/backdrop.ts'

test('window openings reveal and select a separate background, while their frame still occludes it', () => {
  const holes = [[[.2, .2], [.8, .2], [.8, .8], [.2, .8]]]
  const front = new Mesh(imageWindowGeometry(.5, holes), new MeshBasicMaterial({ side: DoubleSide }))
  const back = new Mesh(imageWindowGeometry(.5), new MeshBasicMaterial({ side: DoubleSide }))
  back.position.z = -2
  front.updateMatrixWorld(); back.updateMatrixWorld()
  const ray = new Raycaster(new Vector3(0, 0, 5), new Vector3(0, 0, -1))
  assert.equal(ray.intersectObjects([front, back])[0].object, back)
  ray.set(new Vector3(.45, 0, 5), new Vector3(0, 0, -1))
  assert.equal(ray.intersectObjects([front, back])[0].object, front)
  const restored = new Mesh(imageWindowGeometry(.5), front.material)
  ray.set(new Vector3(0, 0, 5), new Vector3(0, 0, -1))
  assert.equal(ray.intersectObjects([restored, back])[0].object, restored)
})

test('multiple window panes keep the mullion solid and retain original image UVs', () => {
  const holes = [
    [[.1, .1], [.45, .1], [.45, .9], [.1, .9]],
    [[.55, .1], [.9, .1], [.9, .9], [.55, .9]],
  ]
  const geometry = imageWindowGeometry(2, holes)
  const mesh = new Mesh(geometry, new MeshBasicMaterial({ side: DoubleSide }))
  const ray = new Raycaster(new Vector3(0, 0, 5), new Vector3(0, 0, -1))
  assert.ok(ray.intersectObject(mesh).length)
  ray.set(new Vector3(-1, 0, 5), new Vector3(0, 0, -1))
  assert.equal(ray.intersectObject(mesh).length, 0)
  const position = geometry.getAttribute('position'), uv = geometry.getAttribute('uv')
  for (let i = 0; i < uv.count; i++) {
    assert.ok(Math.abs(uv.getX(i) - (position.getX(i) / 2 + 1) / 2) < 1e-6)
    assert.ok(Math.abs(uv.getY(i) - (position.getY(i) + 1) / 2) < 1e-6)
  }
})

test('window data survives serialization without altering its input and ignores invalid contours', () => {
  const windows = [[[.1, .2], [.9, .2], [.9, .8], [.1, .8]]]
  const source = { unlit: true, windows }
  const parsed = parseImageLook(JSON.parse(JSON.stringify(source)))
  assert.deepEqual(parsed, source)
  parsed.windows[0][0][0] = .25
  assert.equal(windows[0][0][0], .1)
  for (const invalid of [null, {}, [[]], [[[0, 0], [1, 1]]], [[[NaN, 0], [1, 0], [1, 1]]], [[[0, 0], [1, 1], [2, 2]]]]) {
    assert.equal(parseImageWindows(invalid), undefined)
  }
})

test('native readiness is stable across normalized image-look property order and disabled effects', () => {
  const windows = [[[.1, .2], [.9, .2], [.9, .8], [.1, .8]]]
  const slot = { sourceUrl: '/examples/frame.jpg', media: 'image', surface: 'cutout', imageLook: { unlit: true, windows, psx: 0 } }
  assert.equal(slotMountKey(slot), slotMountKey({ ...slot, imageLook: parseImageLook(slot.imageLook) }))
  assert.notEqual(slotMountKey(slot), slotMountKey({ ...slot, imageLook: { unlit: true } }))
})
