import assert from 'node:assert/strict'
import test from 'node:test'
import { DoubleSide, Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildRetroRoom } from '../src/features/scene3d/atmos/sets/retroRoom.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { projectPoint } from '../src/features/scene3d/camera.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'cream', timeOfDay: 'dim', variant: 3, ...patch }, 'atmos-retro-room'), quality, 'atmos-retro-room')
}

function places(mesh) {
  const matrix = new Matrix4()
  const spots = []
  for (let i = 0; i < mesh.count; i += 1) {
    mesh.getMatrixAt(i, matrix)
    spots.push([matrix.elements[12], matrix.elements[13], matrix.elements[14]])
  }
  return spots
}

function outsideLane(x, z) {
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  const inCircle = dx * dx + dz * dz < 1.4 * 1.4
  const inLane = z > -1.15 && z < 3.5 && x > -1.05 && x < 1.7
  return !inCircle && !inLane
}

function framed(point, eye, look, fov) {
  const hit = projectPoint(point, eye, look, fov, 16 / 9)
  assert.ok(hit, `${point.join(',')} is behind the camera`)
  assert.ok(hit.x > 0.04 && hit.x < 0.96, `${point.join(',')} x ${hit.x.toFixed(3)}`)
  assert.ok(hit.y > 0.04 && hit.y < 0.96, `${point.join(',')} y ${hit.y.toFixed(3)}`)
  return hit
}

test('retro room templates keep cream, dim light, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-retro-room-wide')
  const low = atmosTemplateDocument('atmos-retro-room-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-retro-room')
    assert.equal(doc.atmos?.timeOfDay, 'dim')
    assert.equal(doc.atmos?.palette, 'cream')
    assert.equal(doc.atmos?.variant, 3)
    assert.deepEqual([...doc.light.direction], [0.08, -0.92, -0.18])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.16, 1.52, 2.18])
  assert.equal(wide.camera.fov, 56)
  assert.deepEqual([...low.camera.eye], [0.28, 0.44, 1.72])
  assert.equal(low.camera.fov, 62)
  assert.equal(settingFromDressing('atmos-retro-room'), 'room')
  assert.equal(parseAtmosSettings({ palette: 'cream', timeOfDay: 'on', variant: 20 }, 'atmos-retro-room')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'mauve', variant: -1 }, 'atmos-retro-room')?.variant, 0)
})

test('the CRT, console and controller stay off the lane and read in both shots', () => {
  const first = buildRetroRoom(resolved(), true)
  const again = buildRetroRoom(resolved(), true)
  const screen = first.root.getObjectByName('atmos-screen')
  const crt = places(first.root.getObjectByName('atmos-crt'))
  assert.deepEqual(crt, places(again.root.getObjectByName('atmos-crt')))
  assert.equal(screen.geometry.type, 'PlaneGeometry')
  assert.equal(screen.material.type, 'MeshBasicMaterial')
  assert.equal(first.root.getObjectByName('atmos-wall').material.side, DoubleSide)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  const names = ['atmos-crt', 'atmos-console', 'atmos-controller', 'atmos-games', 'atmos-scan', 'atmos-static', 'atmos-lamp']
  for (const name of names) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  for (const name of ['atmos-poster', 'atmos-window', 'atmos-rug', 'atmos-glow']) {
    const mesh = first.root.getObjectByName(name)
    assert.equal(outsideLane(mesh.position.x, mesh.position.z), true, name)
  }
  const wide = atmosTemplateDocument('atmos-retro-room-wide')
  const low = atmosTemplateDocument('atmos-retro-room-low')
  const marks = [
    [screen.position.x, screen.position.y, screen.position.z],
    places(first.root.getObjectByName('atmos-console'))[0],
    places(first.root.getObjectByName('atmos-controller'))[0],
    [0.72, 0.2, -0.55],
  ]
  for (const doc of [wide, low]) {
    const start = [doc.camera.eye[0], doc.camera.eye[1], doc.camera.eye[2] + 2.2]
    for (const mark of marks) {
      framed(mark, doc.camera.eye, doc.camera.look, doc.camera.fov)
      framed(mark, start, doc.camera.look, doc.camera.fov)
    }
  }
  const floor = first.root.getObjectByName('atmos-floor').geometry.attributes.position
  let minY = Infinity
  let maxY = -Infinity
  let minX = Infinity
  let maxX = -Infinity
  for (let i = 0; i < floor.count; i += 1) {
    minY = Math.min(minY, floor.getY(i))
    maxY = Math.max(maxY, floor.getY(i))
    minX = Math.min(minX, floor.getX(i))
    maxX = Math.max(maxX, floor.getX(i))
  }
  assert.ok(Math.abs(maxY) < 1e-5 && Math.abs(minY) < 1e-5)
  assert.ok(maxX - minX > 4)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('static brightens the CRT and the lamp turns on', () => {
  const built = buildRetroRoom(resolved(), true)
  const screen = built.root.getObjectByName('atmos-screen')
  const scan = built.root.getObjectByName('atmos-scan')
  const snow = built.root.getObjectByName('atmos-static')
  const lamp = built.root.getObjectByName('atmos-lamp')
  built.handle.sync(0, {}, {}, 'low', 3, resolved({ variant: 0 }))
  const calmScreen = screen.material.color.r
  const calmScan = scan.material.color.r
  const calmSnow = snow.instanceColor.getX(0)
  const parked = places(snow).map(spot => spot[1])
  const dimLamp = lamp.material.color.r
  built.handle.sync(1.4, {}, {}, 'low', 3, resolved({ variant: 8, timeOfDay: 'on' }))
  assert.ok(screen.material.color.r > calmScreen)
  assert.ok(scan.material.color.r < calmScan)
  assert.ok(snow.instanceColor.getX(0) > calmSnow)
  assert.ok(places(snow).some((spot, index) => spot[1] !== parked[index]))
  assert.ok(lamp.material.color.r > dimLamp)
  const calm = buildRetroRoom(resolved({ variant: 0 }), true)
  assert.ok(calm.root.getObjectByName('atmos-screen').material.color.r < screen.material.color.r)
  const mauve = buildRetroRoom(resolved({ palette: 'mauve', timeOfDay: 'on' }, 'high'), true)
  assert.equal(mauve.root.getObjectByName('atmos-static').count, 36)
  assert.equal(mauve.root.getObjectByName('atmos-scan').count, 10)
  assert.notEqual(mauve.root.getObjectByName('atmos-wall').material.color.getHex(), built.root.getObjectByName('atmos-wall').material.color.getHex())
  assert.equal(mauve.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  mauve.handle.dispose()
})

test('retro room degrades to a flat floor without WebGL2', () => {
  const flat = buildRetroRoom(resolved(), false)
  assert.equal(flat.root.name, 'atmos-retro-room')
  assert.equal(flat.root.getObjectByName('atmos-screen'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-console'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-controller'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-retro-room-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [202, 187, 171])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
