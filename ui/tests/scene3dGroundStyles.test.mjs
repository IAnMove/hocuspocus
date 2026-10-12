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

test('settling carries each piece down to the floor line and shades it to the floor colour', () => {
  const key = { color: '#ff00ff', tolerance: 0.2, softness: 0.12 }
  const width = 40, height = 100, MAGENTA = [255, 0, 255], HOUSE = [200, 180, 140], HALO = [230, 120, 220]
  // A house in columns 5-24 ending at row 59 with a key halo row under it; a post in columns 30-32 down to row 85;
  // a lone speck high in column 36; the rest key.
  const data = picture(width, height, (x, y) => {
    if (x >= 5 && x <= 24 && y >= 20 && y <= 59) return HOUSE
    if (x >= 5 && x <= 24 && y === 60) return HALO
    if (x >= 30 && x <= 32 && y >= 30 && y <= 85) return HOUSE
    if (x === 36 && y >= 8 && y <= 9) return HOUSE
    return MAGENTA
  })
  const settled = settleColumns(data, width, height, key, { floor: 0.2, color: '#40a040' })
  const at = (x, y) => Array.from(data.slice((y * width + x) * 4, (y * width + x) * 4 + 4))
  assert.equal(settled, 20, 'the house columns settle; the post already reaches below the floor line, the speck is not a piece')
  assert.ok(at(10, 60).slice(0, 3).every((channel, c) => Math.abs(channel - HOUSE[c]) <= 3), 'the band starts in the house\'s own colour (the halo is not paint)')
  assert.deepEqual(at(10, 80), [64, 160, 64, 255], 'at the floor line (row 80) it is the floor\'s colour')
  assert.equal(at(10, 99)[3], 255, 'and stays opaque to the bottom, under the floor')
  assert.deepEqual(at(36, 50), [...MAGENTA, 255], 'a column with only a high speck stays key')
  assert.deepEqual(at(31, 90), [...MAGENTA, 255], 'a piece already past the floor line is left alone')
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
  const styled = stageParallaxSet(doc, set, { styledGround: true, groundColor: '#4a802c' })
  assert.ok(!styled.some(slot => slot.id === 'set-ground'), 'the style is the floor: no slab')
  assert.equal(styled.find(slot => slot.id === 'set-layer-mid').imageLook.settle.color, '#4a802c')
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
