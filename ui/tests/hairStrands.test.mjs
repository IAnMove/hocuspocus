import test from 'node:test'
import assert from 'node:assert/strict'
import { BufferAttribute, BufferGeometry, Mesh, MeshStandardMaterial, Group, DoubleSide } from 'three'
import { applyHairStrands, hairStrandPixels, hairStrandTexture, STRAND_HEIGHT, STRAND_WIDTH } from '../src/features/scene3d/hairStrands.ts'

function model(withUv) {
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(9), 3))
  if (withUv) geometry.setAttribute('uv', new BufferAttribute(new Float32Array(6), 2))
  const hair = new MeshStandardMaterial({ name: 'hair' })
  const body = new MeshStandardMaterial({ name: 'body' })
  const group = new Group()
  group.add(new Mesh(geometry, [body, hair]))
  return { group, hair, body }
}

test('the strand pixels are deterministic: opaque at the root, a pointed frayed tip, light and dark strands', () => {
  const a = hairStrandPixels(), b = hairStrandPixels()
  assert.deepEqual(Array.from(a.slice(0, 4096)), Array.from(b.slice(0, 4096)))
  const alpha = (x, y) => a[(y * STRAND_WIDTH + x) * 4 + 3]
  for (let x = 0; x < STRAND_WIDTH; x++) assert.equal(alpha(x, 0), 255, 'every column is opaque at the root')
  assert.equal(alpha(0, STRAND_HEIGHT - 2), 0, 'the tip has narrowed away from the edges')
  const covered = row => { let n = 0; for (let x = 0; x < STRAND_WIDTH; x++) if (alpha(x, row)) n++; return n }
  assert.ok(covered(STRAND_HEIGHT - 20) < covered(40) / 2, 'a lock thins toward its tip')
  const greys = new Set(); for (let x = 0; x < STRAND_WIDTH; x++) greys.add(a[(40 * STRAND_WIDTH + x) * 4])
  assert.ok(greys.size > 6, 'strands differ in tone')
})

test('only the hair material of a mesh with texture coordinates gets the strand map, cut out and two-sided', () => {
  const { group, hair, body } = model(true)
  applyHairStrands(group)
  assert.equal(hair.map, hairStrandTexture())
  assert.equal(hair.alphaTest, 0.5)
  assert.equal(hair.side, DoubleSide)
  assert.equal(body.map, null)
  const old = model(false)
  applyHairStrands(old.group)
  assert.equal(old.hair.map, null, 'hair written before the cards keeps its plain colour')
})
