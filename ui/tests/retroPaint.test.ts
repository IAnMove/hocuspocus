import assert from 'node:assert/strict'
import { test } from 'node:test'
import { applyRetroPixels, isRetroLook, RETRO_LOOK_IDS } from '../src/features/sceneFx/retroPaint'
import { FX_CATALOG, parseSceneFx } from '../src/features/sceneFx/types'
import { withFxShowcase } from '../src/features/sceneFx/showcase'
import { paintSceneFx } from '../src/features/sceneFx/paint'

function gradient(width: number, height: number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      pixels[i] = Math.round(x * 255 / Math.max(1, width - 1))
      pixels[i + 1] = Math.round(y * 255 / Math.max(1, height - 1))
      pixels[i + 2] = 128
      pixels[i + 3] = 255
    }
  }
  return pixels
}

function colors(pixels: Uint8ClampedArray) {
  const seen = new Set<string>()
  for (let i = 0; i < pixels.length; i += 4) seen.add(`${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`)
  return seen
}

test('retro looks are catalogued as screen-only and invertibly named', () => {
  assert.equal(RETRO_LOOK_IDS.length, 10)
  for (const id of RETRO_LOOK_IDS) {
    assert.equal(isRetroLook(id), true)
    assert.ok(FX_CATALOG.some(item => item.id === id && item.collection === 'retro'), id)
  }
  assert.equal(isRetroLook('sparks'), false)
  assert.equal(FX_CATALOG.filter(item => item.collection === 'retro').length, 10)
})

test('each retro look is deterministic and changes a gradient', () => {
  const width = 48, height = 32
  const source = gradient(width, height)
  const baseline = colors(source).size
  for (const kind of RETRO_LOOK_IDS) {
    const a = new Uint8ClampedArray(source)
    const b = new Uint8ClampedArray(source)
    applyRetroPixels(a, width, height, kind, 1, 11, 0.4)
    applyRetroPixels(b, width, height, kind, 1, 11, 0.4)
    assert.deepEqual(a, b, kind)
    assert.notDeepEqual(a, source, kind)
    if (kind === 'gameboy') {
      const allowed = new Set(['15,56,15', '48,98,48', '139,172,15', '155,188,15'])
      for (const color of colors(a)) assert.equal(allowed.has(color), true, color)
    }
    if (kind === 'psx' || kind === 'nes' || kind === 'c64') {
      assert.ok(colors(a).size < baseline, kind)
    }
  }
})

test('retro showcase is 30 seconds and keeps authored slots', () => {
  const source = { version: 1 as const, duration: 4, slots: [{ id: 'subject_1' }] }
  const next = withFxShowcase(source, 'retro')
  assert.equal(next.duration, 30)
  assert.equal(next.sfx.length, 10)
  assert.deepEqual(next.sfx.map(cue => cue.kind), [...RETRO_LOOK_IDS])
  assert.equal(next.slots, source.slots)
  const cue = parseSceneFx([{ kind: 'psx', start: 0, end: 1, sound: true }])[0]
  assert.equal(cue.kind, 'psx')
})

test('paintSceneFx applies a look without the particle path', () => {
  const cue = parseSceneFx([{ id: 'look', kind: 'gameboy', start: 0, end: 2, intensity: 1, seed: 3 }])[0]
  const pixels = gradient(16, 16)
  const image = { data: pixels, width: 16, height: 16 }
  const ops: string[] = []
  const ctx = {
    drawImage() { ops.push('copy') },
    getImageData() { ops.push('read'); return image },
    putImageData() { ops.push('write') },
    save() { ops.push('save') }, restore() { ops.push('restore') },
    translate() {}, scale() {}, rotate() {}, beginPath() {}, fill() {}, stroke() {},
    fillRect() {}, measureText: () => ({ width: 0 }),
    fillStyle: '', strokeStyle: '', globalAlpha: 1,
  } as unknown as CanvasRenderingContext2D
  paintSceneFx(ctx, 16, 16, 0.5, [cue], { tagName: 'CANVAS' } as unknown as CanvasImageSource)
  assert.deepEqual(ops, ['copy', 'read', 'write'])
  assert.ok([...colors(pixels)].every(color => ['15,56,15', '48,98,48', '139,172,15', '155,188,15'].includes(color)))
})
