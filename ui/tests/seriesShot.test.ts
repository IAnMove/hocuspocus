import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, parseCharacterKitPoseLayerId, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { blinkTimes, bodyKeyframes, CAMERA_MOVES, castTransform, compileSeriesShot, PERCH, perchTransforms, personTransform, runSeriesShot, WALK_BOB, type CameraMove, type ShotFxSpec, type ShotSpec } from '../scripts/seriesShot.ts'
import { sequenceFrame } from '../src/lib/scene2d/motion.ts'
import { heldFrameTime } from '../src/features/stopMotion.ts'
import { ANIMATION_SHEET, type KitAnimation } from '../src/lib/characterAnimations.ts'

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

test('medium shots and close-ups never show the feet: a wide pose in a vertical frame is enlarged, eyes on the line', () => {
  const wide = kit('wolf')
  wide.poses.arms = asset('wolf-arms', 'image', { width: 900, height: 1000 })
  for (const framing of ['medium', 'close'] as const) {
    const pose = personTransform(wide, 'arms', framing, 50, 9 / 16)
    // The arms pose is width-limited in a 9:16 frame; its bottom must still end below the frame.
    const height = pose.scale * 100 * (9 / 16) / 0.9
    assert.ok(pose.y + height / 2 >= 111.9, `${framing}: bottom ${pose.y + height / 2}`)
  }
  // A narrow pose in a wide frame already crops its feet, so nothing changes.
  assert.equal(personTransform(kits.kevin, 'base', 'medium', 50, 16 / 9).scale, 1.22)
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
  assert.equal(scene.layers.find(layer => layer.type === 'image' && layer.id.includes('kevin'))!.id, 'kit-kevin-pose-base')
  assert.ok(scene.layers.some(layer => layer.id === 'kit-gary-pose-base'))
  assert.ok(scene.layers.some(layer => layer.id === 'kit-kevin-mouth-wide'))
})

test('the same kit twice gets its own ids and the line moves the copy castIndex names', () => {
  const scene = compileSeriesShot(kits, shot({
    cast: [{ kitId: 'kevin', x: 30 }, { kitId: 'kevin', x: 70 }],
    lines: [
      { id: 'a', kitId: 'kevin', text: 'Left.', start: 0.2, end: 1.0, filename: 'a.wav' },
      { id: 'b', kitId: 'kevin', text: 'Right.', start: 1.2, end: 2.0, filename: 'b.wav', castIndex: 1 },
    ],
  }))
  const poses = scene.layers.filter(layer => layer.type === 'image' && layer.id.includes('pose'))
  assert.deepEqual(poses.map(layer => layer.id), ['kit-kevin-0-pose-base', 'kit-kevin-1-pose-base'])
  assert.ok(scene.dialogueBeats![0].mouthLayerIds.every(id => id.includes('kevin-0-')))
  assert.ok(scene.dialogueBeats![1].mouthLayerIds.every(id => id.includes('kevin-1-')))
  assert.deepEqual(parseCharacterKitPoseLayerId('kit-kevin-0-pose-base', ['kevin']), { kitId: 'kevin', poseId: 'base', instanceKey: 0 })
  assert.deepEqual(parseCharacterKitPoseLayerId('kit-kevin-pose-base', ['kevin']), { kitId: 'kevin', poseId: 'base' })
  assert.deepEqual(parseCharacterKitPoseLayerId('kit-wolf-12-pose-base', ['wolf-12']), { kitId: 'wolf-12', poseId: 'base' })
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

test('a walking entrance lands on every step, rises mid-step and sways to alternate sides', () => {
  const rest = { x: 60, y: 70, scale: 0.5 }
  const enter = { fromX: -15, start: 0.5, end: 3.5, gait: 'walk' as const, step: 0.6, sway: 1.5 }
  const frames = bodyKeyframes('monk', rest, 6, [], 'still', enter)
  const at = (time: number) => frames.find(frame => Math.abs(frame.time - time) < 1e-6)!
  assert.deepEqual([frames[0].time, frames[0].x, frames[0].curve], [0, -15, 'hold'], 'off screen until the walk starts')
  for (let step = 0; step <= 5; step++) {
    const footfall = at(0.5 + 0.6 * step)
    assert.equal(footfall.y, 70, `down on footfall ${step}`)
    assert.equal(footfall.rotation, 0)
    assert.equal(footfall.x, Math.round((-15 + 75 * step / 5) * 1000) / 1000, 'at an even pace')
  }
  const peaks = [0, 1, 2, 3, 4].map(step => at(0.8 + 0.6 * step))
  assert.ok(peaks.every(peak => peak.y === Math.round((70 - WALK_BOB * 0.5) * 1000) / 1000), 'up mid-step')
  assert.deepEqual(peaks.map(peak => peak.rotation), [1.5, -1.5, 1.5, -1.5, 1.5], 'leaning to alternate sides')
  const walking = frames.filter(frame => frame.time >= 0.5 && frame.time <= 3.5)
  assert.ok(walking.every((frame, index) => index === 0 || frame.x > walking[index - 1].x), 'never stops on the way in')
  assert.equal(at(3.5).x, 60, 'arrives on its mark')
  const still = bodyKeyframes('monk', rest, 6, [], 'still', { ...enter, sway: 0 })
  assert.ok(still.every(frame => frame.rotation === 0), 'sway 0 walks upright')
})

test('a compiled walk bobs between the frames too', () => {
  const scene = compileSeriesShot(kits, shot({ duration: 4, cast: [{ kitId: 'kevin', x: 50, motion: 'still',
    enter: { fromX: -15, start: 0, end: 2, gait: 'walk', step: 0.5, sway: 1.5 } }], lines: [] }))
  const pose = scene.layers.find(layer => layer.id.includes('kevin') && layer.type === 'image' && !layer.faceBinding)!
  const sample = (time: number) => evaluateSceneLayer(pose, time)
  const rest = sample(2).y
  assert.ok(Math.abs(sample(0.5).y - rest) < 1e-6 && Math.abs(sample(1).y - rest) < 1e-6, 'feet down on 0.5 s and 1 s')
  assert.ok(sample(0.25).y < rest - 0.5 && sample(0.75).y < rest - 0.5, 'up between them')
  assert.ok(sample(0.125).y < rest && sample(0.125).y > sample(0.25).y, 'rising, not jumping')
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

test('a shot that shows the previous picture goes on from its camera, pushing on or holding', () => {
  const camera = (spec: ShotSpec) => compileSeriesShot(kits, spec).layers.find(layer => layer.type === 'camera')
  const rest = camera(shot())!
  assert.deepEqual([rest.animation.start.scale, rest.animation.end.scale, rest.animation.end.y], [1, 1.07, 48.5])
  const onward = camera(shot({ cameraStart: { scale: 1.07, y: 48.5 } }))!
  assert.deepEqual([onward.transform.scale, onward.animation.start.scale, onward.animation.end.scale, onward.animation.end.y], [1.07, 1.07, 1.14, 47])
  const held = camera(shot({ camera: 'static', cameraStart: { scale: 1.07, y: 48.5 } }))!
  assert.deepEqual([held.animation.start.scale, held.animation.end.scale, held.animation.end.y], [1.07, 1.07, 48.5])
  assert.equal(camera(shot({ camera: 'static' })), undefined, 'a static shot at rest has no camera, as before')
  const panEnd = CAMERA_MOVES['pan-left'][1]
  const fromPan = camera(shot({ cameraStart: panEnd }))!
  assert.deepEqual([fromPan.animation.start.x, fromPan.animation.end.x, fromPan.animation.end.scale], [46.5, 46.5, 1.15], 'x stays, the push grows')
  const pan = camera(shot({ camera: 'pan-left', cameraStart: panEnd }))!
  assert.deepEqual([pan.animation.start, pan.animation.end].map(pose => pose.x), [53.5, 46.5], 'a pan plays its own move')
})

test('a detail frames a point of the same plate closer, as far as its edges allow', () => {
  const background = (spec: ShotSpec) => compileSeriesShot(kits, spec).layers.find(layer => layer.id === 'background')!
  const framed = background(shot({ framing: 'insert', cast: [], lines: [], background: { source: '/api/v1/file/street.png?workspace=cast', kind: 'image', focusX: 50, detail: { x: 56, y: 18, zoom: 1.8 } } }))
  assert.deepEqual([framed.transform.x, framed.transform.y, framed.transform.scale], [39.2, 90, 1.8])
  const plain = background(shot({ framing: 'insert', cast: [], lines: [] }))
  assert.deepEqual([plain.transform.y, plain.transform.scale], [50, 1], 'without a detail the plate stays as it was')
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

test('a beam from a cast member starts on that cutout\'s pose layer; one from the frame keeps its point', () => {
  const laser = (from: ShotFxSpec['from'], id = 'fx-0') => ({ id, kind: 'laser', start: 0.6, end: 0.9, x: 90, y: 20, color: '#ffd56a', ...(from ? { from } : {}) }) as ShotFxSpec
  const scene = compileSeriesShot(kits, shot({
    cast: [{ kitId: 'kevin', characterId: 'kev', x: 34 }, { kitId: 'gary', x: 66 }],
    sfx: [laser({ cast: 1, point: [95, 46] }), laser({ cast: 'kev', point: [10, 50] }, 'fx-1'), laser({ point: [70, 40] }, 'fx-2'), laser(undefined, 'fx-3')],
  }))
  const poses = scene.layers.filter(layer => layer.characterKitRef && layer.type === 'image' && !layer.faceBinding).map(layer => layer.id)
  assert.deepEqual(scene.sfx!.map(cue => cue.from), [{ layerId: poses[1], x: 95, y: 46 }, { layerId: poses[0], x: 10, y: 50 }, { x: 70, y: 40 }, undefined])
  assert.ok(poses[1].includes('gary'))
  const missing = runSeriesShot({ mode: 'shot', kits, shot: shot({ sfx: [laser({ cast: 4, point: [95, 46] })] }) })
  assert.equal(missing.ok, false)
  assert.match(missing.ok ? '' : missing.message, /fx-0 starts on cast 4, who is not in this shot/)
})

test('stop-motion is copied onto the scene only when the shot sets it', () => {
  const held = compileSeriesShot(kits, shot({ motionStep: 2, stopMotionJitter: 1 }))
  assert.equal(held.motionStep, 2)
  assert.equal(held.stopMotionJitter, 1)
  const plain = compileSeriesShot(kits, shot())
  assert.equal('motionStep' in plain, false)
  assert.equal('stopMotionJitter' in plain, false)
})

test('a push compiles to the camera layer it always did, and a static or unknown camera to none', () => {
  const still = { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }, pushed = { x: 50, y: 48.5, scale: 1.07, opacity: 1, rotation: 0 }
  assert.deepEqual(compileSeriesShot(kits, shot()).layers.find(layer => layer.type === 'camera'), {
    id: 'camera', name: 'Camera', type: 'camera', source: '', visible: true, locked: false, z: 1000, transform: still,
    animation: { start: still, end: pushed, duration: 4, curve: 'ease', keyframes: [
      { id: 'camera-0', time: 0, ...still, curve: 'ease' }, { id: 'camera-4000', time: 4, ...pushed, curve: 'ease' }] },
  })
  for (const camera of ['static', 'zoom', 'toString'] as CameraMove[]) {
    assert.equal(compileSeriesShot(kits, shot({ camera })).layers.some(layer => layer.type === 'camera'), false, camera)
  }
})

test('every camera move keeps the plate over the whole frame, in a flat or a layered set, at any framing', () => {
  const layers: ShotSpec['layers'] = [{ id: 'layer-1', name: 'Front', source: '/api/v1/file/fg.png?workspace=cast', kind: 'image', x: 8, y: 62, scale: 0.9, depth: 0.9, front: true }]
  const framings = [['wide', 50], ['two', 0], ['medium', 100], ['close', 0], ['close', 100]] as const
  // Each move, and a push or a hold that goes on from where each move ended (the same picture, series_continuity).
  const cameras: Array<Pick<ShotSpec, 'camera' | 'cameraStart'>> = [
    ...(Object.keys(CAMERA_MOVES) as Array<keyof typeof CAMERA_MOVES>).map(move => ({ camera: move })),
    ...Object.values(CAMERA_MOVES).flatMap(([, end]) => (['push', 'static'] as const).map(camera => ({ camera, cameraStart: end }))),
  ]
  for (const camera of cameras) {
    const move = `${camera.camera}${camera.cameraStart ? ` from ${JSON.stringify(camera.cameraStart)}` : ''}`
    for (const [framing, focusX] of framings) {
      for (const set of [{}, { layers }]) {
        const scene = normalizeScene2D(compileSeriesShot(kits, shot({ ...camera, framing, background: { ...shot().background!, focusX }, ...set })))
        const evaluator = createSceneEvaluator(scene)
        const background = scene.layers.find(layer => layer.id === 'background')!
        for (let step = 0; step <= 20; step += 1) {
          const state = evaluator.renderedLayerStates(background, step / 20)[0]
          const margin = 50 * (state.scale - 1)
          assert.ok(Math.abs(state.x - 50) <= margin + 1e-6 && Math.abs(state.y - 50) <= margin + 1e-6,
            `${move} ${framing} focus ${focusX} ${set.layers ? 'layered' : 'flat'} at ${step / 20}: the plate's edge shows`)
        }
      }
    }
  }
})

test('a pan crosses the plate the way it is named and a pull ends wider than it starts', () => {
  const picture = (camera: CameraMove, progress: number) => {
    const scene = normalizeScene2D(compileSeriesShot(kits, shot({ camera, framing: 'wide' })))
    return createSceneEvaluator(scene).renderedLayerStates(scene.layers.find(layer => layer.id === 'background')!, progress)[0]
  }
  assert.ok(picture('pan-left', 1).x > picture('pan-left', 0).x, 'pan left: the picture slides right under the frame')
  assert.ok(picture('pan-right', 1).x < picture('pan-right', 0).x, 'pan right: the picture slides left')
  assert.ok(picture('pull', 1).scale < picture('pull', 0).scale && picture('push', 1).scale > picture('push', 0).scale)
  assert.ok(picture('drift', 1).x !== picture('drift', 0).x && picture('drift', 0).scale > 1)
})

// Kit animations in a Series shot (cast[].animation, and the walk sheet of an entrance) -------------------------

const sheetOf = (id: string, count: number, extra: Partial<KitAnimation> = {}, cell = { width: 300, height: 640 }): KitAnimation => ({
  sheet: { source: `/api/v1/file/${id}-sheet.png?workspace=cast`, width: cell.width * count, height: cell.height, count, columns: count, rows: 1, cell },
  frames: [], fps: 4, loop: 'loop', facing: 'right', reviewState: 'approved', ...extra })

function animated(extra: Record<string, KitAnimation> = {}, id = 'kevin') {
  const value = kit(id)
  value.animations = { walk: sheetOf('walk', 4), wave: sheetOf('wave', 3, { fps: 5, loop: 'pingpong', facing: 'front' }),
    angry: sheetOf('angry', 2, { fps: 3, loop: 'once', facing: 'front', reviewState: 'pending' }), ...extra }
  return value
}

const withSheets = { ...kits, kevin: animated() }
const ASPECT = 16 / 9
const poseLayer = (scene: ReturnType<typeof compileSeriesShot>) => scene.layers.find(layer => layer.id === 'kit-kevin-pose-base')!
const opacityAt = (scene: ReturnType<typeof compileSeriesShot>, id: string, time: number) => {
  const layer = scene.layers.find(item => item.id === id)!
  return createSceneEvaluator(scene).layerState(layer, time / scene.duration).opacity
}
const alone = (cast: ShotSpec['cast'], extra: Partial<ShotSpec> = {}) => shot({ framing: 'wide', camera: 'static', duration: 6, cast, lines: [], ...extra })

test('a kit with animations nobody plays compiles to the scene it always did', () => {
  const walk = { kitId: 'kevin', x: 60, motion: 'still' as const, enter: { fromX: -15, start: 0.5, end: 3.5, gait: 'walk' as const, step: 0.6, sway: 1.5 } }
  for (const spec of [shot(), alone([walk]), alone([{ kitId: 'kevin', x: 50 }], { lines: [shot().lines[0]] })]) {
    assert.deepEqual(compileSeriesShot({ ...kits, kevin: animated({ walk: sheetOf('walk', 4, { reviewState: 'pending' }) }) }, spec), compileSeriesShot(kits, spec),
      'a pending walk sheet leaves the bob as it was')
    if (!spec.cast[0].enter) assert.deepEqual(compileSeriesShot(withSheets, spec), compileSeriesShot(kits, spec))
  }
})

test('an animation swaps the pose for the sheet inside its window and hides the face while it plays', () => {
  const spec = alone([{ kitId: 'kevin', x: 50, blinks: [1.5, 3.15], animation: { id: 'wave', at: 1, duration: 2 } }],
    { lines: [{ id: 'l1', kitId: 'kevin', text: 'Hello Gary.', start: 0.35, end: 1.55, filename: 'l1.wav', cues }] })
  const scene = compileSeriesShot(withSheets, spec)
  const sheet = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!
  assert.equal(sheet.source, '/api/v1/file/wave-sheet.png?workspace=cast')
  assert.deepEqual(sheet.sequence, { kind: 'sheet', source: sheet.source, columns: 3, rows: 1, count: 3, fps: 5, loop: 'pingpong', start: 1 })
  assert.deepEqual(sheet.focus, { x: 50, y: ANIMATION_SHEET.feet * 100 })
  for (const [time, pose, drawn] of [[0.5, 1, 0], [0.99, 1, 0], [1.5, 0, 1], [2.9, 0, 1], [3.2, 1, 0], [5, 1, 0]]) {
    assert.equal(opacityAt(scene, poseLayer(scene).id, time), pose, `pose at ${time}`)
    assert.equal(opacityAt(scene, sheet.id, time), drawn, `sheet at ${time}`)
  }
  const face = scene.layers.filter(layer => layer.faceBinding?.poseLayerId === poseLayer(scene).id)
  assert.ok(face.length > 5, 'mouths and blink are bound to the pose')
  for (const time of [1.0, 1.5, 2.0, 2.9]) {
    assert.deepEqual(face.filter(layer => opacityAt(scene, layer.id, time) > 0).map(layer => layer.id), [], `no face over the sheet at ${time}`)
  }
  assert.equal(face.filter(layer => opacityAt(scene, layer.id, 3.2) > 0).length, 2, 'the rest mouth and the blink come back with the pose')
  assert.equal(face.filter(layer => opacityAt(scene, layer.id, 0.2) > 0).length, 1, 'only the rest mouth before it')
})

test('the sheet stands on the pose\'s ground line at the pose\'s height, in a flat or a vertical frame', () => {
  const spoken = alone([{ kitId: 'kevin', x: 50, animation: { id: 'wave', at: 1, duration: 2 } }])
  const scene = compileSeriesShot(withSheets, spoken)
  const stand = personTransform(withSheets.kevin, 'base', 'wide', 50, ASPECT, 1.25)
  const height = stand.scale * 100
  const sheet = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!
  const state = createSceneEvaluator(scene).layerState(sheet, 2 / scene.duration)
  assert.ok(Math.abs(state.y - (stand.y + height / 2)) < 0.01, 'the boots on the pose\'s bottom edge')
  assert.ok(Math.abs(state.scale * 100 * ANIMATION_SHEET.figure - height) < 0.01, 'the figure as tall as the pose')
  assert.equal(state.x, 50)
  // A cell wider than a vertical frame is limited by the frame\'s width: the feet line moves up the box with it.
  const wide = { ...withSheets, kevin: animated({ wave: sheetOf('wave', 3, { fps: 5, loop: 'pingpong', facing: 'front' }, { width: 400, height: 640 }) }) }
  const portrait = compileSeriesShot(wide, alone([{ kitId: 'kevin', x: 50, animation: { id: 'wave', at: 1, duration: 2 } }], { width: 1080, height: 1920 }))
  const tall = portrait.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!
  const aspect = 1080 / 1920, ratio = 400 / 640
  const base = personTransform(wide.kevin, 'base', 'wide', 50, aspect, 1.25)
  const box = createSceneEvaluator(portrait).layerState(tall, 2 / portrait.duration)
  assert.ok(Math.abs(tall.focus!.y - (50 + (ANIMATION_SHEET.feet - 0.5) * 100 * aspect / ratio)) < 0.01)
  assert.ok(Math.abs(box.scale * 100 * aspect / ratio * ANIMATION_SHEET.figure - base.scale * 100) < 0.01, 'a width-limited cell is drawn as tall as the pose')
})

test('an animation without a duration lasts one pass of its sheet, and a once sheet holds its last cell', () => {
  const scene = compileSeriesShot(withSheets, alone([{ kitId: 'kevin', x: 50, animation: { id: 'wave' } }]))
  const sheet = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!
  assert.equal(sheet.sequence?.kind === 'sheet' && sheet.sequence.start, 0)
  assert.equal(opacityAt(scene, sheet.id, 0), 1, 'from the first frame')
  assert.equal(opacityAt(scene, sheet.id, 0.5), 1)
  assert.equal(opacityAt(scene, sheet.id, 1.5), 0, 'wave: 3 cells back and forth at 5 fps is 4 steps, 0.8 s')
  const angry = compileSeriesShot({ ...kits, kevin: animated({ angry: sheetOf('angry', 2, { fps: 3, loop: 'once', facing: 'front' }) }) },
    alone([{ kitId: 'kevin', x: 50, animation: { id: 'angry', at: 1, duration: 3, loop: 'once' }, }]))
  assert.equal(opacityAt(angry, 'kit-kevin-sheet-angry', 2.5), 1, 'the hold in the middle of the window is fully up')
  const leaving = opacityAt(angry, 'kit-kevin-sheet-angry', 3.9)
  assert.ok(leaving > 0 && leaving < 1, `an expression fades out: ${leaving}`)
  assert.equal(opacityAt(angry, 'kit-kevin-sheet-angry', 4.1), 0)
  const angrySheet = angry.layers.find(layer => layer.id === 'kit-kevin-sheet-angry')!
  assert.equal(angrySheet.sequence?.kind === 'sheet' && sequenceFrame(angrySheet.sequence, 3.9), 1, 'the last cell is held through the fade')
  const looped = compileSeriesShot(withSheets, alone([{ kitId: 'kevin', x: 50, animation: { id: 'wave', at: 1, loop: 'loop' } }]))
  const sequence = looped.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!.sequence
  assert.equal(sequence?.kind === 'sheet' && sequence.loop, 'loop', 'the cast entry may choose the loop')
})

const BOTH_EDGES = { left: [[0, 1]], right: [[0, 1]], bottom: [[0, 1]] } as const

/** Height a pose occupies (% of the frame), the same rule as seriesShot.drawnHeight. */
function drawn(size: { width: number; height: number }, scale: number, aspect: number) {
  const ratio = size.width / size.height
  return ratio < aspect ? scale * 100 : scale * 100 * aspect / ratio
}

/** The sheet's opaque figure, from the unpinned layer state: feet at state.y, figure share of the cell. */
function figureBox(scene: ReturnType<typeof compileSeriesShot>, layerId: string, cell = { width: 300, height: 640 }) {
  const layer = scene.layers.find(item => item.id === layerId)!
  const state = createSceneEvaluator(scene).layerState(layer, 0.5)
  const aspect = scene.width / scene.height
  const ratio = cell.width / cell.height
  const figure = ratio < aspect ? state.scale * 100 * ANIMATION_SHEET.figure : state.scale * 100 * aspect / ratio * ANIMATION_SHEET.figure
  return { state, figure, center: state.y - figure / 2, top: state.y - figure }
}

test('a medium-shot expression matches the snapped pose, and a portrait face sheet is only the head', () => {
  const square = kit('kevin')
  square.base = { ...square.base, width: 1024, height: 1024, cut: BOTH_EDGES } as CharacterKit['base']
  square.animations = { angry: sheetOf('angry', 2, { fps: 3, loop: 'once', facing: 'front', scaleBy: 'face' }) }
  const bare = kit('kevin')
  bare.base = { ...square.base }
  const placed = { kitId: 'kevin', x: 46, motion: 'still' as const }
  const quiet = shot({ framing: 'medium', camera: 'static', duration: 4, lines: [], cast: [placed] })
  assert.deepEqual(compileSeriesShot({ kevin: square }, quiet), compileSeriesShot({ kevin: bare }, quiet),
    'no animation: an approved sheet that nobody plays leaves the edge-snapped pose as it was')
  const scene = compileSeriesShot({ kevin: square }, shot({ framing: 'medium', camera: 'static', duration: 4, lines: [],
    cast: [{ ...placed, animation: { id: 'angry', at: 0.4 } }] }))
  const pose = scene.layers.find(layer => layer.id === 'kit-kevin-pose-base')!
  const plain = personTransform(square, 'base', 'medium', 46, ASPECT)
  assert.ok(Math.abs(pose.transform.scale - plain.scale) > 0.05, 'both edges actually change the pose scale')
  const snapped = castTransform(square, placed, 'medium', ASPECT)
  assert.deepEqual({ x: pose.transform.x, y: pose.transform.y, scale: pose.transform.scale }, snapped)
  const box = figureBox(scene, 'kit-kevin-sheet-angry')
  const poseHeight = drawn({ width: 1024, height: 1024 }, pose.transform.scale, ASPECT)
  assert.ok(Math.abs(box.figure - poseHeight) / poseHeight < 0.01, `figure ${box.figure} vs pose ${poseHeight}`)
  assert.ok(Math.abs(box.center - pose.transform.y) / poseHeight < 0.01, `center ${box.center} vs ${pose.transform.y}`)
  assert.ok(Math.abs(box.state.x - pose.transform.x) < 0.05, `x ${box.state.x} vs ${pose.transform.x}`)
  assert.ok(opacityAt(scene, 'kit-kevin-sheet-angry', 1.6) === 1, 'default expression hold is fully up past one pass')
  assert.ok(opacityAt(scene, 'kit-kevin-sheet-angry', 2.8) > 0, 'still visible at 2.4 s of a 2.5 s hold')
  assert.equal(opacityAt(scene, 'kit-kevin-sheet-angry', 3.0), 0, 'the hold ends at 2.5 s')
  const sheet = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-angry')!
  assert.equal(sheet.sequence?.kind === 'sheet' && sequenceFrame(sheet.sequence, 2.8), 1, 'the last cell is held')

  const body = animated({ angry: sheetOf('angry', 2, { fps: 3, loop: 'once', facing: 'front', scaleBy: 'face' }),
    wave: sheetOf('wave', 3, { fps: 5, loop: 'pingpong', facing: 'front', scaleBy: 'base' }) })
  const head = compileSeriesShot({ kevin: body }, shot({ framing: 'medium', camera: 'static', duration: 4, lines: [],
    cast: [{ kitId: 'kevin', x: 50, motion: 'still', animation: { id: 'angry', at: 0.2, duration: 2.5 } }] }))
  const headPose = head.layers.find(layer => layer.id === 'kit-kevin-pose-base')!
  const headBox = figureBox(head, 'kit-kevin-sheet-angry')
  const bodyHeight = drawn({ width: 500, height: 1000 }, headPose.transform.scale, ASPECT)
  assert.ok(Math.abs(headBox.figure / bodyHeight - ANIMATION_SHEET.head / ANIMATION_SHEET.faceShare) < 0.01, `head share ${headBox.figure / bodyHeight}`)
  const crown = headPose.transform.y - bodyHeight / 2
  assert.ok(Math.abs(headBox.top - crown) / bodyHeight < 0.01, `hung from the crown ${headBox.top} vs ${crown}`)
  const gesture = compileSeriesShot({ kevin: body }, shot({ framing: 'medium', camera: 'static', duration: 4, lines: [],
    cast: [{ kitId: 'kevin', x: 50, motion: 'still', animation: { id: 'wave', at: 1, duration: 2 } }] }))
  const wavePose = gesture.layers.find(layer => layer.id === 'kit-kevin-pose-base')!
  const waveBox = figureBox(gesture, 'kit-kevin-sheet-wave')
  const waveHeight = drawn({ width: 500, height: 1000 }, wavePose.transform.scale, ASPECT)
  assert.ok(Math.abs(waveBox.figure - waveHeight) / waveHeight < 0.01, 'a gesture keeps the whole pose')
  assert.equal(opacityAt(gesture, 'kit-kevin-sheet-wave', 1.05), 1, 'a gesture still cuts in')
  assert.equal(opacityAt(gesture, 'kit-kevin-sheet-wave', 2.95), 1)
  assert.equal(opacityAt(gesture, 'kit-kevin-sheet-wave', 3.05), 0)
})

test('an animation the kit cannot play fails the compile with the reason', () => {
  const failure = (animation: NonNullable<ShotSpec['cast'][number]['animation']>) => {
    const result = runSeriesShot({ mode: 'shot', kits: withSheets, shot: alone([{ kitId: 'kevin', x: 50, animation }]) })
    return result.ok ? '' : result.message
  }
  assert.match(failure({ id: 'zoom' }), /has no animation zoom/)
  assert.match(failure({ id: 'angry' }), /angry.*pending approval.*Characters/)
})

test('an approved walk sheet plays through the whole entrance on the same slide, without the bob', () => {
  const enter = { fromX: -15, start: 0.5, end: 3.5, gait: 'walk' as const, step: 0.6, sway: 1.5 }
  const spec = alone([{ kitId: 'kevin', x: 60, motion: 'still', enter }])
  const scene = compileSeriesShot(withSheets, spec)
  const sheet = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-walk-in')!
  assert.deepEqual(sheet.sequence, { kind: 'sheet', source: '/api/v1/file/walk-sheet.png?workspace=cast', columns: 4, rows: 1, count: 4,
    fps: Math.round(4 / (2 * 0.6) * 1000) / 1000, loop: 'loop', start: 0.5 }, 'a cycle is two steps: the feet land on the steps')
  const evaluator = createSceneEvaluator(scene)
  const at = (time: number) => evaluator.layerState(sheet, time / scene.duration)
  assert.deepEqual([0.2, 0.6, 2, 3.4, 3.6].map(time => opacityAt(scene, sheet.id, time)), [0, 1, 1, 1, 0])
  assert.deepEqual([0.2, 0.6, 3.6].map(time => opacityAt(scene, poseLayer(scene).id, time)), [1, 0, 1], 'the pose is back on the mark')
  assert.ok(Math.abs(at(2).x - 22.5) < 1e-6, 'halfway across at an even pace')
  assert.ok(Math.abs(at(0.8).y - at(1.1).y) < 1e-9 && Math.abs(at(1.4).y - at(1.1).y) < 1e-9 && at(0.8).rotation === 0, 'feet on the line: no bob, no sway')
  assert.ok(Math.abs(evaluator.layerState(poseLayer(scene), 3.6 / scene.duration).x - 60) < 1e-6)
  assert.equal(sheet.sequence?.kind === 'sheet' && sheet.sequence.mirror, undefined, 'a right-facing sheet entering from the left is not mirrored')
})

test('a walk sheet is mirrored when the character walks against the way the sheet looks', () => {
  const walkFrom = (fromX: number, facing: 'left' | 'right' | 'front') => {
    const kitWith = { ...kits, kevin: animated({ walk: sheetOf('walk', 4, { facing }) }) }
    const scene = compileSeriesShot(kitWith, alone([{ kitId: 'kevin', x: 40, motion: 'still', enter: { fromX, start: 0.5, end: 2.5, gait: 'walk', step: 0.5, sway: 0 } }]))
    const sequence = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-walk-in')!.sequence
    return sequence?.kind === 'sheet' ? sequence.mirror : 'no sheet'
  }
  assert.deepEqual([walkFrom(115, 'right'), walkFrom(115, 'left'), walkFrom(-15, 'left'), walkFrom(-15, 'right'), walkFrom(115, 'front')],
    [true, undefined, true, undefined, undefined])
})

test('an animation after the walk-in plays when the walk ends', () => {
  const enter = { fromX: -15, start: 0.5, end: 3.5, gait: 'walk' as const, step: 0.6, sway: 1.5 }
  const scene = compileSeriesShot(withSheets, alone([{ kitId: 'kevin', x: 60, motion: 'still', enter, animation: { id: 'wave', at: 3.5, duration: 1 } }]))
  assert.deepEqual([3.4, 3.6, 4.4, 4.6].map(time => [opacityAt(scene, 'kit-kevin-sheet-walk-in', time), opacityAt(scene, 'kit-kevin-sheet-wave', time), opacityAt(scene, poseLayer(scene).id, time)]),
    [[1, 0, 0], [0, 1, 0], [0, 1, 0], [0, 0, 1]], 'the pose is hidden from the first step to the end of the wave')
  const early = compileSeriesShot(withSheets, alone([{ kitId: 'kevin', x: 60, motion: 'still', enter, animation: { id: 'wave', at: 2, duration: 3 } }]))
  assert.equal(opacityAt(early, 'kit-kevin-sheet-wave', 3.0), 0, 'a wave that would start inside the walk starts when it ends')
  assert.equal(opacityAt(early, 'kit-kevin-sheet-wave', 3.6), 1)
})

test('stop-motion holds apply to a sheet: the cell follows the held picture time', () => {
  const scene = compileSeriesShot(withSheets, alone([{ kitId: 'kevin', x: 50, animation: { id: 'wave', at: 1, duration: 2 } }], { motionStep: 4 }))
  assert.equal(scene.motionStep, 4)
  const sequence = scene.layers.find(layer => layer.id === 'kit-kevin-sheet-wave')!.sequence!
  const times = [1.0, 1.12, 1.2, 1.28, 1.34, 1.5]
  const held = times.map(time => sequenceFrame(sequence, heldFrameTime(time, scene.fps, 4)))
  assert.deepEqual(held, [0, 0, 0, 0, 1, 2], 'the cell changes only on a new hold of four frames, counted from the window\'s start')
  assert.notDeepEqual(held, times.map(time => sequenceFrame(sequence, time)), 'the sheet follows the held picture, not the free clock')
})
