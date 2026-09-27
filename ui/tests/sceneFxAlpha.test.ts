import assert from 'node:assert/strict'
import test from 'node:test'
import { withAlpha } from '../src/features/sceneFx/color.ts'
import { paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { FX_CATALOG, parseSceneFx } from '../src/features/sceneFx/types.ts'

function isPaintableCssColor(value: string) {
  const color = value.trim()
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color)) return true
  if (/^(?:rgb|rgba|hsl|hsla)\([^)]+\)$/i.test(color)) return true
  return /^(?:white|black|transparent)$/i.test(color)
}

test('withAlpha keeps six-digit hex stops and accepts the other CSS forms', () => {
  assert.equal(withAlpha('#ff88dd', '00'), '#ff88dd00')
  assert.equal(withAlpha('#DBEAFE', '88'), '#DBEAFE88')
  assert.equal(withAlpha('#abc', '00'), '#aabbcc00')
  assert.equal(withAlpha('#abcd', '10'), '#aabbcc10')
  assert.equal(withAlpha('#aabbccdd', '00'), '#aabbcc00')
  assert.equal(withAlpha('  #ff00aa  ', 'aa'), '#ff00aaaa')
  assert.equal(withAlpha('rgb(10, 20, 30)', '00'), 'rgba(10, 20, 30, 0)')
  assert.equal(withAlpha('rgba(10, 20, 30, 0.4)', '70'), 'rgba(10, 20, 30, 0.4392)')
  assert.equal(withAlpha('rgb(10 20 30 / 40%)', '00'), 'rgba(10, 20, 30, 0)')
  assert.equal(withAlpha('hsl(120, 100%, 75%)', '00'), 'hsla(120, 100%, 75%, 0)')
  assert.equal(withAlpha('hsl(120 100% 75%)', 'aa'), 'hsla(120, 100%, 75%, 0.6667)')
  assert.equal(withAlpha('hsla(120, 100%, 75%, 0.2)', '00'), 'hsla(120, 100%, 75%, 0)')
  assert.equal(withAlpha('hsl(120deg 100% 75% / 0.5)', 'ff'), 'hsla(120deg, 100%, 75%, 1)')
  assert.equal(isPaintableCssColor(withAlpha('hsl(237.6 100% 75%)', '00')), true)
  assert.equal(isPaintableCssColor('hsl(237.6 100% 75%)00'), false)
  assert.equal(withAlpha('not-a-color', '00'), 'not-a-color')
})

function spyContext(width: number, height: number) {
  const seen: string[] = []
  const state: Record<string, unknown> = {
    canvas: { width, height },
    fillStyle: '#000000', strokeStyle: '#000000', shadowColor: '#000000',
    globalAlpha: 1, globalCompositeOperation: 'source-over', lineWidth: 1, lineCap: 'butt',
    font: '16px sans-serif', textAlign: 'left', textBaseline: 'alphabetic', filter: 'none',
    shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
  }
  const keep = (value: unknown) => {
    if (typeof value !== 'string') return
    assert.equal(isPaintableCssColor(value), true, value)
    seen.push(value)
  }
  const gradient = { addColorStop(offset: number, color: string) { assert.ok(offset >= 0 && offset <= 1); keep(color) } }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return () => gradient
      if (prop === 'measureText') return () => ({ width: 12 })
      if (prop === 'getTransform') return () => ({ a: 1, b: 0, c: 0, d: 1, e: width / 2, f: height / 2 })
      if (prop === 'getImageData') return (_x: number, _y: number, w: number, h: number) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)), width: w, height: h })
      if (typeof prop === 'string' && !(prop in target)) return () => {}
      return Reflect.get(target, prop, receiver)
    },
    set(target, prop, value, receiver) {
      if (prop === 'fillStyle' || prop === 'strokeStyle' || prop === 'shadowColor') keep(value)
      return Reflect.set(target, prop, value, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, seen }
}

test('every screen effect, including the fireworks flash, paints only real CSS colors', () => {
  const times = [0.12, 0.5, 1.05]
  for (const preset of FX_CATALOG) {
    const cue = parseSceneFx([{ id: preset.id, kind: preset.id, start: 0, end: 2, x: 50, y: 50, size: 80, intensity: 1, seed: 4, sound: false }])[0]
    for (const time of times) {
      const { context } = spyContext(32, 32)
      assert.doesNotThrow(() => paintSceneFx(context, 32, 32, time, [cue], { tagName: 'CANVAS' } as unknown as CanvasImageSource), `${preset.id} @ ${time}`)
    }
  }
  const fireworks = parseSceneFx([{ id: 'show', kind: 'fireworks', start: 0, end: 3.2, x: 50, y: 42, size: 80, intensity: 1, seed: 7, sound: false }])[0]
  const flash = spyContext(96, 96)
  paintSceneFx(flash.context, 96, 96, 0.5, [fireworks])
  assert.ok(flash.seen.some(color => color.startsWith('hsla(')))
  const again = spyContext(96, 96)
  paintSceneFx(again.context, 96, 96, 0.5, [fireworks])
  assert.deepEqual(again.seen, flash.seen)
})
