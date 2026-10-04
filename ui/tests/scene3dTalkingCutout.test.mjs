import test from 'node:test'
import assert from 'node:assert/strict'
import { anchorRect, blinkingAt, parseTalkingCutout, talkStateAt } from '../src/features/scene3d/talkingCutout.ts'
import { mediaScreenMountKey, parseMediaScreen } from '../src/features/scene3d/mediaScreen.ts'

const talk = {
  base: '/api/v1/file/kits/lola/base.png',
  mouths: { rest: '/api/v1/file/kits/lola/m-rest.png', A: '/api/v1/file/kits/lola/m-a.png', O: '/api/v1/file/kits/lola/m-o.png' },
  mouth: { offsetX: 2, offsetY: -18, scale: .08, rotation: 4 },
  rest: 'rest',
  cues: [{ start: 1.2, end: 1.5, state: 'O' }, { start: .5, end: .8, state: 'A' }, { start: 2, end: 2.2, state: 'unknown' }, { start: 3, end: 2, state: 'A' }],
  blink: { source: '/api/v1/file/kits/lola/blink.png', anchor: { offsetX: 0, offsetY: -25, scale: .05, rotation: 0 } },
  blinks: [1, 'x', 4.5],
}

test('a talking cutout keeps known mouths, sorted valid cues and its blink', () => {
  const parsed = parseTalkingCutout(talk)
  assert.deepEqual(parsed.cues, [{ start: .5, end: .8, state: 'A' }, { start: 1.2, end: 1.5, state: 'O' }])
  assert.deepEqual(parsed.blinks, [1, 4.5])
  assert.equal(parsed.blink.source, talk.blink.source)
  assert.equal(parseTalkingCutout({ ...talk, rest: 'Z' }).rest, 'rest', 'an unknown rest falls back to the first mouth')
  assert.equal(parseTalkingCutout({ ...talk, mouths: {} }), undefined)
  assert.equal(parseTalkingCutout({ ...talk, mouth: { offsetX: 0, offsetY: 0, scale: 0 } }), undefined)
  assert.equal(parseTalkingCutout({ ...talk, blink: { source: '/b.png' } }).blink, undefined, 'a blink without anchor is dropped')
  const anchored = parseTalkingCutout({ ...talk, mouthAnchors: { O: { offsetX: 1, offsetY: -17, scale: .1 }, Z: talk.mouth, A: { scale: 0 } } })
  assert.deepEqual(anchored.mouthAnchors, { O: { offsetX: 1, offsetY: -17, scale: .1, rotation: 0 } }, 'only valid anchors of known mouths')
})

test('the mouth follows the cue that holds the time and rests between lines', () => {
  const parsed = parseTalkingCutout(talk)
  assert.deepEqual([0, .5, .79, .8, 1, 1.2, 1.49, 1.5, 9].map(t => talkStateAt(parsed, t)), ['rest', 'A', 'A', 'rest', 'rest', 'O', 'O', 'rest', 'rest'])
  assert.deepEqual([.99, 1, 1.05, 1.2, 4.5].map(t => blinkingAt(parsed.blinks, t)), [false, true, true, false, true])
})

test('anchors use the Character Kit convention: % of the longer edge, height = scale x edge', () => {
  const rect = anchorRect({ offsetX: 10, offsetY: -20, scale: .1, rotation: 0 }, 400, 800, 2)
  assert.deepEqual(rect, { x: 200 + 80 - 80, y: 400 - 160 - 40, width: 160, height: 80 })
})

test('a media screen with a talking cutout is transparent and remounts when its art changes', () => {
  const screen = parseMediaScreen({ media: 'image', sourceUrl: '/ignored.png', talk })
  assert.equal(screen.sourceUrl, talk.base)
  assert.equal(screen.transparent, true)
  assert.equal(screen.talk.cues.length, 2)
  const moved = parseMediaScreen({ media: 'image', talk: { ...talk, cues: [{ start: 0, end: 1, state: 'A' }] } })
  assert.equal(mediaScreenMountKey(screen), mediaScreenMountKey(moved), 'new cues repaint without reloading images')
  const other = parseMediaScreen({ media: 'image', talk: { ...talk, mouths: { ...talk.mouths, A: '/api/v1/file/other.png' } } })
  assert.notEqual(mediaScreenMountKey(screen), mediaScreenMountKey(other))
  assert.equal(parseMediaScreen({ media: 'video', sourceUrl: '/a.mp4', talk }).talk, undefined)
})
