import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { backgroundView, compileSeriesShot, FRAMING, personTransform, type ShotSpec } from '../scripts/seriesShot.ts'
import { expectedHeight, frameY, perspectiveHeight, plateY, stageStanding, type Stage } from '../scripts/seriesStage.ts'

type Row = { stage: string; zoom: number; viewY: number; heightM: number; depth: number; feetY: number; height: number }
const TABLE = JSON.parse(readFileSync(new URL('../../tests/fixtures/series_stage_table.json', import.meta.url), 'utf8')) as
  { stage: Stage; farStage: Stage; rows: Row[] }
const OFFICE = TABLE.stage

const STATES = ['closed', 'small', 'wide', 'round', 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
const asset = (id: string, kind: 'image' | 'overlay' = 'overlay', size?: { width: number; height: number }): CharacterKitAsset => ({
  id, name: id, source: `/api/v1/file/${id}.png?workspace=cast`, kind, alphaStatus: 'transparent', reviewState: 'approved', ...size })

function kit(id: string, extra: Partial<CharacterKitAsset> = {}): CharacterKit {
  const value = createCharacterKit(id)
  value.id = id
  value.base = { ...asset(`${id}-base`, 'image', { width: 450, height: 1000 }), ...extra }
  value.poses = { bust: { ...asset(`${id}-bust`, 'image', { width: 700, height: 800 }), cut: { bottom: [[0.1, 0.9]] } } as CharacterKitAsset }
  value.mouth = Object.fromEntries(STATES.map(state => [state, asset(`${id}-mouth-${state}`)]))
  value.mouthMapping = { rest: 'closed', M: 'pressed', A: 'wide', E: 'medium', I: 'small', O: 'round', U: 'pucker', F: 'bite', L: 'tongue' }
  value.eyes = { blink: asset(`${id}-blink`) }
  const anchors = { mouth: { offsetX: 0, offsetY: -8, scale: 0.1, rotation: 0 }, eyes: { offsetX: 0, offsetY: -22, scale: 0.18, rotation: 0 } }
  value.anchors = { base: anchors, bust: anchors }
  return value
}

const kits = { lucky: kit('lucky'), bigman: kit('bigman') }

function shot(overrides: Partial<ShotSpec> = {}): ShotSpec {
  return {
    name: 'Despacho · s01', workspace: 'cast', width: 1920, height: 1080, fps: 24, duration: 4, framing: 'wide',
    background: { source: '/api/v1/file/office.png?workspace=cast', kind: 'image' },
    cast: [{ kitId: 'lucky', x: 34 }, { kitId: 'bigman', x: 66 }], lines: [], camera: 'static', ...overrides,
  }
}

const staged = (overrides: Partial<ShotSpec> = {}) => shot({ stage: OFFICE, ...overrides })
const pose = (spec: ShotSpec, kitId: string) => compileSeriesShot(kits, spec).layers.find(layer => layer.characterKitRef?.id === kitId && !layer.faceBinding)!
/** Feet line and figure height (% of the frame) of a 450x1000 pose drawn at a layer transform: its image is contained in the frame
 * and the figure is the image less the rig's 2 % margin of its longest side above and below. */
const body = ({ transform }: { transform: { y: number; scale: number } }) => {
  const image = transform.scale * 100
  return { height: image * 0.96, feet: transform.y + image / 2 - image * 0.02 }
}
/** The layer scale is stored to 0.001 (0.1 % of the frame height), so a drawn height is exact to 0.06. */
const near = (actual: number, expected: number, tolerance = 0.06) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not ${expected}`)

test('the stage formula gives the hand-checked table', () => {
  for (const row of TABLE.rows) {
    const found = stageStanding((TABLE as unknown as Record<string, Stage>)[row.stage], row.heightM, row.depth, { zoom: row.zoom, y: row.viewY })
    near(found.feetY, row.feetY, 0.002)
    near(found.height, row.height, 0.002)
  }
})

test('plate and frame coordinates convert both ways and the inverse of standing is the expected height', () => {
  near(frameY({ zoom: 1.12, y: 50 }, 0.72), 74.64, 1e-9)
  near(plateY({ zoom: 1.12, y: 50 }, 74.64), 0.72, 1e-9)
  const view = { zoom: 1.12, y: 50 }
  const found = stageStanding(OFFICE, 1.6, 0.4, view)
  near(expectedHeight(OFFICE, 1.6, found.feetY, view), found.height, 0.01)
  near(perspectiveHeight(OFFICE, 2, 0.72), 0.62, 1e-9)
})

test('with a stage a wide shot sizes each person by their height and depth', () => {
  const lucky = body(pose(staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8 }, { kitId: 'bigman', x: 66, heightM: 1.4 }] }), 'lucky'))
  const bigman = body(pose(staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8 }, { kitId: 'bigman', x: 66, heightM: 1.4 }] }), 'bigman'))
  near(lucky.height, 80.352)
  near(lucky.feet, 94)
  assert.ok(lucky.height > 62, 'a foreground adult is taller than the 2 m door (62 % of the frame)')
  near(bigman.height / lucky.height, 1.4 / 1.8, 0.002)
  const far = body(pose(staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8, depth: 0 }] }), 'lucky'))
  near(far.height, 55.8)
  near(far.feet, 72)
})

test('a shorter character placed further back stays in proportion with the one in front', () => {
  const spec = staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8, depth: 1 }, { kitId: 'bigman', x: 66, heightM: 1.4, depth: 0.3 }] })
  const lucky = body(pose(spec, 'lucky')), bigman = body(pose(spec, 'bigman'))
  assert.ok(bigman.height < lucky.height * 0.7, 'smaller than the 0.78 of the same depth')
  assert.ok(bigman.feet < lucky.feet, 'and higher in the frame')
})

test('a two shot follows the plate zoom and puts people on their feet', () => {
  const spec = staged({ framing: 'two', cast: [{ kitId: 'lucky', x: 34, heightM: 1.8 }] })
  const view = backgroundView(spec.background!, 'two')
  assert.deepEqual([view.zoom, view.y], [1.12, 50])
  const lucky = body(pose(spec, 'lucky'))
  near(lucky.height, 84.102)
  near(lucky.feet, 94)
})

test('a lone person in a wide shot keeps no single-person boost and an explicit boost still multiplies', () => {
  const alone = body(pose(staged({ cast: [{ kitId: 'lucky', x: 50, heightM: 1.8 }] }), 'lucky'))
  near(alone.height, 80.352)
  const boosted = body(pose(staged({ cast: [{ kitId: 'lucky', x: 50, heightM: 1.8, boost: 0.5 }] }), 'lucky'))
  near(boosted.height, 40.176)
  near(boosted.feet, 94)
})

test('without a stage everything compiles as it did, whatever depth and heightM say', () => {
  const plain = compileSeriesShot(kits, shot())
  const noted = compileSeriesShot(kits, shot({ cast: [{ kitId: 'lucky', x: 34, depth: 0.2, heightM: 1.4 }, { kitId: 'bigman', x: 66, depth: 1 }] }))
  assert.deepEqual(noted, plain)
  const legacy = personTransform(kits.lucky, 'base', 'wide', 34, 1920 / 1080)
  assert.equal(pose(shot(), 'lucky').transform.scale, legacy.scale)
  assert.equal(legacy.scale, FRAMING.wide.scale)
  for (const framing of ['medium', 'close', 'insert'] as const) {
    const base = compileSeriesShot(kits, shot({ framing, cast: [{ kitId: 'lucky', x: 50 }] }))
    assert.deepEqual(compileSeriesShot(kits, staged({ framing, cast: [{ kitId: 'lucky', x: 50, depth: 0, heightM: 1.8 }] })), base, `${framing} keeps its eye-line framing`)
  }
  assert.deepEqual(compileSeriesShot(kits, staged({ background: undefined })), compileSeriesShot(kits, shot({ background: undefined })), 'a stage needs the plate')
})

test('a bust, a manual transform and a perch keep their own placement', () => {
  const bust = shot({ cast: [{ kitId: 'lucky', x: 34, poseId: 'bust', heightM: 1.8 }] })
  assert.deepEqual(compileSeriesShot(kits, { ...bust, stage: OFFICE }), compileSeriesShot(kits, bust), 'a pose cut at the waist is not a whole figure')
  const manual = staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8, transform: { x: 34, y: 60, scale: 0.4 } }] })
  assert.equal(pose(manual, 'lucky').transform.scale, 0.4)
  const perched = staged({ cast: [{ kitId: 'lucky', x: 34, heightM: 1.8, perch: { source: '/api/v1/file/desk.png?workspace=cast', width: 800, height: 250 } }] })
  assert.equal(pose(perched, 'lucky').transform.scale, 0.29, 'the perch preset')
})

test('a vertical frame and a detail still map the plate through their own view', () => {
  const portrait = staged({ width: 1080, height: 1920, cast: [{ kitId: 'lucky', x: 50, heightM: 1.8 }] })
  const found = body(pose(portrait, 'lucky'))
  near(found.feet, 94)
  const detail = staged({ background: { source: 'o.png', kind: 'image', detail: { x: 50, y: 70, zoom: 2 } }, cast: [{ kitId: 'lucky', x: 50, heightM: 1.8 }] })
  const view = backgroundView(detail.background!, 'wide')
  assert.equal(view.zoom, 2)
  near(view.y, Math.max(0, Math.min(100, 50 - (0.7 - 0.5) * 100 * 2)), 1e-9)
})
