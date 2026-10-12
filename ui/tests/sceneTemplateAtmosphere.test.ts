import assert from 'node:assert/strict'
import test from 'node:test'
import { ALL_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile'
import { candidateDemoBindings } from '../src/features/sceneTemplates/demoScenes'
import { ATMOSPHERE_OPACITY, ATMOSPHERE_PRESETS } from '../src/lib/scene2d/layerStyle'

const effects = (id: string, intensity = .5) =>
  compileCandidateScene(id, candidateDemoBindings(id, 'coral'), { intensity }).layers.filter(layer => layer.type === 'effect' && layer.atmosphere)

test('a card draws its particles from the editor preset of their kind, so they read over a real plate', () => {
  const cards = ALL_SCENE_TEMPLATES.filter(template => effects(template.id).length)
  assert.ok(cards.length >= 15, 'most cards carry an atmosphere')
  for (const { id } of cards) {
    for (const layer of effects(id)) {
      const kind = layer.atmosphere!.kind!
      const preset = ATMOSPHERE_PRESETS[kind]
      assert.equal(layer.atmosphere!.density, preset.density, `${id} ${kind}: density at medium intensity`)
      assert.ok(Math.abs(layer.atmosphere!.size! - preset.size) < 1e-9, `${id} ${kind}: size at medium intensity`)
      if (layer.id.startsWith('atmosphere-')) {
        assert.equal(layer.transform.opacity, ATMOSPHERE_OPACITY[kind], `${id} ${kind}: the kind's own opacity`)
      }
    }
  }
})

test('intensity scales the preset: fewer particles when quiet, more when loud', () => {
  const [quiet] = effects('music-shockwave', 0)
  const [loud] = effects('music-shockwave', 1)
  assert.ok(quiet.atmosphere!.density! < loud.atmosphere!.density!)
  assert.ok(quiet.atmosphere!.density! >= 5 && quiet.atmosphere!.size! > .5, 'never the 12 specks of size .4 that vanished')
})
