import assert from 'node:assert/strict'
import test from 'node:test'
import { Mesh, Points, Scene, ShaderMaterial } from 'three'
import { ENERGY_NOISE } from '../src/features/sceneFx/energyShaders.ts'
import { WORLD_SFX_KINDS, parseWorldSfx } from '../src/features/sceneFx/world.ts'
import { syncWorldSfx } from '../src/features/sceneFx/worldRuntime.ts'

const HASH = /float hash\(vec2 p\) \{([\s\S]*?)\n\}/

/** The shader's lattice hash in 32-bit integer arithmetic, as the GPU runs it. */
function latticeHash(x, y) {
  const k = 1103515245
  const qx = Math.imul(k, ((x >>> 0) >>> 1) ^ (y >>> 0)) >>> 0
  const qy = Math.imul(k, ((y >>> 0) >>> 1) ^ (x >>> 0)) >>> 0
  return (Math.imul(k, qx ^ (qy >>> 3)) >>> 0 >>> 8) / 16777216
}

function correlation(pairs) {
  const n = pairs.length
  const [ma, mb] = [0, 1].map(side => pairs.reduce((sum, pair) => sum + pair[side], 0) / n)
  let ab = 0, aa = 0, bb = 0
  for (const [a, b] of pairs) { ab += (a - ma) * (b - mb); aa += (a - ma) ** 2; bb += (b - mb) ** 2 }
  return ab / Math.sqrt(aa * bb)
}

/** Every material of every world effect, as the stage builds them. */
function effectMaterials(kinds = WORLD_SFX_KINDS, scale = 1) {
  const scene = new Scene(), nodes = new Map()
  syncWorldSfx(scene, nodes, parseWorldSfx(kinds.map((kind, index) => ({ id: String(index), kind, start: 0, end: 4, scale }))), 1, [])
  scene.updateMatrixWorld(true)
  const objects = []
  scene.traverse(object => { if (object instanceof Mesh || object instanceof Points) objects.push(object) })
  return objects
}

test('effect noise hashes whole lattice cells with integers, so neighbouring cells agree on their shared corner', () => {
  const body = HASH.exec(ENERGY_NOISE)?.[1]
  assert.ok(body, 'ENERGY_NOISE defines hash(vec2)')
  assert.doesNotMatch(body, /sin\(/, 'a sine hash turns a last-bit difference into another value')
  assert.match(body, /highp uvec2 q = uvec2\(ivec2\(floor\(p\)\)\);/)
  assert.match(body, /q = 1103515245u \* \(\(q >> 1u\) \^ q\.yx\);/)
  assert.match(body, /highp uint n = 1103515245u \* \(q\.x \^ \(q\.y >> 3u\)\);/)
  assert.match(body, /return float\(n >> 8u\) \* \(1\. \/ 16777216\.\);/)
  // The JS twin above runs the same steps: the values spread evenly over [0, 1) with no pattern between neighbours.
  const values = [], right = [], up = []
  for (let y = -64; y < 64; y += 1) {
    for (let x = -64; x < 64; x += 1) {
      const value = latticeHash(x, y)
      values.push(value); right.push([value, latticeHash(x + 1, y)]); up.push([value, latticeHash(x, y + 1)])
    }
  }
  assert.ok(values.every(value => value >= 0 && value < 1))
  assert.ok(Math.abs(values.reduce((sum, value) => sum + value, 0) / values.length - .5) < .01)
  assert.ok(new Set(values).size > values.length * .99)
  assert.ok(Math.abs(correlation(right)) < .03 && Math.abs(correlation(up)) < .03)
})

test('no world effect shader carries its own sine hash', () => {
  for (const object of effectMaterials()) {
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials) {
      if (!(material instanceof ShaderMaterial)) continue
      assert.doesNotMatch(material.fragmentShader, /43758|sin\(dot\(/, `${material.name} hashes with a sine`)
    }
  }
})

/** gl_PointSize of a spark material for a point `depth` metres in front of the camera, evaluated from its source. */
function pointSize(points, depth) {
  const expression = /gl_PointSize=(.+?);/.exec(points.material.vertexShader)?.[1]
  assert.ok(expression, 'the spark shader sets gl_PointSize')
  const column = points.matrixWorld.elements.slice(0, 3)
  const glsl = new Function('uSize', 'modelMatrix', 'p', 'clamp', 'max', 'length', `return ${expression}`)
  return glsl(points.material.uniforms.uSize.value, [{ xyz: column }], { z: -depth },
    (value, low, high) => Math.min(high, Math.max(low, value)), Math.max, vector => Math.hypot(...vector))
}

test('rain, snow and spark points grow with the scale of their effect like its sheets', () => {
  const points = scale => effectMaterials(['rain', 'snow', 'sparks', 'fire'], scale).filter(object => object instanceof Points)
  const unit = points(1), large = points(6)
  assert.equal(unit.length, 4)
  // A drop 15 m away: under 5 px at scale 1, which leaves a streak a twelfth of that wide.
  assert.ok(Math.abs(pointSize(unit[0], 15) - .1 * 700 / 15) < 1e-9)
  for (const [index, point] of unit.entries()) {
    assert.ok(Math.abs(pointSize(large[index], 15) / pointSize(point, 15) - 6) < 1e-6, `${point.userData.kind}: six times the size`)
  }
  assert.equal(pointSize(large[0], 1), 30, 'a streak stays within its cap')
  assert.equal(pointSize(unit[1], 1000), 1, 'and never drops under a pixel')
})
