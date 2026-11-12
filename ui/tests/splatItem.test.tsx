import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { Mesh, Raycaster, Vector3 } from 'three'
import type { Scene3DSlot, Vec3 } from '../src/features/scene3d/types.ts'
import { SPLAT_CLOUD_NAME, SPLAT_FLOOR_NAME, createSplatMount, poseSplatMount, splatFloorWorld } from '../src/features/scene3d/splatItem.ts'
import { liftCastToSplatFloor, splatBackgroundSlot } from '../src/features/scene3d/splatSet.ts'
import { normalizeScene3DSlot } from '../src/features/scene3d/documentSlot.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement, Node: dom.window.Node,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function slot(patch: Partial<Scene3DSlot> = {}): Scene3DSlot {
  return {
    id: 'set-hall', slot: 'background', position: [2, 1, -3], rotationY: 0.4, scale: 3,
    sourceUrl: '/api/v1/file/hall.ply?workspace=w', media: 'splat', clip: null,
    splat: { floorY: 0.25 }, ...patch,
  }
}

test('the splat floor stays horizontal at floorY and does not take the cloud scale', () => {
  const root = createSplatMount()
  poseSplatMount(root, slot())
  const placed = splatFloorWorld(root)
  assert.ok(Math.abs(placed.y - 0.25) < 1e-6, `floor Y ${placed.y}`)
  assert.ok(placed.normalY > 0.99, `floor normal Y ${placed.normalY}`)
  const floor = root.getObjectByName(SPLAT_FLOOR_NAME)
  assert.ok(floor instanceof Mesh)
  assert.equal(floor.visible, true)
  assert.equal(floor.scale.x, 1)
  const material = floor.material
  assert.ok(!Array.isArray(material) && material.opacity === 0 && material.colorWrite === false)
  const cloud = root.getObjectByName(SPLAT_CLOUD_NAME)
  assert.ok(cloud && Math.abs(cloud.scale.x - 3) < 1e-6 && Math.abs(cloud.rotation.y - 0.4) < 1e-6)
  assert.equal(root.scale.x, 1)
  assert.equal(root.rotation.y, 0)
  // Off the shared diagonal of the two triangles, so one hit means the face points up.
  const ray = new Raycaster(new Vector3(2.5, 2, -3.2), new Vector3(0, -1, 0))
  const hits = ray.intersectObject(floor, false)
  assert.equal(hits.length, 1)
  assert.ok(Math.abs(hits[0].point.y - 0.25) < 1e-4)
  const fromBelow = new Raycaster(new Vector3(2.5, -1, -3.2), new Vector3(0, 1, 0))
  assert.equal(fromBelow.intersectObject(floor, false).length, 0)
})

test('a parsed splat keeps its floor and a model drops it', () => {
  const kept = normalizeScene3DSlot(slot())
  assert.equal(kept.media, 'splat')
  assert.deepEqual(kept.splat, { floorY: 0.25 })
  const model = normalizeScene3DSlot({ ...slot(), media: 'model3d' })
  assert.equal(model.media, 'model3d')
  assert.equal(model.splat, undefined)
})

test('a grounded cast stands on the splat floor and a flyer does not', () => {
  const placed = splatBackgroundSlot({ source: '/api/v1/file/hall.ply?workspace=w', splat: true, floorY: 0.4, scale: 2 })
  assert.equal(placed.media, 'splat')
  assert.deepEqual(placed.splat, { floorY: 0.4 })
  assert.equal(placed.scale, 2)
  const lifted = liftCastToSplatFloor([
    { media: 'model3d', grounded: true, position: [1, 0, 0] as Vec3 },
    { media: 'model3d', position: [0, 2, 0] as Vec3 },
    { media: 'model3d', grounded: false, position: [0, 0, 1] as Vec3 },
  ], 0.4)
  assert.deepEqual(lifted[0].position, [1, 0.4, 0])
  assert.equal(lifted[0].grounded, true)
  assert.deepEqual(lifted[1].position, [0, 2, 0])
  assert.equal(lifted[2].grounded, false)
  assert.deepEqual(lifted[2].position, [0, 0, 1])
})

test('the object list names a splat', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { Scene3DObjectList } = await import('../src/features/scene3d/Scene3DObjectList.tsx')
  try {
    render(<Scene3DObjectList slots={[slot({ id: 'hall', slot: 'prop' })]} onSelect={() => undefined} />)
    assert.ok(screen.getByText(/Gaussian splat/))
    assert.ok(screen.getByText('hall'))
  } finally {
    cleanup()
  }
})
