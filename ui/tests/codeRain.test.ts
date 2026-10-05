import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { FX_CATALOG, parseSceneFx, switchFxKind, type SceneFx } from '../src/features/sceneFx/types.ts'
import { paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { CODE_RAIN_GLYPHS, CODE_RAIN_KIND, paintCodeRain } from '../src/features/sceneFx/codeRainPaint.ts'
import { withFxShowcase } from '../src/features/sceneFx/showcase.ts'
import { parseScreenBackdrop } from '../src/features/scene3d/screenBackdrop.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyAnimeTemplate } from '../src/features/scene3d/animeTemplates.ts'
import { hideEmptyCutoutsInExport, type GpuWorld } from '../src/features/scene3d/gpu.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const locale = (code: string) => JSON.parse(readFileSync(join(HERE, `../src/i18n/locales/${code}/sceneFx.json`), 'utf8'))

type Call = { name: string; args: unknown[]; fillStyle: unknown; alpha: unknown; font: unknown; shadowBlur: unknown }

/** A 2D context that records every draw call with the style it used. Same calls, same pixels. */
function recorder(width: number, height: number) {
  const calls: Call[] = []
  const state: Record<string, unknown> = { canvas: { width, height }, fillStyle: '#000', strokeStyle: '#000', shadowColor: '#000', shadowBlur: 0,
    globalAlpha: 1, globalCompositeOperation: 'source-over', lineWidth: 1, lineCap: 'butt', font: '', textAlign: 'left', textBaseline: 'alphabetic' }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (typeof prop === 'string' && !(prop in target)) {
        return (...args: unknown[]) => {
          calls.push({ name: prop, args, fillStyle: target.fillStyle, alpha: target.globalAlpha, font: target.font, shadowBlur: target.shadowBlur })
          return prop === 'measureText' ? { width: 10 } : undefined
        }
      }
      return Reflect.get(target, prop, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, calls }
}

const rain = (patch: Partial<SceneFx> = {}) => parseSceneFx([{ id: 'rain', kind: CODE_RAIN_KIND, start: 0, end: 6, seed: 5, ...patch }])[0]
const draw = (cue: SceneFx, time: number, width = 640, height = 360) => {
  const { context, calls } = recorder(width, height)
  paintCodeRain(context, cue, time, width, height)
  return calls
}
const texts = (calls: Call[]) => calls.filter(call => call.name === 'fillText')
/** Head glyphs are drawn last, with the glow on. */
const heads = (calls: Call[]) => texts(calls).filter(call => Number(call.shadowBlur) > 0)

test('code rain is a classic catalog effect with its own glyph size, colour and names', () => {
  const preset = FX_CATALOG.find(item => item.id === CODE_RAIN_KIND)
  assert.deepEqual(preset, { id: 'code_rain', color: '#39ff6a', sound: 'scan', collection: 'classic', size: 3 })
  const cue = parseSceneFx([{ id: 'r', kind: 'code_rain', start: 1, end: 7 }])[0]
  assert.equal(cue.kind, 'code_rain')
  assert.equal(cue.size, 3, 'size is the glyph height in % of the frame, not a burst size')
  assert.equal(cue.color, '#39ff6a')
  assert.equal(rain({ size: 5, intensity: 1.5, color: '#ffb000' }).size, 5)
  assert.equal(parseSceneFx([{ id: 's', kind: 'sparks', start: 0, end: 1 }])[0].size, 65, 'other effects keep the shared default')
  assert.equal(locale('en').presets.code_rain, 'Code rain')
  assert.equal(locale('es').presets.code_rain, 'Lluvia de código')
  const showcase = withFxShowcase({ version: 1 as const, name: 'FX', layers: [], width: 640, height: 360, duration: 3 })
  assert.equal(showcase.sfx.find(item => item.kind === 'code_rain')?.size, 3)
})

test('switching a cue to or from code rain resets the size scale', () => {
  assert.deepEqual(switchFxKind({ kind: 'sparks' }, 'code_rain'), { kind: 'code_rain', color: '#39ff6a', size: 3 })
  assert.deepEqual(switchFxKind({ kind: 'code_rain' }, 'sparks'), { kind: 'sparks', color: '#ffbb55', size: 65 })
  assert.deepEqual(switchFxKind({ kind: 'sparks' }, 'rain'), { kind: 'rain', color: '#88bbff' }, 'other switches keep the size')
  assert.deepEqual(switchFxKind({ kind: 'sparks' }, 'nope'), {})
})

test('the same seed and time draw the same frame; another seed draws another', () => {
  const cue = rain()
  assert.deepEqual(draw(cue, 2.25), draw(cue, 2.25))
  assert.notDeepEqual(texts(draw(cue, 2.25)), texts(draw(rain({ seed: 6 }), 2.25)))
  assert.ok(texts(draw(cue, 2.25)).length > 100, 'a frame full of glyphs')
  for (const call of texts(draw(cue, 2.25))) assert.ok(CODE_RAIN_GLYPHS.includes(String(call.args[0])), String(call.args[0]))
})

test('the frame at the end of the cue is the frame at its start, whatever its length', () => {
  for (const [start, end] of [[0, 6], [1.3, 5.67], [0, 2], [12.5, 32.5]]) {
    const cue = rain({ start, end, seed: 11 })
    assert.deepEqual(draw(cue, end - start), draw(cue, 0), `${start}-${end}`)
    assert.notDeepEqual(draw(cue, (end - start) / 2), draw(cue, 0), `${start}-${end}: it moves in between`)
  }
  // Through the shared painter too: a cue that starts later repeats over its own span.
  const late = rain({ start: 2, end: 8 })
  const at = (seconds: number) => { const { context, calls } = recorder(320, 180); paintSceneFx(context, 320, 180, seconds, [late]); return calls }
  assert.deepEqual(at(2), at(2))
  assert.equal(at(8).length, 0, 'the cue is over at its end')
})

test('glyphs fall: between two frames the heads move down, and the glyphs change', () => {
  const cue = rain()
  const before = heads(draw(cue, 2)), after = heads(draw(cue, 2 + 1 / 24))
  assert.ok(before.length > 20)
  const byColumn = (calls: Call[]) => new Map(calls.map(call => [Number(call.args[1]), Number(call.args[2])]))
  const first = byColumn(before), next = byColumn(after)
  let down = 0, up = 0
  for (const [x, y] of first) {
    const later = next.get(x)
    if (later === undefined) continue
    if (later > y) down++
    if (later < y) up++
  }
  assert.ok(down > up * 4, `heads moving down ${down}, up (a new drop at the top) ${up}`)
  const glyphsAt = (time: number) => texts(draw(cue, time)).map(call => `${call.args[1]},${call.args[2]}:${call.args[0]}`)
  const still = new Set(glyphsAt(3))
  assert.ok(glyphsAt(3.5).some(cell => !still.has(cell)))
})

test('the rain fills the whole frame: size is the glyph height and x/y/rotation do not move it', () => {
  const calls = draw(rain(), 1, 1000, 500)
  assert.match(String(texts(calls)[0].font), /^15px /, '3% of 500 px')
  assert.match(String(texts(draw(rain({ size: 6 }), 1, 1000, 500))[0].font), /^30px /)
  const xs = texts(calls).map(call => -Number(call.args[1]))
  assert.ok(Math.min(...xs) < 100 && Math.max(...xs) > 900, 'columns across the frame')
  const placed = (patch: Partial<SceneFx>) => { const { context, calls: list } = recorder(320, 180); paintSceneFx(context, 320, 180, 1, [rain(patch)]); return list }
  assert.deepEqual(placed({ x: 10, y: 90, rotation: 45 }), placed({ x: 50, y: 50, rotation: 0 }))
  assert.equal(placed({}).some(call => call.name === 'translate' || call.name === 'rotate'), false)
})

test('intensity sets how dense and how bright the rain is; the head is near-white', () => {
  const dense = texts(draw(rain({ intensity: 2 }), 1)).length, sparse = texts(draw(rain({ intensity: 0.4 }), 1)).length
  assert.ok(dense > sparse * 3, `${dense} vs ${sparse}`)
  const dim = Math.max(...texts(draw(rain({ intensity: 0.2 }), 1)).map(call => Number(call.alpha)))
  assert.ok(dim < Math.max(...texts(draw(rain(), 1)).map(call => Number(call.alpha))))
  const head = heads(draw(rain(), 1))[0]
  assert.match(String(head.fillStyle), /^#[0-9a-f]{6}$/)
  assert.ok(texts(draw(rain(), 1)).some(call => call.fillStyle === '#39ff6a'), 'the trail reaches the cue colour')
  const channel = (color: unknown, index: number) => parseInt(String(color).slice(1 + index * 2, 3 + index * 2), 16)
  assert.ok(channel(head.fillStyle, 0) > 200 && channel(head.fillStyle, 2) > 200, `head ${head.fillStyle}`)
})

test('code rain works as a Video 3D screen effect and as a screen backdrop', () => {
  const cue = { id: 'rain', kind: 'code_rain', start: 0, end: 6 }
  const backdrop = parseScreenBackdrop({ color: '#000000', sfx: [cue] })!
  assert.equal(backdrop.sfx[0].size, 3)
  const doc = { ...createDefaultScene3DDocument(), duration: 6, sfx: parseSceneFx([cue]), screenBackdrop: backdrop }
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(reopened?.sfx, doc.sfx)
  assert.deepEqual(reopened?.screenBackdrop, backdrop)
})

test('the code-rain shot rains over its whole length behind an optional tinted cutout', () => {
  const doc = applyAnimeTemplate('anime-code-rain')!
  assert.equal(doc.duration, 6)
  assert.equal(doc.screenBackdrop?.color, '#000000')
  const rains = doc.screenBackdrop?.sfx ?? []
  assert.ok(rains.length >= 1 && rains.every(item => item.kind === 'code_rain' && item.start === 0 && item.end === doc.duration), 'each cue spans the shot, so a plate loops')
  assert.equal(doc.sfx?.length ?? 0, 0, 'nothing over the face')
  assert.equal(doc.worldSfx, undefined)
  const subject = doc.slots.find(slot => slot.id === 'subject')!
  assert.equal(subject.surface, 'cutout')
  assert.equal(subject.sourceUrl, '')
  assert.ok(subject.imageLook?.unlit && subject.imageLook.tint, 'the green spill of the code')
  assert.equal(doc.camera.framing?.targetSlot, 'subject')
  assert.ok((doc.camera.framing?.to[2] ?? 0) < (doc.camera.framing?.from[2] ?? 0), 'a push-in')
  const bound = applyAnimeTemplate('anime-code-rain', { roles: { subject: '/api/v1/file/kit.png?workspace=w' } })!
  assert.equal(bound.slots.find(slot => slot.id === 'subject')?.sourceUrl, '/api/v1/file/kit.png?workspace=w')
})

test('an export hides a cutout with no picture and keeps every other object', () => {
  const slot = (id: string, patch: Partial<Scene3DSlot>) => ({ id, slot: 'subject_1', media: 'image', surface: 'cutout', sourceUrl: '', clip: null, position: [0, 0, 0], rotationY: 0, scale: 1, ...patch }) as Scene3DSlot
  const slots = [slot('empty', {}), slot('bound', { sourceUrl: '/a.png' }), slot('model', { media: 'model3d', surface: undefined }), slot('wall', { surface: 'wall' })]
  const world = (exporting: boolean) => ({ exporting, slots: new Map(slots.map(item => [item.id, { root: { visible: true } }])) }) as unknown as GpuWorld
  const visible = (target: GpuWorld) => slots.map(item => target.slots.get(item.id)!.root.visible)
  const exported = world(true), editing = world(false)
  hideEmptyCutoutsInExport(exported, slots)
  hideEmptyCutoutsInExport(editing, slots)
  assert.deepEqual(visible(exported), [false, true, true, true])
  assert.deepEqual(visible(editing), [true, true, true, true], 'the editor keeps the placeholder')
})
