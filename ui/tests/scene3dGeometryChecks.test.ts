import assert from 'node:assert/strict'
import test from 'node:test'
import { checkGeometry, geometrySampleTimes, type GeometrySample, type GeometrySlotSample } from '../src/features/scene3d/geometryChecks.ts'

const body = (patch: Partial<GeometrySlotSample> = {}): GeometrySlotSample => ({
  id: 'hero', character: true, ground: 0, onFloor: true, min: [-0.3, 0, -0.2], max: [0.3, 1.7, 0.2], visible: true, ...patch,
})
const shot = (frames: ((t: number) => GeometrySlotSample[]), camera: [number, number, number] = [0, 1.6, 4], duration = 3) =>
  geometrySampleTimes(duration).map((t): GeometrySample => ({ t, camera, slots: frames(t) }))

test('a character standing on the floor in view is fine', () => {
  assert.deepEqual(checkGeometry(shot(() => [body()])), { verdict: 'ok', samples: 13, warnings: [] })
})

test('a character under the floor fails with the time range', () => {
  const report = checkGeometry(shot(t => [body(t >= 1 && t <= 2 ? { min: [-0.3, -0.3, -0.2], max: [0.3, 1.4, 0.2] } : {})]))
  assert.equal(report.verdict, 'fail')
  assert.deepEqual(report.warnings.map(w => [w.code, w.start, w.end]), [['below_floor', 1, 2]])
})

test('floating is reported only past a jump', () => {
  const jump = checkGeometry(shot(t => [body(t >= 1 && t <= 1.25 ? { min: [-0.3, 0.3, -0.2], max: [0.3, 2, 0.2] } : {})]))
  assert.equal(jump.verdict, 'ok')
  const floating = checkGeometry(shot(t => [body(t >= 1 ? { min: [-0.3, 0.3, -0.2], max: [0.3, 2, 0.2] } : {})]))
  assert.deepEqual(floating.warnings.map(w => [w.code, w.severity, w.start]), [['floating', 'watch', 1]])
  assert.equal(checkGeometry(shot(() => [body({ onFloor: false, min: [-0.3, 2, -0.2], max: [0.3, 3.7, 0.2] })])).verdict, 'ok', 'flying on purpose')
})

test('a body through a prop is noted, two props are not', () => {
  const prop = (id: string, x: number): GeometrySlotSample => ({ ...body({ id, character: false }), min: [x - 0.3, 0, -0.3], max: [x + 0.3, 1, 0.3] })
  const report = checkGeometry(shot(() => [body(), prop('table', 0.1)]))
  assert.deepEqual(report.warnings.map(w => [w.code, w.slot, w.other]), [['intersects', 'hero', 'table']])
  assert.equal(checkGeometry(shot(() => [prop('a', 0), prop('b', 0.1)])).verdict, 'ok')
})

test('the camera inside a model fails; a character out of frame is noted after half a second', () => {
  const inside = checkGeometry(shot(() => [body()], [0, 1, 0]))
  assert.equal(inside.verdict, 'fail')
  assert.equal(inside.warnings[0].code, 'camera_inside')
  const out = checkGeometry(shot(t => [body({ visible: t < 2 })]))
  assert.deepEqual(out.warnings.map(w => [w.code, w.start, w.end]), [['out_of_frame', 2, 3]])
  const blink = checkGeometry(shot(t => [body({ visible: t !== 1 })]))
  assert.equal(blink.verdict, 'ok', 'a quarter second out of frame is not worth a warning')
})

test('long shots are sampled at most 240 times and always include the end', () => {
  const times = geometrySampleTimes(600)
  assert.ok(times.length <= 242)
  assert.equal(times[times.length - 1], 600)
  assert.deepEqual(geometrySampleTimes(1), [0, 0.25, 0.5, 0.75, 1])
})
