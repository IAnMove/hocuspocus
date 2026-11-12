import assert from 'node:assert/strict'
import test from 'node:test'
import { FX_CATALOG, parseSceneFx, type SceneFx } from '../src/features/sceneFx/types.ts'
import { needsFrameSource, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { impactBeat, isFrameFx } from '../src/features/sceneFx/impactPaint.ts'
import { showcaseCollectionFrom, withFxShowcase } from '../src/features/sceneFx/showcase.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { parseScreenBackdrop, SCREEN_BACKDROP_COLOR } from '../src/features/scene3d/screenBackdrop.ts'

type Call = { name: string; args: unknown[]; fillStyle: unknown; alpha: unknown; composite: unknown }

/** A 2D context that records what is drawn and with which style. */
function recorder(width: number, height: number) {
  const calls: Call[] = []
  const state: Record<string, unknown> = { canvas: { width, height }, fillStyle: '#000', strokeStyle: '#000', globalAlpha: 1, globalCompositeOperation: 'source-over', lineWidth: 1, lineCap: 'butt', font: '', textAlign: 'left' }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (typeof prop === 'string' && !(prop in target)) {
        return (...args: unknown[]) => {
          calls.push({ name: prop, args, fillStyle: target.fillStyle, alpha: target.globalAlpha, composite: target.globalCompositeOperation })
          return prop === 'measureText' ? { width: 10 } : undefined
        }
      }
      return Reflect.get(target, prop, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, calls }
}

const cue = (kind: string, patch: Partial<SceneFx> = {}) => parseSceneFx([{ id: kind, kind, start: 1, end: 1 + 3 / 24, x: 12, y: 80, size: 30, ...patch }])[0]

test('the impact frames are anime catalog effects any 2D or 3D scene can use', () => {
  for (const id of ['impact_flash', 'impact_invert']) {
    const preset = FX_CATALOG.find(item => item.id === id)
    assert.equal(preset?.collection, 'anime')
    assert.equal(preset?.sound, 'impact')
    assert.equal(cue(id)?.kind, id)
    assert.equal(isFrameFx(id), true)
  }
  assert.equal(isFrameFx('manga_impact'), false)
  assert.equal(needsFrameSource('impact_invert'), true)
  assert.equal(needsFrameSource('psx'), true)
  assert.equal(needsFrameSource('impact_flash'), false)
  const anime = withFxShowcase(createDefaultScene3DDocument(), 'anime')
  assert.equal(showcaseCollectionFrom(anime), 'anime', 'the anime showcase is still recognised with fourteen cues')
})

test('two, three and four frame cues walk through flash, lines and release', () => {
  const beats = (frames: number) => Array.from({ length: frames }, (_, index) => impactBeat({ start: 0, end: frames / 24 }, index / 24).beat)
  assert.deepEqual(beats(2), [0, 1])
  assert.deepEqual(beats(3), [0, 1, 2])
  assert.deepEqual(beats(4), [0, 1, 1, 2])
  const long = { start: 0, end: 2.8 }
  assert.equal(impactBeat(long, 0.05).beat, 0)
  assert.equal(impactBeat(long, 0.15).beat, 1)
  assert.ok(impactBeat(long, 1).fade > impactBeat(long, 2.5).fade, 'a long cue releases slowly instead of staying white')
})

test('the flash fills the whole frame wherever its focus point is', () => {
  const { context, calls } = recorder(320, 180)
  paintSceneFx(context, 320, 180, 1, [cue('impact_flash', { color: '#ff0000' })])
  const fill = calls.find(call => call.name === 'fillRect')
  assert.deepEqual(fill?.args, [0, 0, 320, 180])
  assert.equal(fill?.fillStyle, '#ff0000')
  assert.equal(calls.some(call => call.name === 'translate'), false)
  const lines = recorder(320, 180)
  paintSceneFx(lines.context, 320, 180, 1 + 1 / 24, [cue('impact_flash')])
  assert.ok(lines.calls.filter(call => call.name === 'fill' && call.fillStyle === '#0b0b14').length >= 20, 'ink focus lines on the second frame')
})

test('the inverted frame works on the picture under it', () => {
  const source = { tagName: 'CANVAS' } as unknown as CanvasImageSource
  const { context, calls } = recorder(320, 180)
  paintSceneFx(context, 320, 180, 1, [cue('impact_invert')], source)
  assert.equal(calls[0].name, 'drawImage', 'an overlay copies the stage first')
  const negative = calls.find(call => call.name === 'fillRect')
  assert.equal(negative?.composite, 'difference')
  assert.equal(negative?.fillStyle, '#ffffff')
  assert.deepEqual(negative?.args, [0, 0, 320, 180])
  const plain = recorder(320, 180)
  paintSceneFx(plain.context, 320, 180, 1, [cue('impact_flash')], source)
  assert.equal(plain.calls.some(call => call.name === 'drawImage'), false, 'other effects never copy the stage')
})

test('speed-line intensity sets how many lines are drawn; 1 keeps the original 65', () => {
  const strokes = (intensity: number) => {
    const { context, calls } = recorder(200, 200)
    paintSceneFx(context, 200, 200, 0.5, parseSceneFx([{ id: 's', kind: 'speedlines', start: 0, end: 2, intensity }]))
    return calls.filter(call => call.name === 'stroke').length
  }
  assert.equal(strokes(1), 65)
  assert.equal(strokes(2), 130)
  assert.ok(strokes(0.5) < 65)
})

test('a screen backdrop keeps its colour and effects through save and reopen', () => {
  assert.equal(parseScreenBackdrop(null), undefined)
  assert.equal(parseScreenBackdrop([]), undefined)
  assert.deepEqual(parseScreenBackdrop({ color: 'red' }), { color: SCREEN_BACKDROP_COLOR, sfx: [] })
  const backdrop = parseScreenBackdrop({ color: '#1c2f86', sfx: [{ id: 'lines', kind: 'speedlines', start: 0, end: 4 }, { kind: 'nope', start: 0, end: 1 }] })!
  assert.equal(backdrop.sfx.length, 1)
  const doc = { ...createDefaultScene3DDocument(), screenBackdrop: backdrop }
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc)))?.screenBackdrop, backdrop)
  assert.equal(parseScene3DDocument(createDefaultScene3DDocument())?.screenBackdrop, undefined)
})
