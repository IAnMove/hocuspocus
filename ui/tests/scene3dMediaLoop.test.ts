import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultMediaScreen, mediaScreenTime, parseMediaScreen } from '../src/features/scene3d/mediaScreen'

test('trimmed back-and-forth motion never re-enters rejected source frames', () => {
  const screen = { ...defaultMediaScreen(), loopRange: [2.4, 6.4] as [number, number], pingPong: true }
  assert.equal(mediaScreenTime(0, 7, screen), 2.4)
  assert.equal(mediaScreenTime(4, 7, screen), 6.4)
  assert.ok(Math.abs(mediaScreenTime(8, 7, screen) - 2.4) < 1e-10)
  for (let time = 0; time < 120; time += 1 / 30) {
    const value = mediaScreenTime(time, 7, screen)
    assert.ok(value >= 2.4 && value <= 6.4)
    assert.ok(Math.abs(value - mediaScreenTime(time + 1 / 30, 7, screen)) <= 1 / 30 + 1e-10)
  }
})

test('consecutive shot clocks match one unbroken animation including reverse seeks', () => {
  const screen = { ...defaultMediaScreen(), start: 2.4, speed: .8, loopRange: [2.4, 6.4] as [number, number], pingPong: true }
  for (const seconds of [0, 4, 1, 8, .1]) {
    assert.equal(mediaScreenTime(seconds, 7, { ...screen, timeOffset: 15 }), mediaScreenTime(seconds + 15, 7, screen))
  }
})

test('loop intervals round-trip and malformed intervals cannot break the clock', () => {
  const screen = { ...defaultMediaScreen(), sourceUrl: '/examples/actor.webm', media: 'video', loopRange: [2.4, 6.4], pingPong: true, timeOffset: 18 }
  assert.deepEqual(parseMediaScreen(JSON.parse(JSON.stringify(screen)))?.loopRange, [2.4, 6.4])
  for (const loopRange of [[4, 2], [0, Infinity], [-1, 4], ['0', 4]]) assert.equal(parseMediaScreen({ ...screen, loopRange })?.loopRange, undefined)
  assert.equal(mediaScreenTime(99, 2, { ...defaultMediaScreen(), loopRange: [3, 4], pingPong: true }), 1.999)
})
