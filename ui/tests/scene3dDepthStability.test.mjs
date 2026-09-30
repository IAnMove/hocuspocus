import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, BoxGeometry, Group, Mesh, MeshBasicMaterial, PlaneGeometry } from 'three'
import { stabilizeGroundDepth, stabilizeSurfaceDepth, stabilizeSceneSurfaces } from '../src/features/scene3d/depthStability.ts'
import { BackdropFloor } from '../src/features/scene3d/backdropFloor.ts'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'

test('the automatic floor stays below an imported solid floor whose top is Y=0', () => {
  const ground = new Mesh(new PlaneGeometry(20, 20), new MeshBasicMaterial())
  ground.rotation.x = -Math.PI / 2
  const imported = new Mesh(new BoxGeometry(8, .12, 8), new MeshBasicMaterial())
  imported.position.y = -.06
  stabilizeGroundDepth(ground)
  assert.ok(new Box3().setFromObject(ground).max.y < new Box3().setFromObject(imported).max.y)
  assert.equal(ground.material.depthTest, true)
  assert.equal(ground.material.depthWrite, true)
  assert.ok(ground.material.polygonOffsetFactor > 0)
  assert.ok(ground.material.polygonOffsetUnits > 0)
  const y = ground.position.y
  for (let frame = 0; frame < 240; frame++) stabilizeGroundDepth(ground)
  assert.equal(ground.position.y, y)
})

test('coplanar floor and wall layers have deterministic priority without moving geometry', () => {
  const a = new Mesh(new PlaneGeometry(), new MeshBasicMaterial())
  const b = new Mesh(new PlaneGeometry(), [new MeshBasicMaterial(), new MeshBasicMaterial()])
  const root = new Group(); root.add(b)
  const before = b.matrix.clone()
  stabilizeSurfaceDepth(a, 1); stabilizeSurfaceDepth(root, 2)
  assert.ok(b.material.every(m => m.polygonOffsetUnits < a.material.polygonOffsetUnits))
  assert.ok(b.matrix.equals(before))
  assert.ok(b.material.every(m => m.depthTest && m.depthWrite))
  stabilizeSurfaceDepth(root, 1)
  assert.ok(b.material.every(m => m.polygonOffsetUnits === a.material.polygonOffsetUnits))
})

test('floor material replacement and visibility toggles retain protection; actor material stays intact', () => {
  const ground = new Mesh(new PlaneGeometry(), new MeshBasicMaterial())
  const actor = new Mesh(new BoxGeometry(), new MeshBasicMaterial())
  const runtime = new BackdropFloor({ floor: ground, slots: new Map() })
  const doc = createDefaultScene3DDocument()
  runtime.sync({ ...doc, environment: { reflectiveFloor: false, floorStyle: 'none' } })
  assert.equal(ground.visible, false)
  runtime.sync({ ...doc, environment: undefined })
  assert.equal(ground.visible, true)
  assert.ok(ground.material.polygonOffset)
  assert.equal(actor.material.polygonOffset, false)
  ground.material = new MeshBasicMaterial()
  stabilizeGroundDepth(ground)
  assert.ok(ground.material.polygonOffset)
  runtime.dispose()
})

test('late asset loading cannot change surface priority and GLB/cutout materials remain authored', () => {
  const wall = new Mesh(new PlaneGeometry(), new MeshBasicMaterial())
  const actor = new Mesh(new BoxGeometry(), new MeshBasicMaterial())
  const cutout = new Mesh(new PlaneGeometry(), new MeshBasicMaterial())
  const roots = new Map([['wall', { root: wall }], ['actor', { root: actor }], ['cutout', { root: cutout }]])
  const slots = [{ id: 'floor', media: 'image', surface: 'floor' }, { id: 'wall', media: 'image', surface: 'wall' },
    { id: 'actor', media: 'model3d' }, { id: 'cutout', media: 'image', surface: 'cutout' }]
  stabilizeSceneSurfaces(slots, roots)
  const priority = wall.material.polygonOffsetUnits
  roots.set('floor', { root: new Mesh(new PlaneGeometry(), new MeshBasicMaterial()) })
  stabilizeSceneSurfaces(slots, roots)
  assert.equal(wall.material.polygonOffsetUnits, priority)
  assert.equal(actor.material.polygonOffset, false)
  assert.equal(cutout.material.polygonOffset, false)
})
