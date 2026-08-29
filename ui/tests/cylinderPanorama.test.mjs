import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createCylinderPanoramaShaders,
  projectCylinderPanorama,
  shouldUseParallaxFallback,
} from '../src/lib/cylinderPanorama.ts'

test('centre ray maps to centre and horizontal rotation changes longitude', () => {
  const centre = projectCylinderPanorama(0, 0, { radius: 10, verticalFov: 60, aspect: 16 / 9 })
  const turned = projectCylinderPanorama(0, 0, { radius: 10, verticalFov: 60, horizontalRotation: 90, aspect: 16 / 9 })
  assert.equal(centre.u, .5)
  assert.equal(centre.v, .5)
  assert.ok(Math.abs(turned.u - .75) < 1e-12)
  assert.equal(turned.v, .5)
})

test('vertical FOV affects projection and UVs remain bounded', () => {
  const narrow = projectCylinderPanorama(0, 1, { radius: 2, verticalFov: 30, aspect: 1 })
  const wide = projectCylinderPanorama(0, 1, { radius: 2, verticalFov: 120, aspect: 1 })
  assert.ok(narrow.v > wide.v)
  for (const projection of [narrow, wide]) {
    assert.ok(projection.u >= 0 && projection.u < 1)
    assert.ok(projection.v >= 0 && projection.v <= 1)
  }
})

test('shader contract exposes rotation, FOV and panorama uniforms', () => {
  const shaders = createCylinderPanoramaShaders()
  assert.match(shaders.vertex, /aPosition/)
  assert.match(shaders.fragment, /uHorizontalRotation/)
  assert.match(shaders.fragment, /uVerticalFov/)
  assert.match(shaders.fragment, /uAspect/)
  assert.match(shaders.fragment, /uPanorama/)
})

test('parallax fallback starts after meaningful camera translation', () => {
  assert.equal(shouldUseParallaxFallback(1, 10), false)
  assert.equal(shouldUseParallaxFallback(1.51, 10), true)
})
