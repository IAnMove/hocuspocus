import assert from 'node:assert/strict'
import test from 'node:test'
import modifiers from '../../app/shared/world3d_modifiers.json' with { type: 'json' }
import lines from '../../app/shared/video2d_lines.json' with { type: 'json' }
import en from '../src/i18n/locales/en/kineticText.json' with { type: 'json' }
import es from '../src/i18n/locales/es/kineticText.json' with { type: 'json' }
import { FINISH_PRESETS, grainNoise, parseFinish } from '../src/lib/scene2d/finish.ts'
import { applyTone, paintGel, paintScanlines, scanlineBands, toneLut, TONE_CURVES, vhsTape } from '../src/lib/scene2d/finishPieces.ts'

const GRADE_NAMES = Object.keys(modifiers.grades)

function stripes(width: number, height: number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let index = 0; index < width * height; index += 1) {
    const value = (index % width) < width / 2 ? 40 : 220
    pixels.set([value, value * 0.8, 255 - value, 255], index * 4)
  }
  return pixels
}

type Call = [string, ...unknown[]]
function recorder() {
  const calls: Call[] = []
  const state: Record<string, unknown> = {}
  const ctx = new Proxy(state, {
    get: (target, key) => key in target ? target[key as string] : (...args: unknown[]) => { calls.push([String(key), ...args]) },
    set: (target, key, value) => { target[key as string] = value; calls.push([`=${String(key)}`, value]); return true },
  }) as unknown as CanvasRenderingContext2D
  return { ctx, calls }
}

test('the twelve 3D grade names are 2D finishes and the five old ones stay', () => {
  assert.deepEqual(Object.keys(FINISH_PRESETS), ['warmCinema', 'oldDoc', 'nightNeon', 'paperComic', 'risoPress', ...GRADE_NAMES])
  for (const name of GRADE_NAMES) {
    const grade = modifiers.grades[name as keyof typeof modifiers.grades]
    const finish = FINISH_PRESETS[name]
    assert.equal(finish.grade?.curve, grade.look.toneMapping, name)
    assert.equal(finish.gel?.color, 'tint' in grade ? grade.tint : undefined, name)
  }
})

test('every preset survives the scene parser unchanged, so a saved scene reopens with its finish', () => {
  for (const [name, preset] of Object.entries(FINISH_PRESETS)) assert.deepEqual(parseFinish(preset), preset, name)
  const raw = parseFinish({ grade: { exposure: 0, contrast: 0, saturation: 0, temperature: 0, tint: 0, fade: 0, curve: 'reinhard' }, gel: { color: '#ff0000', amount: 4, shadows: 'teal' }, vhs: { amount: -2 }, scanlines: { amount: 0.4 } })
  assert.equal(raw?.grade?.curve, undefined)
  assert.deepEqual(raw?.gel, { color: '#ff0000', amount: 1 })
  assert.deepEqual(raw?.vhs, { amount: 0 })
  assert.equal(parseFinish({ gel: { color: 'red', amount: 1 } }), undefined)
})

test('tone curves shape the picture the way each 3D tone mapper does', () => {
  for (const curve of TONE_CURVES) {
    const lut = toneLut(curve)
    assert.equal(lut[0], 0, curve)
    for (let level = 1; level < 256; level += 1) assert.ok(lut[level] >= lut[level - 1], `${curve} is monotonic at ${level}`)
  }
  const aces = toneLut('aces'), agx = toneLut('agx'), neutral = toneLut('neutral')
  assert.ok(aces[51] < 51 && aces[204] > 204 && aces[255] === 255, 'aces is an S that keeps white: darker shadows, brighter highlights')
  assert.ok(agx[25] > 25 && agx[51] > aces[51] && agx[255] === 255, 'agx lifts the shadows: a softer picture')
  assert.ok(neutral[51] === 51 && neutral[128] === 128 && neutral[255] < 255, 'neutral keeps all but the top, which it rolls off')
  const pixels = new Uint8ClampedArray([51, 128, 204, 255])
  applyTone(pixels, 'aces')
  assert.deepEqual([...pixels], [aces[51], aces[128], aces[204], 255])
})

test('a gel multiplies the frame and its shadow colour lifts the dark parts', () => {
  const { ctx, calls } = recorder()
  paintGel(ctx, 100, 50, FINISH_PRESETS.teal_orange.gel)
  const ops = calls.filter(call => call[0] === '=globalCompositeOperation').map(call => call[1])
  assert.deepEqual(ops, ['multiply', 'screen'])
  assert.deepEqual(calls.filter(call => call[0] === 'fillRect').map(call => call.slice(1)), [[0, 0, 100, 50], [0, 0, 100, 50]])
  const quiet = recorder()
  paintGel(quiet.ctx, 100, 50, { color: '#ff0000', amount: 0 })
  assert.equal(quiet.calls.length, 0)
})

test('scanlines draw about 240 lines and a band that rolls down with time', () => {
  const bands = scanlineBands(720, 0)
  assert.equal(bands.step, 3)
  assert.equal(bands.rows.length, 120)
  assert.ok(scanlineBands(720, 1).roll > bands.roll)
  const { ctx, calls } = recorder()
  paintScanlines(ctx, 1280, 720, 0.5, FINISH_PRESETS.vhs.scanlines)
  assert.equal(calls.filter(call => call[0] === 'fillRect').length, 121)
})

test('vhs tape changes the picture, the same way for the same frame and differently on the next', () => {
  const before = stripes(32, 16)
  const one = stripes(32, 16), again = stripes(32, 16), next = stripes(32, 16)
  vhsTape(one, 32, 16, FINISH_PRESETS.vhs.vhs!.amount, 1)
  vhsTape(again, 32, 16, FINISH_PRESETS.vhs.vhs!.amount, 1)
  vhsTape(next, 32, 16, FINISH_PRESETS.vhs.vhs!.amount, 1.5)
  assert.notDeepEqual(one, before)
  assert.deepEqual(one, again)
  assert.notDeepEqual(one, next)
  const off = stripes(32, 16)
  vhsTape(off, 32, 16, 0, 1)
  assert.deepEqual(off, before)
})

test('the editor offers every finish by its ES/EN name from video2d_lines', () => {
  const copy = lines.finish as Record<string, { titleEs: string; titleEn: string }>
  assert.deepEqual(Object.keys(en.finishes), Object.keys(FINISH_PRESETS))
  for (const name of Object.keys(FINISH_PRESETS)) {
    assert.equal((en.finishes as Record<string, string>)[name], copy[name].titleEn, name)
    assert.equal((es.finishes as Record<string, string>)[name], copy[name].titleEs, name)
  }
})

test('grain is noise, not a pattern: neighbours and the next frame do not repeat it', () => {
  const width = 320
  const one = grainNoise(30, width * 180), next = grainNoise(31, width * 180)
  const mean = one.reduce((sum, value) => sum + value, 0) / one.length
  assert.ok(Math.abs(mean - 127.5) < 3, `mean ${mean}`)
  const correlation = (shift: number, other = one) => {
    let sum = 0
    for (let index = 0; index + shift < one.length; index += 1) sum += (one[index] - mean) * (other[index + shift] - mean)
    return sum / (one.length - shift) / (255 * 255 / 12)
  }
  for (const shift of [1, 2, 4, width, width + 1]) assert.ok(Math.abs(correlation(shift)) < 0.05, `shift ${shift}: ${correlation(shift)}`)
  assert.ok(Math.abs(correlation(0, next)) < 0.05, 'the next frame is new grain')
  assert.deepEqual(grainNoise(30, 64), one.slice(0, 64))
})
