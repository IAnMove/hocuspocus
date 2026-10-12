import assert from 'node:assert/strict'
import test from 'node:test'
import { spawnSync } from 'node:child_process'
import { Scene } from 'three'
import { GROUND_RECIPES, GROUND_STYLES, GroundStyleRuntime, groundColor, groundPixels, isGroundStyle, parseGroundScroll } from '../src/features/scene3d/groundStyles.ts'
import { settleColumns } from '../src/features/scene3d/imageSettle.ts'
import { parseEnvironment, cinematicReflectorVisible } from '../src/features/scene3d/cinematicSettings.ts'
import { parseImageLook } from '../src/features/scene3d/imageLook.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { stageParallaxSet } from '../src/features/scene3d/parallaxSet.ts'
import tables from '../../app/shared/world3d_modifiers.json' with { type: 'json' }

const SIZE = 64

function compile(scene3d, duration = 4) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', 'scripts/production-scene3d.mjs'], {
    cwd: new URL('..', import.meta.url), input: JSON.stringify({ scene3d, duration }), encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

const mean = (pixels, pick) => {
  let sum = 0, n = 0
  for (let i = 0; i < pixels.length; i += 4) { sum += pick(pixels, i); n++ }
  return sum / n
}

test('the ground styles are the shared table\'s, each paints its own colours and the same seed paints the same tile', () => {
  assert.deepEqual([...GROUND_STYLES], Object.keys(tables.grounds), 'one list for the compiler, the checks and the renderer')
  const tints = GROUND_STYLES.map(style => {
    const pixels = groundPixels(style, 3, SIZE)
    assert.deepEqual(pixels, groundPixels(style, 3, SIZE), `${style} is deterministic`)
    assert.notDeepEqual(pixels, groundPixels(style, 4, SIZE), `${style} changes with the seed`)
    return [0, 1, 2].map(channel => mean(pixels, (p, i) => p[i + channel]))
  })
  const [grass, , sand, asphalt, , snow] = tints
  assert.ok(grass[1] > grass[0] && grass[1] > grass[2], 'grass is green')
  assert.ok(sand[0] > sand[2] + 40, 'sand is warm')
  assert.ok(asphalt.every(channel => channel < 90), 'asphalt is dark')
  assert.ok(snow.every(channel => channel > 170), 'snow is bright')
  assert.match(groundColor('grass'), /^#[\da-f]{6}$/)
  assert.ok(isGroundStyle('meadow') && !isGroundStyle('lava') && !isGroundStyle('tiles'))
})

test('a tile has no seam: its first and last columns differ no more than any two neighbours', () => {
  for (const style of ['grass', 'sand', 'cobble']) {
    const pixels = groundPixels(style, 1, SIZE)
    const column = x => Array.from({ length: SIZE }, (_, y) => pixels[(y * SIZE + x) * 4 + 1])
    const gap = (a, b) => column(a).reduce((sum, value, y) => sum + Math.abs(value - column(b)[y]), 0) / SIZE
    const inner = Array.from({ length: SIZE - 1 }, (_, x) => gap(x, x + 1))
    const typical = inner.sort((a, b) => a - b)[Math.floor(inner.length * 0.9)]
    assert.ok(gap(SIZE - 1, 0) <= typical * 1.5 + 4, `${style}: seam ${gap(SIZE - 1, 0).toFixed(1)} vs ${typical.toFixed(1)}`)
  }
})

test('a scroll is a speed along a normalised direction; anything else is dropped', () => {
  assert.deepEqual(parseGroundScroll({ speed: 2, direction: [3, 4] }), { speed: 2, direction: [0.6, 0.8] })
  assert.equal(parseGroundScroll({ speed: 0, direction: [1, 0] }), undefined)
  assert.equal(parseGroundScroll({ speed: 2, direction: [0, 0] }), undefined)
  assert.equal(parseGroundScroll({ speed: 'fast' }), undefined)
  const environment = parseEnvironment({ reflectiveFloor: true, bloom: 0, floorStyle: 'grass', groundScroll: { speed: 3, direction: [-1, 0] }, groundSeed: 5 })
  assert.equal(environment.floorStyle, 'grass')
  assert.deepEqual(environment.groundScroll, { speed: 3, direction: [-1, 0] })
  assert.equal(environment.groundSeed, 5)
  assert.equal(cinematicReflectorVisible(environment), false, 'a ground style hides the mirror floor')
  assert.equal(parseEnvironment({ floorStyle: 'tiles', groundScroll: { speed: 3, direction: [1, 0] } }).groundScroll, undefined)
})

test('the runtime draws the plane and the pieces, slides them with the scroll and clears them where the cast stands', () => {
  const scene = new Scene()
  const ground = new GroundStyleRuntime(scene)
  assert.equal(ground.sync('grass', 0, undefined, 1, [[0, 0]]), true)
  const plane = ground.root.children.find(child => child.name === 'ground-grass')
  const tufts = ground.root.children.find(child => child.name === 'ground-tuft')
  assert.ok(plane && tufts && tufts.count === GROUND_RECIPES.grass.scatter[0].count)
  const placed = index => { const m = tufts.instanceMatrix.array.slice(index * 16, index * 16 + 16); return { x: m[12], z: m[14], scale: Math.hypot(m[4], m[5], m[6]) } }
  for (let i = 0; i < tufts.count; i++) {
    const { x, z, scale } = placed(i)
    if (Math.hypot(x, z) < 0.27) assert.ok(scale < 1e-6, 'no tuft grows where a cast member stands')
  }
  const before = placed(0)
  ground.sync('grass', 2, { speed: 1.5, direction: [-1, 0] }, 1, [])
  const after = placed(0)
  const wrapped = Math.abs(after.x - (before.x - 3)) < 1e-6 || Math.abs(Math.abs(after.x - (before.x - 3)) - 22 * 1.4 * 2) < 1e-6
  assert.ok(wrapped && Math.abs(after.z - before.z) < 1e-6, 'a piece travels 3 m with the ground in 2 s, wrapping round the square')
  assert.ok(Math.abs(plane.material.map.offset.x - 3 / GROUND_RECIPES.grass.period) < 1e-9, 'the picture travels with it')
  assert.equal(ground.sync(undefined, 0), false)
  assert.equal(ground.root.visible, false)
  ground.dispose()
})

function picture(width, height, paint) {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const [r, g, b] = paint(x, y), i = (y * width + x) * 4
    data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255
  }
  return data
}

test('settling brings the floor up to the pieces standing just above it, and leaves openings, slivers and posts alone', () => {
  const key = { color: '#ff00ff', tolerance: 0.2, softness: 0.12 }
  const width = 200, height = 100, MAGENTA = [255, 0, 255], HOUSE = [200, 180, 140], HALO = [230, 120, 220], RIM = [200, 150, 175]
  // Floor line at row 80 (floor 0.2). A house in columns 10-49 down to row 71 (a key halo under it, a pinkish rim at its
  // foot); an empty 8-column gap; a second house in 58-89 down to row 73; a one-column sliver at 100; an arch at
  // 120-169 (legs down to row 72, a lintel ending at row 49); a post at 180-182 reaching past the floor line; a speck high
  // in column 195; the rest key.
  const paint = (x, y) => {
    if (x >= 10 && x <= 49 && y >= 69 && y <= 71) return RIM
    if (x >= 10 && x <= 49 && y >= 30 && y <= 71) return HOUSE
    if (x >= 10 && x <= 49 && y === 72) return HALO
    if (x >= 58 && x <= 89 && y >= 40 && y <= 73) return HOUSE
    if (x === 100 && y >= 50 && y <= 72) return HOUSE
    if (((x >= 120 && x <= 129) || (x >= 160 && x <= 169)) && y >= 40 && y <= 72) return HOUSE
    if (x >= 130 && x <= 159 && y >= 40 && y <= 49) return HOUSE
    if (x >= 180 && x <= 182 && y >= 30 && y <= 85) return HOUSE
    if (x === 195 && y >= 8 && y <= 9) return HOUSE
    return MAGENTA
  }
  const data = picture(width, height, paint)
  settleColumns(data, width, height, key, { floor: 0.2, color: '#40a040' })
  const at = (x, y) => Array.from(data.slice((y * width + x) * 4, (y * width + x) * 4 + 4))
  const keyed = (x, y) => assert.deepEqual(at(x, y), [...MAGENTA, 255], `(${x}, ${y}) stays key`)
  assert.ok(at(30, 72).slice(0, 3).every((channel, c) => Math.abs(channel - HOUSE[c]) <= 25), 'the band starts in the piece\'s colour (the halo is not paint)')
  assert.deepEqual(at(30, 80), [64, 160, 64, 255], 'at the floor line it is the floor\'s colour')
  assert.ok(at(30, 76)[1] < 150, 'and darker above it, in the piece\'s shadow')
  assert.equal(at(30, 99)[3], 255, 'opaque to the bottom, under the floor')
  assert.deepEqual(at(30, 70), [175, 150, 150, 255], 'the key colour is taken out of the piece\'s rim')
  assert.equal(at(53, 78)[3], 255, 'the empty gap between the houses is bridged')
  assert.notDeepEqual(at(53, 78), [...MAGENTA, 255])
  keyed(145, 70)                                       // the arch's opening keeps its sky
  keyed(100, 78); assert.deepEqual(at(100, 60), [...HOUSE, 255], 'a sliver is not a piece')
  keyed(181, 90)                                       // the post already reaches the floor
  keyed(195, 50)
  assert.notDeepEqual(at(92, 79), [...MAGENTA, 255], 'a band ends in a bank sloping down to the floor line')
  keyed(92, 75)
  const grained = picture(width, height, paint)
  settleColumns(grained, width, height, key, { floor: 0.2, ground: 'grass' })
  const band = Array.from({ length: 40 }, (_, x) => grained[((90) * width + 10 + x) * 4 + 1])
  assert.ok(Math.max(...band) - Math.min(...band) > 6, 'with a ground style the band carries its grain')
})

test('parallax layers settle to the floor line under their painted feet, and a styled ground replaces the slab', () => {
  const set = { layers: [{ source: '/mid.png', depth: 'mid', foot: 0.1 }, { source: '/near.png', depth: 'near', foot: 0.2 }],
    ground: { source: '/ground.glb', height: 0.2, size: 80 }, key: '#ff00ff' }
  const doc = applyScene3DTemplate('cine-two-shot')
  const plain = stageParallaxSet(doc, set)
  assert.ok(plain.some(slot => slot.id === 'set-ground'))
  const mid = plain.find(slot => slot.id === 'set-layer-mid')
  assert.deepEqual(mid.imageLook.settle, { floor: 0.15 }, 'the floor line is the painted foot plus the sink')
  assert.deepEqual(parseImageLook(mid.imageLook).settle, { floor: 0.15 }, 'parsing keeps it')
  const styled = stageParallaxSet(doc, set, { groundStyle: 'grass' })
  assert.ok(!styled.some(slot => slot.id === 'set-ground'), 'the style is the floor: no slab')
  const settle = styled.find(slot => slot.id === 'set-layer-mid').imageLook.settle
  assert.deepEqual(settle, { floor: 0.15, color: groundColor('grass'), ground: 'grass' }, 'the layers settle onto the style\'s colour and grain')
  assert.deepEqual(parseImageLook({ settle }).settle, settle)
})

test('a shot asks for a ground style by floor or by its set\'s ground; a scrolled one slides it to the camera\'s left', () => {
  const subject = '/api/v1/file/hero.glb?workspace=movie'
  const background = { source: '/api/v1/uploads/far.png', key: '#00ff00', layers: [{ source: '/api/v1/uploads/mid.png', depth: 'mid', foot: 0.25 }],
    ground: { source: '/api/v1/file/ground.glb?workspace=t', height: 0.2, size: 80 } }
  const grass = compile({ template: 'cine-two-shot', subject, floor: 'grass' })
  assert.equal(grass.environment.floorStyle, 'grass')
  assert.equal(grass.environment.reflectiveFloor, false)
  const onSet = compile({ template: 'tracking', subject, background, floor: 'meadow', scroll: 2 })
  assert.equal(onSet.environment.floorStyle, 'meadow')
  assert.ok(!onSet.slots.some(slot => slot.id === 'set-ground'), 'the set\'s slab gives way to the style')
  assert.equal(onSet.environment.groundScroll.speed, 2)
  assert.ok(Math.abs(Math.hypot(...onSet.environment.groundScroll.direction) - 1) < 1e-9)
  const named = compile({ template: 'cine-two-shot', subject, background: { ...background, ground: { style: 'sand' } } })
  assert.equal(named.environment.floorStyle, 'sand', 'a set whose ground is a style draws it')
  const slab = compile({ template: 'cine-two-shot', subject, background })
  assert.notEqual(slab.environment.floorStyle, 'grass')
  assert.ok(slab.slots.some(slot => slot.id === 'set-ground'), 'without a style the set keeps its slab')
})
