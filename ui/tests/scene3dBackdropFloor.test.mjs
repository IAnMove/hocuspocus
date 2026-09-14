import assert from 'node:assert/strict'
import test from 'node:test'
import { Mesh, MeshBasicMaterial, PlaneGeometry, Texture, Vector3 } from 'three'
import { BackdropFloor } from '../src/features/scene3d/backdropFloor.ts'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'

function fixture(psx) {
  const texture = new Texture({ width: 600, height: 900 })
  const plate = new Mesh(new PlaneGeometry(6, 10), new MeshBasicMaterial({ map: texture }))
  plate.position.set(1, 3, -12); plate.scale.setScalar(2)
  const floor = new Mesh(new PlaneGeometry(20, 20), new MeshBasicMaterial())
  const doc = createDefaultScene3DDocument()
  doc.slots = [{ id: 'background', slot: 'background', media: 'image', surface: 'cutout', position: [1, 3, -12], scale: 2, rotationY: 0, sourceUrl: '/plate.png', imageLook: psx ? { psx } : undefined }]
  doc.environment = { reflectiveFloor: false, platform: false, bloom: 0, floorStyle: 'backdrop', floorSourceHeight: .42 }
  doc.camera = { family: 'static', eye: [0, 3, 10], look: [0, 2, 0], fov: 45 }
  const world = { floor, slots: new Map([['background', { root: plate }]]) }
  return { doc, texture, floor, plate, world }
}

test('projected floor uses the same artwork and a stable reference camera; switching away restores the original floor', () => {
  const { doc, texture, floor, plate, world } = fixture(), original = floor.material
  const runtime = new BackdropFloor(world)
  runtime.sync(doc)
  const projected = floor.material
  assert.notEqual(projected, original); assert.equal(projected.map, texture)
  const shader = { uniforms: {}, vertexShader: '#include <project_vertex>', fragmentShader: 'void main() {\n#include <map_fragment>\n}' }
  projected.onBeforeCompile(shader, {})
  assert.deepEqual(shader.uniforms.hpGroundEye.value.toArray(), [0, 3, 10])
  assert.deepEqual(shader.uniforms.hpGroundSize.value.toArray(), [6, 10])
  assert.equal(shader.uniforms.hpGroundSourceHeight.value, .42)
  assert.deepEqual(new Vector3(1, 3, -12).applyMatrix4(shader.uniforms.hpGroundInverse.value).toArray(), [0, 0, 0])
  assert.ok(shader.fragmentShader.includes('vec2 hpGroundUv='))
  assert.ok(!shader.fragmentShader.includes('vMapUv'))
  doc.environment.floorSourceHeight = .8
  runtime.sync(doc); assert.equal(floor.material, projected)
  assert.equal(shader.uniforms.hpGroundSourceHeight.value, .8)
  runtime.sync({ ...doc, environment: undefined }); assert.equal(floor.material, original)
  runtime.sync({ ...doc, slots: [], environment: { ...doc.environment, floorColor: '#c0ffee' } })
  assert.equal(floor.material, original); assert.equal(floor.material.color.getHexString(), 'c0ffee')
  runtime.dispose(); floor.geometry.dispose(); original.dispose(); plate.geometry.dispose(); plate.material.dispose(); texture.dispose()
})

test('selective PSX on the backdrop continues onto its floor without changing other materials', () => {
  const { doc, floor, world, plate, texture } = fixture(1.4), original = floor.material
  const runtime = new BackdropFloor(world)
  runtime.sync(doc)
  const shader = { uniforms: {}, vertexShader: '#include <project_vertex>', fragmentShader: 'void main() {\n#include <map_fragment>\n}' }
  floor.material.onBeforeCompile(shader, {})
  assert.ok(shader.uniforms.hpPsxGrid)
  assert.ok(shader.fragmentShader.includes('floor(hpGroundUv * hpPsxGrid)'))
  assert.equal(original.map, null)
  runtime.dispose(); floor.geometry.dispose(); original.dispose(); plate.geometry.dispose(); plate.material.dispose(); texture.dispose()
})
