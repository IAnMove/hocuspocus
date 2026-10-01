import assert from 'node:assert/strict'
import test from 'node:test'
import { framingFov } from '../src/features/scene3d/framing.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { TECHNIQUE_TEMPLATE_IDS } from '../src/features/scene3d/techniqueTemplateIds.ts'

test('each scraped cinematic technique is its own Video 3D shot', () => {
  assert.equal(TECHNIQUE_TEMPLATE_IDS.length, 424)
  assert.equal(new Set(TECHNIQUE_TEMPLATE_IDS).size, 424)
  for (const id of TECHNIQUE_TEMPLATE_IDS) assert.equal(id.startsWith('cine-'), true)

  const zoom = applyScene3DTemplate('cine-slow-zoom-in')
  const opened = framingFov(zoom.camera.framing, zoom.camera.fov, 0, zoom.duration)
  const closed = framingFov(zoom.camera.framing, zoom.camera.fov, zoom.duration, zoom.duration)
  assert.ok(closed < opened, 'slow zoom tightens the lens')

  const dolly = applyScene3DTemplate('cine-dolly-zoom')
  assert.ok((dolly.camera.framing?.to[2] ?? 9) < (dolly.camera.framing?.from[2] ?? 0))
  assert.ok((dolly.camera.framing?.fovTo ?? 0) > (dolly.camera.framing?.fovFrom ?? 99))

  const bird = applyScene3DTemplate('cine-birds-eye')
  assert.ok((bird.camera.framing?.from[1] ?? 0) > 6)

  const rain = applyScene3DTemplate('cine-rain')
  assert.equal(rain.dressing, 'chase-street')
  assert.equal(rain.worldSfx?.[0]?.kind, 'rain')

  const portrait = applyScene3DTemplate('cine-ratio-switch')
  assert.equal(portrait.width, 720)
  assert.equal(portrait.height, 1280)
  assert.equal(portrait.camera.frameFormat, 'portrait')

  const empty = applyScene3DTemplate('cine-void')
  assert.equal(empty.dressing, 'none')
})
