import assert from 'node:assert/strict'
import test from 'node:test'
import { AdditiveBlending, BoxGeometry, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, NormalBlending } from 'three'
import { applyGlowBlending } from '../src/features/scene3d/gpu.ts'

test('a material the clean-up marked as a glow on black adds its light; the others keep painting', () => {
  const root = new Group()
  const glow = new MeshBasicMaterial(); glow.userData.hocusBlend = 'additive'
  const paint = new MeshStandardMaterial()
  const both = new Mesh(new BoxGeometry(), [paint, glow])
  root.add(new Mesh(new BoxGeometry(), glow), new Mesh(new BoxGeometry(), paint), both)
  applyGlowBlending(root)
  assert.equal(glow.blending, AdditiveBlending)
  assert.equal(glow.transparent, true)
  assert.equal(glow.depthWrite, false)
  assert.equal(paint.blending, NormalBlending)
  assert.equal(paint.transparent, false)
  for (const material of [glow, paint]) material.dispose()
})
