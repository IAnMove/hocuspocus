import assert from 'node:assert/strict'
import test from 'node:test'
import { assessNarrativeAsset } from '../src/lib/assetSuitability.ts'

test('opaque character previews warn that their baked world cannot be isolated', () => {
  const result = assessNarrativeAsset('hero', 'image', 'field-runner.preview.jpg')
  assert.equal(result.level, 'warning')
  assert.match(result.message, /baked background/i)
})

test('loopable plates and GLB heroes get role-specific guidance', () => {
  assert.equal(assessNarrativeAsset('plate', 'image', 'city-panorama-loop.png').level, 'ok')
  assert.match(assessNarrativeAsset('hero', 'model3d', 'hero.glb').message, /verified rig/i)
})
