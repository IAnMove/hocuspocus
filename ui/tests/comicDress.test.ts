import test from 'node:test'
import assert from 'node:assert/strict'
import { buildComicPair } from '../src/features/scene3d/comicPage.ts'
import { imageFadeAt, parseImageFade } from '../src/features/scene3d/imageFade.ts'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { parseMediaScreen } from '../src/features/scene3d/mediaScreen.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

const opacity = (slot: Scene3DSlot, at: number) => slot.imageLook?.fade ? imageFadeAt(slot.imageLook.fade, at) : 1

test('a fade holds its ends and eases between them', () => {
  const fade = parseImageFade({ from: 0, to: 1, start: 0.2, end: 1.2 })!
  assert.equal(imageFadeAt(fade, 0), 0)
  assert.equal(imageFadeAt(fade, 2), 1)
  assert.ok(Math.abs(imageFadeAt(fade, 0.7) - 0.5) < 1e-9)
  assert.equal(parseImageFade({ from: 0, to: 1 }), undefined, 'a fade needs its times')
  assert.deepEqual(parseImageLook({ unlit: true, fade: { from: 2, to: -1, start: 1, end: 0.5 } })?.fade, { from: 1, to: 0, start: 1, end: 1 })
})

test('a screen may ask for more canvas rows, within bounds', () => {
  assert.equal(parseMediaScreen({ sourceUrl: '/a.mp4', media: 'video', lines: 1920 })?.lines, 1920)
  assert.equal(parseMediaScreen({ sourceUrl: '/a.mp4', media: 'video', lines: 9000 })?.lines, 2160)
  assert.equal(parseMediaScreen({ sourceUrl: '/a.mp4', media: 'video' })?.lines, undefined)
})

test('printed twins fade so both cuts stay clean and both halves agree at the wide pose', () => {
  const live = { url: '/api/v1/file/comic-live-2.mp4', lines: 1920, fadeStart: 0.5, fadeEnd: 1.1 }
  const panels = [0, 1, 2, 3].map(index => ({
    url: `/p${index}.png`, print: `/print${index}.png`,
    ...(index === 1 ? { cutout: '/c1.png', printCutout: '/pc1.png', shadow: '/s1.png' } : {}),
    ...(index === 2 ? { live } : {}),
  }))
  const pair = buildComicPair({ format: 'portrait', panels, fromPanel: 1, toPanel: 2, deskUrl: '/desk.png' })
  const exit = pair.exit, enter = pair.enter
  assert.equal(exit.slots[0].id, 'desk')
  assert.equal(exit.environment?.floorStyle, 'none')
  const prints = (slots: Scene3DSlot[]) => slots.filter(slot => /^(print|shadow)/.test(slot.id))
  for (const slot of prints(exit.slots)) assert.equal(opacity(slot, exit.duration), 1, `${slot.id} printed at the end of the exit`)
  for (const slot of prints(enter.slots)) assert.equal(opacity(slot, 0), 1, `${slot.id} printed at the start of the enter`)
  for (const id of ['print-1', 'print-cutout-1', 'shadow-1']) assert.equal(opacity(exit.slots.find(slot => slot.id === id)!, 0), 0, `${id} hidden at the exit cut`)
  assert.equal(opacity(enter.slots.find(slot => slot.id === 'print-2')!, enter.duration), 0, 'the arriving print is gone at the cut')
  const arriving = enter.slots.find(slot => slot.id === 'panel-2')!
  assert.equal(arriving.screen?.sourceUrl, live.url)
  assert.equal(arriving.screen?.lines, 1920)
  assert.equal(exit.slots.find(slot => slot.id === 'panel-2')!.screen, undefined, 'the exit shows the still')
  const clean = exit.slots.find(slot => slot.id === 'cutout-1')!, twin = exit.slots.find(slot => slot.id === 'print-cutout-1')!
  assert.ok(twin.position[2] > clean.position[2] && twin.scale < clean.scale, 'the printed sticker sits just in front, a touch smaller')
  assert.ok(Math.abs((twin.position[1] + twin.scale) - (clean.position[1] + clean.scale)) < 1e-9, 'both on the fill axis')
})

test('without paper the catalogue pages keep their plain slots', () => {
  const pair = buildComicPair({ format: 'landscape' })
  assert.ok(!pair.exit.slots.some(slot => slot.id === 'desk' || slot.id.startsWith('print')))
  assert.equal(pair.exit.environment?.floorStyle, undefined)
})
