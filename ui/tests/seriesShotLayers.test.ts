import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate'
import { normalizeScene2D } from '../src/lib/scene2d/normalize'
import type { Scene } from '../src/types'
import { CAST_DEPTH, compileSeriesShot, depthParallax, FAR_PARALLAX, type SetLayerSpec, type ShotSpec } from '../scripts/seriesShot.ts'

const STATES = ['closed', 'small', 'wide', 'round', 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
const asset = (id: string, kind: 'image' | 'overlay' = 'overlay', size?: { width: number; height: number }): CharacterKitAsset => ({
  id, name: id, source: `/api/v1/file/${id}.png?workspace=cast`, kind, alphaStatus: 'transparent', reviewState: 'approved', ...size })

function kit(id: string): CharacterKit {
  const value = createCharacterKit(id)
  value.id = id
  value.base = asset(`${id}-base`, 'image', { width: 500, height: 1000 })
  value.poses = {}
  value.mouth = Object.fromEntries(STATES.map(state => [state, asset(`${id}-mouth-${state}`)]))
  value.mouthMapping = { rest: 'closed', M: 'pressed', A: 'wide', E: 'medium', I: 'small', O: 'round', U: 'pucker', F: 'bite', L: 'tongue' }
  value.eyes = { blink: asset(`${id}-blink`) }
  const anchors = { mouth: { offsetX: 0, offsetY: -8, scale: 0.1, rotation: 0 }, eyes: { offsetX: 0, offsetY: -22, scale: 0.18, rotation: 0 } }
  value.anchors = { base: anchors }
  return value
}

const kits = { kevin: kit('kevin'), gary: kit('gary') }

function shot(overrides: Partial<ShotSpec> = {}): ShotSpec {
  return {
    name: 'Pilot · s01', workspace: 'cast', width: 1920, height: 1080, fps: 24, duration: 4, framing: 'two',
    background: { source: '/api/v1/file/garage.png?workspace=cast', kind: 'image', focusX: 40 },
    cast: [{ kitId: 'kevin', x: 34 }, { kitId: 'gary', x: 66 }],
    lines: [{ id: 's01-l1', kitId: 'kevin', text: 'Hello Gary.', start: 0.35, end: 1.55, filename: 'ln-s01-l1.wav',
      cues: { mouthCues: [{ start: 0, end: 0.3, value: 'B' }, { start: 0.3, end: 0.8, value: 'D' }] } }],
    camera: 'push', ...overrides,
  }
}

const digest = (value: unknown) => createHash('sha1').update(JSON.stringify(value)).digest('hex').slice(0, 16)
const layer = (id: string, depth: number, extra: Partial<SetLayerSpec> = {}): SetLayerSpec => ({
  id, name: id, source: `/api/v1/file/${id}.png?workspace=cast`, kind: 'image', x: 50, y: 50, scale: 1, depth, ...extra })
// Listed out of depth order on purpose: the compiler draws the farthest first.
const SET = [layer('columns', 0.45), layer('pillar', 0.95, { front: true, x: 10, scale: 0.9 }), layer('arches', 0.15),
  layer('fog', 0.8, { front: true, opacity: 0.5, drift: 24, scale: 1.2 })]

/** Painted state of a layer at the start and the end of the shot, camera applied. */
function states(scene: Scene, id: string) {
  const normalized = normalizeScene2D(scene)
  const evaluator = createSceneEvaluator(normalized)
  const target = normalized.layers.find(item => item.id === id)!
  return [0, 1].map(progress => evaluator.renderedLayerStates(target, progress)[0])
}
const growth = (scene: Scene, id: string) => { const [start, end] = states(scene, id); return end.scale / start.scale }

test('a shot without set layers compiles to exactly the document it did before layers existed', () => {
  const golden = {
    push: [shot(), '2235a74a61cfeb0e'],
    plate: [shot({ background: { source: '/api/v1/file/plate.mp4?workspace=cast', kind: 'video' }, camera: 'static', framing: 'wide',
      props: [{ id: 'prop-1', name: 'Lamp', source: '/api/v1/file/lamp.png?workspace=cast', x: 20, y: 60, scale: 0.3 }] }), '6fdca5b17a857744'],
    portrait: [shot({ width: 1080, height: 1920, framing: 'medium', cast: [{ kitId: 'kevin', x: 50 }] }), '1bf618a8e30a766f'],
    empty: [shot({ layers: [], castDepth: 0.8 }), '2235a74a61cfeb0e'],
  } as const
  for (const [name, [spec, hash]] of Object.entries(golden)) assert.equal(digest(compileSeriesShot(kits, spec)), hash, name)
  // And the whole frame still pushes in as one: the background takes the camera's full zoom.
  assert.ok(Math.abs(growth(compileSeriesShot(kits, shot()), 'background') - 1.07) < 1e-9)
})

test('back layers sit between the background and the cast, front layers over the cast, farthest first', () => {
  const scene = compileSeriesShot(kits, shot({ layers: SET, props: [{ id: 'prop-1', name: 'Lamp', source: '/api/v1/file/lamp.png?workspace=cast', x: 20, y: 70, scale: 0.3 }] }))
  const z = (id: string) => scene.layers.find(item => item.id === id)!.z
  const cast = scene.layers.filter(item => item.characterKitRef)
  const castLow = Math.min(...cast.map(item => item.z)), castHigh = Math.max(...cast.map(item => item.z))
  assert.ok(z('background') < z('arches') && z('arches') < z('columns') && z('columns') < z('prop-1') && z('prop-1') < castLow)
  assert.ok(castHigh < z('fog') && z('fog') < z('pillar') && z('pillar') < z('camera'))
  const painted = normalizeScene2D(scene).layers.filter(item => item.type !== 'camera').sort((a, b) => a.z - b.z).map(item => item.id)
  assert.deepEqual([painted[0], painted[1], painted[2]], ['background', 'arches', 'columns'])
  assert.deepEqual(painted.slice(-2), ['fog', 'pillar'])
})

test('a push moves and grows each layer by its depth: far layers less than the cast, near ones more', () => {
  const scene = compileSeriesShot(kits, shot({ layers: SET }))
  const byId = Object.fromEntries(scene.layers.map(item => [item.id, item]))
  assert.equal(depthParallax(0), FAR_PARALLAX)
  assert.equal(depthParallax(CAST_DEPTH), 1)
  assert.equal(depthParallax(1, 0.2), 2, 'capped')
  for (const item of SET) {
    assert.equal(byId[item.id].parallax, depthParallax(item.depth))
    assert.equal(byId[item.id].parallaxZoom, true)
  }
  assert.equal(byId.background.parallax, FAR_PARALLAX)
  assert.equal(byId.background.parallaxZoom, true, 'the background is the far plane of a layered set')
  // The camera zooms 1 -> 1.07: each layer grows by its own share, linear in depth from the background's.
  const zoom = (id: string) => growth(scene, id) - 1
  assert.ok(Math.abs(zoom('background') - 0.07 * FAR_PARALLAX) < 1e-9)
  const pose = scene.layers.find(item => item.characterKitRef && item.type === 'image' && !item.faceBinding)!
  assert.ok(Math.abs(zoom(pose.id) - 0.07) < 1e-9, 'the cast pushes in as it always did')
  const slopes = SET.map(item => (zoom(item.id) - zoom('background')) / item.depth)
  // Parallax values are rounded to 0.001, hence the tolerance.
  for (const slope of slopes) assert.ok(Math.abs(slope - slopes[0]) < 1e-4, `offset proportional to depth: ${slopes}`)
  assert.ok(zoom('arches') < zoom('columns') && zoom('columns') < zoom(pose.id) && zoom(pose.id) < zoom('fog') && zoom('fog') < zoom('pillar'))
  // The camera also tilts up 1.5 %: the frame centre of each layer travels by its depth too.
  const travel = (id: string) => { const [start, end] = states(scene, id); return end.y - start.y }
  assert.ok(travel('background') < travel('arches') && travel('arches') < travel('columns') && travel('columns') < travel('fog'))
  // A pillar off to the side slides outward faster than the cast as the camera closes in.
  const [pillarStart, pillarEnd] = states(scene, 'pillar')
  assert.ok(pillarEnd.x < pillarStart.x - 2, `pillar ${pillarStart.x} -> ${pillarEnd.x}`)
})

test('the cast depth sets which layers move less than the cast', () => {
  const deep = compileSeriesShot(kits, shot({ layers: [layer('wall', 0.6)], castDepth: 0.9 }))
  const level = compileSeriesShot(kits, shot({ layers: [layer('wall', 0.6)] }))
  assert.ok(growth(deep, 'wall') < growth(level, 'wall'))
  assert.ok(Math.abs(growth(level, 'wall') - 1.07) < 1e-9, 'a layer at the cast depth moves with the cast')
})

test('drift slides a layer on its own and a looping video plays as a layer, also in a static shot', () => {
  const scene = compileSeriesShot(kits, shot({ camera: 'static', layers: [layer('fog', 0.8, { drift: -48, opacity: 0.4 }),
    layer('smoke', 0.3, { kind: 'video', source: '/api/v1/file/smoke.webm?workspace=cast' })] }))
  const fog = scene.layers.find(item => item.id === 'fog')!
  assert.equal(fog.animation.end.x - fog.animation.start.x, -48 / 1920 * 100 * 4)
  assert.equal(fog.transform.opacity, 0.4)
  const [start, end] = states(scene, 'fog')
  assert.ok(Math.abs(end.x - start.x + 10) < 1e-9, '48 px/s to the left for 4 s is 10 % of a 1920 px frame')
  const smoke = scene.layers.find(item => item.id === 'smoke')!
  assert.equal(smoke.type, 'video')
  assert.equal(smoke.animation.loop, true)
  assert.equal(scene.layers.some(item => item.type === 'camera'), false)
})
