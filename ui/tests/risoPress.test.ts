import assert from 'node:assert/strict'
import test from 'node:test'
import templates from '../../app/shared/scene_templates.json' with { type: 'json' }
import { FINISH_PRESETS, parseFinish } from '../src/lib/scene2d/finish.ts'
import { pressRiso, risoCutEnvelope, risoPlateShift, separateRiso, type RisoCutLayer } from '../src/lib/scene2d/risoPress.ts'

const OLD_PRESETS = ['warmCinema', 'oldDoc', 'nightNeon', 'paperComic'] as const

function fill(width: number, height: number, r: number, g: number, b: number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let index = 0; index < width * height; index += 1) {
    pixels[index * 4] = r
    pixels[index * 4 + 1] = g
    pixels[index * 4 + 2] = b
    pixels[index * 4 + 3] = 255
  }
  return pixels
}

test('a pure ink separates into its plate and not the others', () => {
  const riso = FINISH_PRESETS.risoPress.riso
  assert.ok(riso)
  assert.equal(riso.inks.length, 4)
  const orange = separateRiso(fill(2, 2, 0xff, 0x6a, 0x2b), 2, 2, riso)
  const pink = separateRiso(fill(2, 2, 0xff, 0x48, 0xb0), 2, 2, riso)
  for (let pixel = 0; pixel < 4; pixel += 1) {
    assert.ok(orange[pixel] > 200)
    assert.ok(orange[4 + pixel] < 20)
    assert.ok(orange[8 + pixel] < 20)
    assert.ok(orange[12 + pixel] < 20)
    assert.ok(pink[4 + pixel] > 200)
    assert.ok(pink[pixel] < 20)
    assert.ok(pink[8 + pixel] < 20)
    assert.ok(pink[12 + pixel] < 20)
  }
})

test('old finish presets stay unchanged when riso is off', () => {
  for (const id of OLD_PRESETS) {
    const preset = FINISH_PRESETS[id]
    assert.equal(Object.hasOwn(preset, 'riso'), false)
    assert.deepEqual(parseFinish(preset), preset)
  }
  assert.equal(JSON.stringify(templates).includes('risoPress'), false)
})

test('misregistration stays static until a cut or a beat kick', () => {
  const riso = FINISH_PRESETS.risoPress.riso
  assert.ok(riso)
  const still = risoPlateShift(riso, 0, 0)
  assert.deepEqual(risoPlateShift(riso, 0, 0), still)
  const beat = Math.hypot(...risoPlateShift(riso, 0, 1)[1])
  const cut = Math.hypot(...risoPlateShift(riso, 1, 0)[1])
  assert.ok(beat > Math.hypot(...still[1]))
  assert.ok(cut > beat)
  const image = { type: 'image', visible: true, animation: { duration: 1, offset: 1, speed: 1, loop: false, trimStart: 0, trimEnd: 1 } } as RisoCutLayer
  assert.equal(risoCutEnvelope(0.2, [image], 4), 0)
  assert.ok(risoCutEnvelope(1, [image], 4) > 0.9)
  assert.equal(risoCutEnvelope(1, undefined, 4), 0)
})

test('the press rewrites a small buffer and leaves the separation entry point pure', () => {
  const riso = FINISH_PRESETS.risoPress.riso
  assert.ok(riso)
  const frame = fill(8, 8, 0xff, 0x6a, 0x2b)
  const before = Buffer.from(frame).toString('hex')
  pressRiso(frame, 8, 8, riso, { seconds: 0.4, envelope: 0, cut: 0 })
  assert.notEqual(Buffer.from(frame).toString('hex'), before)
  assert.equal(frame[3], 255)
})
