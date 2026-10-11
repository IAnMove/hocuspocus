import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import type { RoomMold } from '../src/features/scene3d/roomSet.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import {
  TEMPLATE_CAMERA_MOVES,
  TEMPLATE_KINDS,
  TEMPLATE_MOVING_PARTS,
  TEMPLATE_SHOT_SIZES,
  TEMPLATE_USES,
  templatePlace,
  templateTraits,
  templateTraitWords,
} from '../src/features/scene3d/templateTraits.ts'
import { filterScene3DTemplates, templatePlaceOf, templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'

/** The editor's own derivation: the built document plus the category and family hints the exporter also passes. */
const traitsOf = templateTraitsOf
const titleOf = (id: string) => id
const search = (query: string) => filterScene3DTemplates({ category: 'all', setting: 'all', query, locale: 'en', titleOf }).map(item => item.id)

test('every shipped shot gets consistent traits', () => {
  for (const id of SCENE3D_TEMPLATE_IDS) {
    const traits = traitsOf(id)
    const doc = applyScene3DTemplate(id)
    assert.ok(TEMPLATE_KINDS.includes(traits.kind), id)
    assert.ok(TEMPLATE_SHOT_SIZES.includes(traits.shot), id)
    assert.ok(traits.moves.every(move => TEMPLATE_CAMERA_MOVES.includes(move)), id)
    assert.ok(traits.moving.every(part => TEMPLATE_MOVING_PARTS.includes(part)), id)
    assert.ok(traits.uses.length > 0 && traits.uses.every(use => TEMPLATE_USES.includes(use)), id)
    assert.equal(traits.still, traits.moving.length === 0, id)
    assert.equal(traits.moving.includes('camera'), traits.moves.length > 0, id)
    assert.equal(traits.shot === 'plate', traits.distance === null, id)
    assert.equal(traits.travel, doc.slots.some(slot => (slot.slot === 'subject_1' || slot.slot === 'subject_2') && Boolean(slot.motion)), id)
    if (traits.travel) assert.ok(traits.moving.includes('subjects'), id)
    if (traits.uses.includes('impact')) assert.ok(traits.uses.includes('action'), id)
    if (traits.uses.includes('dialogue')) assert.ok(traits.subjects >= 2 && !traits.uses.includes('impact'), id)
    if (id.startsWith('cine-')) assert.ok(traits.kind === 'look' || traits.kind === 'camera', id)
    else assert.ok(traits.kind !== 'look' && traits.kind !== 'camera', id)
  }
})

test('the kind puts each card on its shelf', () => {
  assert.equal(traitsOf('cine-noir').kind, 'look')
  assert.equal(traitsOf('cine-rembrandt').kind, 'look')
  assert.equal(traitsOf('cine-dolly-in').kind, 'camera')
  assert.equal(traitsOf('cine-two-shot').kind, 'camera')
  assert.equal(traitsOf('anime-eyecatch').kind, 'transition')
  assert.equal(traitsOf('dance-orbit').kind, 'scene')
  assert.equal(traitsOf('atmos-reef-wide').kind, 'scene')
  assert.equal(traitsOf('stage-crane').kind, 'scene')
  // The pack ids and the built document decide for cards the families do not cover.
  const two = applyScene3DTemplate('two-shot')
  assert.equal(templateTraits({ ...two, templateId: 'transition-whip-pan' }).kind, 'transition')
  assert.equal(templateTraits({ ...two, templateId: 'title-lower-third' }).kind, 'title')
  const titled = applyScene3DTemplate('car-chase')
  assert.equal(templateTraits({ ...titled, slots: titled.slots.filter(slot => slot.slot === 'background') }).kind, 'title')
  const mold = { id: 'sala', size: 'm', dimensions: [6, 3, 5], walls: [], surfaces: [], openings: [], blocks: [], marks: [], propAnchors: [], cameras: [], defaultSkin: {}, lights: 'studio' } as RoomMold
  const staged = { ...two, room: { mold } }
  assert.equal(templateTraits(staged).kind, 'stage')
  assert.equal(templatePlace(staged), 'sala')
  assert.equal(templatePlace(two), null)
  assert.equal(templatePlace(applyScene3DTemplate('car-chase')), 'chase-street')
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

test('speed, impact, dialogue and reaction follow the director rules', () => {
  const chase = traitsOf('car-chase')
  assert.ok(chase.uses.includes('speed') && !chase.uses.includes('dialogue'), chase.uses.join())
  assert.ok(chase.travel && chase.moves.includes('track'), 'a framing on a running figure tracks it')
  const ship = traitsOf('ship-chase')
  assert.ok(ship.uses.includes('speed') && !ship.uses.includes('dialogue'), 'a chase camera is never a conversation')
  assert.ok(traitsOf('drive-hood').uses.includes('speed'))
  const talk = traitsOf('hangar-talk')
  assert.ok(talk.uses.includes('dialogue') && !talk.uses.includes('speed'), 'figures that stroll keep talking')
  assert.ok(traitsOf('jungle-ambush').uses.includes('dialogue'))
  const walk = traitsOf('cine-walk-and-talk')
  assert.ok(walk.travel && walk.uses.includes('dialogue') && !walk.uses.includes('speed'))
  assert.equal(traitsOf('speech-dialogue').travel, false)
  const impact = traitsOf('anime-impact-frame')
  assert.ok(impact.uses.includes('impact') && impact.uses.includes('action') && !impact.uses.includes('talk'))
  assert.ok(traitsOf('anime-sword-clash').uses.includes('impact') && !traitsOf('anime-sword-clash').uses.includes('dialogue'))
  const held = traitsOf('cine-close-up')
  assert.ok(held.shot === 'close' && held.moves.length === 0 && held.uses.includes('reaction'))
  const noir = traitsOf('cine-noir')
  assert.ok(noir.shot === 'close' && noir.uses.includes('look') && !noir.uses.includes('reaction'), 'a look is not a reaction')
  assert.ok(traitsOf('cine-reaction-shot').uses.includes('reaction'))
  assert.ok(templateTraitWords(walk).includes('travel') && templateTraitWords(walk).includes('camera'))
  assert.ok(templateTraitWords(noir).includes('look') && !templateTraitWords(noir).includes('travel'))
})

test('the editor search finds shots by their traits, kind and place', () => {
  const found = search('dialogue')
  assert.ok(found.includes('speech-dialogue'))
  assert.ok(found.every(id => traitsOf(id).uses.includes('dialogue') || id.includes('dialogue')))
  assert.ok(!found.includes('car-chase'))
  assert.ok(search('transition').includes('anime-eyecatch'))
  assert.ok(search('chase street').includes('car-chase'))
  assert.ok(search('citadel').includes('cine-dolly-in'))
  assert.equal(templatePlaceOf('car-chase'), 'chase-street')
  assert.equal(templatePlaceOf('two-shot'), null)
  assert.equal(templateTraitsOf('dance-orbit'), templateTraitsOf('dance-orbit'))
})

test('the shared catalog carries the derived card fields', () => {
  const catalog = JSON.parse(readFileSync(new URL('../../app/shared/world3d_templates.json', import.meta.url), 'utf8')).catalog as Record<string, unknown>[]
  assert.equal(catalog.length, SCENE3D_TEMPLATE_IDS.length)
  for (const card of catalog) {
    const id = card.id as (typeof SCENE3D_TEMPLATE_IDS)[number]
    const keys = Object.keys(card)
    assert.deepEqual(keys.slice(keys.indexOf('uses')), ['uses', 'kind', 'place', 'travel', 'reference', 'source'], id)
    assert.equal(card.preview, null, id)
    assert.equal(card.kind, traitsOf(id).kind, id)
    assert.equal(card.travel, traitsOf(id).travel, id)
    assert.deepEqual(card.uses, traitsOf(id).uses, id)
    assert.equal(card.place, templatePlaceOf(id), id)
    assert.equal(typeof card.reference === 'string' && card.reference.startsWith('https://'), id.startsWith('cine-'), id)
  }
})
