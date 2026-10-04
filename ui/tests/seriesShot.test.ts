import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { blinkTimes, compileSeriesShot, PERCH, perchTransforms, personTransform, runSeriesShot, type ShotSpec } from '../scripts/seriesShot.ts'

const STATES = ['closed', 'small', 'wide', 'round', 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
const asset = (id: string, kind: 'image' | 'overlay' = 'overlay', size?: { width: number; height: number }): CharacterKitAsset => ({
  id, name: id, source: `/api/v1/file/${id}.png?workspace=cast`, kind, alphaStatus: 'transparent', reviewState: 'approved', ...size })

function kit(id: string): CharacterKit {
  const value = createCharacterKit(id)
  value.id = id
  value.base = asset(`${id}-base`, 'image', { width: 500, height: 1000 })
  value.poses = { panic: asset(`${id}-panic`, 'image', { width: 600, height: 1000 }) }
  value.mouth = Object.fromEntries(STATES.map(state => [state, asset(`${id}-mouth-${state}`)]))
  value.mouthMapping = { rest: 'closed', M: 'pressed', A: 'wide', E: 'medium', I: 'small', O: 'round', U: 'pucker', F: 'bite', L: 'tongue' }
  value.eyes = { blink: asset(`${id}-blink`) }
  const anchors = { mouth: { offsetX: 0, offsetY: -8, scale: 0.1, rotation: 0 }, eyes: { offsetX: 0, offsetY: -22, scale: 0.18, rotation: 0 } }
  value.anchors = { base: anchors, panic: anchors }
  return value
}

const kits = { kevin: kit('kevin'), gary: kit('gary') }
const cues = { mouthCues: [{ start: 0, end: 0.3, value: 'B' }, { start: 0.3, end: 0.8, value: 'D' }, { start: 0.8, end: 1.2, value: 'X' }] }

function shot(overrides: Partial<ShotSpec> = {}): ShotSpec {
  return {
    name: 'Pilot · s01', workspace: 'cast', width: 1920, height: 1080, fps: 24, duration: 4, framing: 'two',
    background: { source: '/api/v1/file/garage.png?workspace=cast', kind: 'image', focusX: 40 },
    cast: [{ kitId: 'kevin', x: 34 }, { kitId: 'gary', x: 66 }],
    lines: [{ id: 's01-l1', kitId: 'kevin', text: 'Hello Gary.', start: 0.35, end: 1.55, filename: 'ln-s01-l1.wav', cues },
      { id: 's01-l2', kitId: 'gary', text: 'Hi.', start: 1.8, end: 2.4, filename: 'ln-s01-l2.wav' }],
    camera: 'push', ...overrides,
  }
}

test('framing puts eyes on one line and feet on the floor in wide shots', () => {
  const two = personTransform(kits.kevin, 'base', 'two', 34, 16 / 9)
  const close = personTransform(kits.kevin, 'base', 'close', 50, 16 / 9)
  assert.ok(close.scale > two.scale)
  // Eye line: 0.5 + (-22% of the 1000 px edge) / 1000 px height = 0.28 of the pose height, at 33 % of the frame.
  assert.equal(two.y, Math.round((33 + (0.5 - 0.28) * 80) * 1000) / 1000)
  const wide = personTransform(kits.kevin, 'base', 'wide', 34, 16 / 9)
  assert.equal(Math.round((wide.y + 25 - 0.75) * 1000) / 1000, 94, 'half of a 50 % tall pose above the feet line')
})

test('a vertical frame draws people smaller against its height so two fit side by side', () => {
  const landscape = personTransform(kits.kevin, 'base', 'two', 27, 16 / 9)
  const portrait = personTransform(kits.kevin, 'base', 'two', 27, 9 / 16)
  assert.equal(portrait.scale, 0.55)
  assert.ok(portrait.scale < landscape.scale)
  const close = personTransform(kits.kevin, 'base', 'close', 50, 9 / 16)
  assert.equal(close.scale, 1.1)
})

test('a planned shot compiles to an editable scene with mounted kits, phonetic mouths, motion and camera', () => {
  const scene = compileSeriesShot(kits, shot())
  const background = scene.layers.find(layer => layer.id === 'background')!
  assert.equal(background.transform.scale, 1.12)
  const kevinPose = scene.layers.find(layer => layer.id.includes('kevin') && layer.type === 'image')!
  assert.equal(kevinPose.characterKitRef?.workspace, 'cast')
  const keyframes = kevinPose.animation.keyframes!
  const talking = keyframes.filter(frame => frame.time >= 0.5 && frame.time <= 1.5)
  assert.ok(talking.some(frame => frame.y < kevinPose.transform.y - 0.05), 'bobs while talking')
  assert.equal(scene.dialogueBeats!.length, 2)
  assert.equal(scene.dialogueBeats![0].confidence, 'aligned-audio')
  assert.equal(scene.dialogueBeats![0].lipSync!.cues.length, 3)
  assert.equal(scene.dialogueBeats![1].confidence, 'known-text')
  const wide = scene.layers.find(layer => layer.faceBinding?.role === 'mouth' && layer.faceBinding.state === 'wide' && layer.id.includes('kevin'))!
  assert.ok(wide.animation.keyframes!.some(frame => frame.opacity === 1), 'the open mouth shows during the line')
  assert.ok(scene.layers.some(layer => layer.faceBinding?.role === 'blink' && layer.animation.keyframes?.length))
  assert.ok(scene.layers.some(layer => layer.type === 'camera'))
  assert.deepEqual(scene.audioTracks!.map(track => [track.id, track.kind, track.startTime]), [['s01-l1', 'speech', 0.35], ['s01-l2', 'speech', 1.8]])
})

test('entering characters hop in; panic shakes; off-screen lines do not move mouths', () => {
  const scene = compileSeriesShot(kits, shot({ cast: [{ kitId: 'kevin', x: 40, poseId: 'panic', motion: 'shake', enter: { fromX: -15, start: 0.2, end: 1.0 } }],
    lines: [{ id: 'vo', kitId: 'gary', text: 'Off screen.', start: 0.5, end: 1.4, filename: 'vo.wav', visible: false }] }))
  const pose = scene.layers.find(layer => layer.id.includes('kevin') && layer.type === 'image')!
  const frames = pose.animation.keyframes!
  assert.equal(frames[0].x, -15)
  assert.ok(frames.some(frame => frame.time > 0.2 && frame.time < 1 && frame.rotation !== 0), 'hops on the way in')
  assert.deepEqual(scene.dialogueBeats![0].mouthLayerIds, [])
})

test('a perched character sits on its prop, just in front of it, in every framing', () => {
  const desk = { source: '/api/v1/file/desk.png?workspace=cast', width: 808, height: 246 }
  for (const framing of ['wide', 'two', 'medium', 'close'] as const) {
    const { character, prop } = perchTransforms({ width: 500, height: 1000 }, framing, 66, 16 / 9, desk)
    const propHeight = character.scale * 100 * 0.5 / (16 / 9) * 1.45 * (16 / 9) / (808 / 246)
    assert.equal(Math.round((character.y + character.scale * 50) * 10) / 10, PERCH[framing].bottom, 'feet on the line')
    assert.equal(Math.round((prop.y - 0.46 * propHeight) * 10) / 10, PERCH[framing].bottom, 'the desk top is that line')
  }
  const scene = compileSeriesShot(kits, shot({ cast: [{ kitId: 'kevin', x: 34 }, { kitId: 'gary', x: 66, perch: desk }] }))
  const seat = scene.layers.find(layer => layer.id === 'perch-gary')!
  const gary = scene.layers.find(layer => layer.characterKitRef?.id === 'gary' && !layer.faceBinding)!
  assert.equal(seat.source, desk.source)
  assert.equal(seat.z, gary.z - 1)
  assert.equal(gary.transform.scale, PERCH.two.height / 100)
})

test('a shot with lines asks the export to dip music and effects under them', () => {
  assert.deepEqual(compileSeriesShot(kits, shot()).audioMix, { duckDb: 10 })
  assert.equal(compileSeriesShot(kits, shot({ lines: [] })).audioMix, undefined)
})

test('blinks are repeatable for a seed and stay inside the shot', () => {
  assert.deepEqual(blinkTimes('a', 12), blinkTimes('a', 12))
  assert.ok(blinkTimes('a', 12).every(time => time > 0.5 && time < 11.7))
})

test('scene operations mount a character, add a line and animate the talk', () => {
  const empty = runSeriesShot({ mode: 'shot', kits, shot: shot({ cast: [], lines: [], camera: 'static' }) })
  assert.ok(empty.ok)
  const mounted = runSeriesShot({ mode: 'mount_character', document: empty.document, kit: kits.kevin,
    request: { x: 50, framing: 'medium', workspace: 'cast' } })
  assert.ok(mounted.ok)
  const again = runSeriesShot({ mode: 'mount_character', document: mounted.document, kit: kits.kevin, request: { x: 30, framing: 'medium', workspace: 'cast' } })
  assert.equal(again.ok, false)
  const spoken = runSeriesShot({ mode: 'add_line', document: mounted.document,
    line: { id: 'l1', kitId: 'kevin', text: 'Hello.', start: 0.4, end: 4.6, filename: 'l1.wav', cues } })
  assert.ok(spoken.ok)
  assert.equal(spoken.document.duration, 5.05, 'the shot grows to fit the line')
  assert.equal(spoken.document.dialogueBeats![0].mouthLayerIds.length, STATES.length)
  assert.equal(spoken.document.audioTracks!.at(-1)!.id, 'l1')
  const missing = runSeriesShot({ mode: 'add_line', document: empty.document, line: { id: 'x', kitId: 'gary', text: 'x', start: 0, end: 1, filename: 'x.wav' } })
  assert.deepEqual(missing.ok ? null : missing.code, 'series_shot_failed')
  const calm = runSeriesShot({ mode: 'animate_talk', document: spoken.document, motion: 'still' })
  assert.ok(calm.ok)
  const pose = calm.document.layers.find(layer => layer.characterKitRef && !layer.faceBinding)!
  assert.ok(pose.animation.keyframes!.every(frame => frame.y === pose.transform.y))
})
