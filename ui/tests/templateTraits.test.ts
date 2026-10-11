import assert from 'node:assert/strict'
import test from 'node:test'
import { applyScene3DTemplate, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import {
  TEMPLATE_CAMERA_MOVES,
  TEMPLATE_MOVING_PARTS,
  TEMPLATE_SHOT_SIZES,
  TEMPLATE_USES,
  templateTraits,
  templateTraitWords,
} from '../src/features/scene3d/templateTraits.ts'
import { filterScene3DTemplates, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'

const traitsOf = (id: (typeof SCENE3D_TEMPLATE_IDS)[number]) => templateTraits(applyScene3DTemplate(id), { category: TEMPLATE_CATEGORIES[id] })

test('every shipped shot gets consistent traits', () => {
  for (const id of SCENE3D_TEMPLATE_IDS) {
    const traits = traitsOf(id)
    assert.ok(TEMPLATE_SHOT_SIZES.includes(traits.shot), id)
    assert.ok(traits.moves.every(move => TEMPLATE_CAMERA_MOVES.includes(move)), id)
    assert.ok(traits.moving.every(part => TEMPLATE_MOVING_PARTS.includes(part)), id)
    assert.ok(traits.uses.length > 0 && traits.uses.every(use => TEMPLATE_USES.includes(use)), id)
    assert.equal(traits.still, traits.moving.length === 0, id)
    assert.equal(traits.moving.includes('camera'), traits.moves.length > 0, id)
    assert.equal(traits.shot === 'plate', traits.distance === null, id)
  }
})

test('the camera, the cast and the use read as authored', () => {
  const close = traitsOf('face-closeup')
  assert.equal(close.shot, 'close')
  assert.ok(close.moves.includes('push') && close.uses.includes('reaction') && close.uses.includes('talk'))
  const dolly = traitsOf('cine-dolly-zoom')
  assert.deepEqual(dolly.moves, ['push', 'zoom'])
  const orbit = traitsOf('dance-orbit')
  assert.deepEqual(orbit.moves, ['orbit'])
  assert.ok(orbit.moving.includes('backdrop') && orbit.uses.includes('music'))
  const duet = traitsOf('speech-dialogue')
  assert.equal(duet.subjects, 2)
  assert.equal(duet.still, true)
  assert.ok(duet.uses.includes('dialogue'))
  const impact = traitsOf('anime-impact-frame')
  assert.equal(impact.authoredFor, 'cutout')
  assert.ok(impact.moves.includes('shake') && impact.moving.includes('effects') && impact.uses.includes('action'))
  assert.equal(impact.floor, 'none')
  const lake = traitsOf('pixel-moon-lake')
  assert.equal(lake.shot, 'plate')
  assert.ok(lake.uses.includes('plate') && lake.moving.includes('backdrop'))
  assert.ok(traitsOf('crane-reveal').uses.includes('reveal'))
  assert.equal(traitsOf('establishing').shot, 'far')
  assert.ok(traitsOf('product-pair').uses.includes('product') && !traitsOf('product-pair').uses.includes('dialogue'))
  assert.deepEqual(templateTraitWords(duet).slice(0, 1), ['medium'])
  assert.ok(templateTraitWords(duet).includes('still') && templateTraitWords(close).includes('animated'))
})

test('the editor search finds shots by their traits', () => {
  const titleOf = (id: string) => id
  const found = filterScene3DTemplates({ category: 'all', setting: 'all', query: 'dialogue', locale: 'en', titleOf })
  assert.ok(found.some(item => item.id === 'speech-dialogue'))
  assert.ok(found.every(item => templateTraitsOf(item.id).uses.includes('dialogue') || `${item.id}`.includes('dialogue')))
  assert.equal(templateTraitsOf('dance-orbit'), templateTraitsOf('dance-orbit'))
})
