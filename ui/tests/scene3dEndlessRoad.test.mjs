import assert from 'node:assert/strict'
import test from 'node:test'
import { Object3D, Scene, Vector3 } from 'three'
import { EndlessRoad, parseEndlessRoad, roadPhase } from '../src/features/scene3d/endlessRoad.ts'
import { parseEnvironment } from '../src/features/scene3d/cinematicSettings.ts'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { poseImageCutout } from '../src/features/scene3d/imageCutout.ts'

test('the road keeps its phase across edits, seeks and consecutive shots', () => {
  const road = new EndlessRoad(new Scene()), settings = { speed: 4, slope: 12, offset: 0 }
  road.sync(true, settings, 3.4)
  const end = road.mesh.material.uniforms.phase.value
  road.sync(true, { ...settings, offset: 3.4 }, 0)
  assert.equal(road.mesh.material.uniforms.phase.value, end)
  road.sync(true, settings, 1)
  assert.equal(road.mesh.material.uniforms.phase.value, roadPhase(settings, 1))
  road.mesh.updateMatrixWorld()
  const point = new Vector3(2, 0, 0).applyMatrix4(road.mesh.matrixWorld)
  assert.ok(Math.abs(point.y / point.x - Math.tan(12 * Math.PI / 180)) < 1e-6)
  road.sync(false, settings, 0); assert.equal(road.mesh.visible, false)
  road.dispose(); assert.equal(road.mesh.parent, null)
})

test('road settings survive documents and reject non-finite or excessive inputs', () => {
  const road = { speed: -4, slope: 12, offset: 3.4 }
  assert.deepEqual(parseEnvironment({ floorStyle: 'road', road }).road, road)
  assert.equal(parseEnvironment({ floorStyle: 'road', road }).floorStyle, 'road')
  assert.deepEqual(parseEndlessRoad({ speed: Infinity, slope: 90, offset: -99999 }), { speed: 3, slope: 35, offset: -36000 })
  assert.equal(parseEnvironment({}).road, undefined)
})

test('tilted cutouts keep their foot anchor at every scale and yaw', () => {
  const root = new Object3D(), position = [2, -.4, 1]
  for (const scale of [.5, 2, 4]) for (const rotationY of [0, .7, -1]) {
    poseImageCutout(root, { scale, rotationY, position, imageLook: { roll: 12 } })
    root.updateMatrixWorld()
    const foot = new Vector3(0, -1, 0).applyMatrix4(root.matrixWorld)
    assert.ok(foot.distanceTo(new Vector3(...position)) < 1e-6)
  }
  assert.deepEqual(parseImageLook({ roll: 999 }), { roll: 180 })
  assert.equal(parseImageLook({ roll: NaN }), undefined)
})
