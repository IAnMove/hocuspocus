import assert from 'node:assert/strict'
import test from 'node:test'
import catalogJson from '../../app/shared/scene_templates.json' with { type: 'json' }
import {
  ALL_SCENE_TEMPLATES,
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
  COMPOSER_SCENE_TEMPLATES,
  MUSIC_MOTION_TEMPLATES,
  RETIRED_SCENE_TEMPLATES,
  SCENE_TEMPLATE_ALIASES,
  VIDEO2D_SCENE_TEMPLATES,
  canonicalBindings,
  getCandidateSceneTemplate,
  parseSceneTemplateEntry,
  requiredSlots,
  resolveSceneTemplate,
} from '../src/features/sceneTemplates/catalog.ts'
import { NARRATIVE_SCENE_TEMPLATES } from '../src/lib/sceneNarrative.ts'

const ORIGINAL_IDS = [
  'cinema-establishing', 'cinema-reveal', 'cinema-closeup', 'cinema-two-shot', 'cinema-detail', 'cinema-hero', 'cinema-tracking',
  'music-pulse', 'music-duet', 'music-orbit', 'music-product',
  'space-cruise', 'space-orbit', 'space-docking', 'space-chase', 'space-broadside', 'space-warp',
]
// The contract table (docs/development/VIDEO2D_TEMPLATE_MODEL.md, «Merges»).
const MERGES = {
  'cinema-isolation': ['cinema-establishing', { mood: 'lonely' }],
  'music-parallax': ['cinema-tracking', { atmosphere: 'streaks' }],
  'music-stage': ['music-pulse', { camera: 'sweep' }],
  'music-finale': ['music-pulse', { camera: 'open', atmosphere: 'confetti' }],
  'music-chorus': ['music-pulse', { camera: 'beat', atmosphere: 'confetti' }],
  'music-satellite-swarm': ['music-orbit', { bounce: 'off' }],
  'music-ricochet-pass': ['music-pinball', { bouncer: 'prop' }],
  'space-shield': ['space-broadside', { outcome: 'shield' }],
  'space-explosion': ['space-broadside', { outcome: 'explode' }],
}
const SLOT_NAMES = new Set(['subject_1', 'subject_2', 'background', 'prop_1', 'prop_2', 'foreground'])
const slot = (template, id) => template.slots.find(candidate => candidate.id === id)
const codeOf = fn => { try { fn() } catch (error) { return error.code } return undefined }

test('the catalog holds the 41 cards: 17 originals, 2 titled cards and 22 choreographies', () => {
  assert.equal(CATALOG_VERSION, '2026-09-review-1')
  assert.equal(ALL_SCENE_TEMPLATES.length, 41)
  assert.equal(new Set(ALL_SCENE_TEMPLATES.map(template => template.id)).size, 41)
  assert.deepEqual(CANDIDATE_SCENE_TEMPLATES.map(template => template.id), ORIGINAL_IDS)
  assert.deepEqual(VIDEO2D_SCENE_TEMPLATES.map(template => template.id), ['documentary-history', 'city-postcard'])
  assert.equal(MUSIC_MOTION_TEMPLATES.length, 22)
  assert.deepEqual(ALL_SCENE_TEMPLATES.map(template => template.id), catalogJson.entries.map(entry => entry.id))
  for (const template of ALL_SCENE_TEMPLATES) {
    assert.equal(template.version, 1)
    assert.equal(template.status, 'candidate', `${template.id} waits for its render review`)
    assert.equal(getCandidateSceneTemplate(template.id), template)
    assert.match(template.promptExample, new RegExp(template.id.replaceAll('-', '\\-')))
    assert.ok(template.title && template.description && template.limits.length >= 5, template.id)
  }
  assert.throws(() => getCandidateSceneTemplate('approved-or-unknown'), /Unknown candidate scene template: approved-or-unknown/)
})

test('every alias compiles as its card with the contract preset, and is not listed', () => {
  assert.deepEqual(Object.keys(SCENE_TEMPLATE_ALIASES).sort(), Object.keys(MERGES).sort())
  for (const [alias, [card, preset]] of Object.entries(MERGES)) {
    assert.deepEqual(SCENE_TEMPLATE_ALIASES[alias], { card, preset })
    const resolved = resolveSceneTemplate(alias)
    assert.equal(resolved.template.id, card)
    assert.equal(resolved.alias, alias)
    assert.deepEqual(resolved.preset, preset)
    assert.equal(ALL_SCENE_TEMPLATES.some(template => template.id === alias), false)
    assert.throws(() => getCandidateSceneTemplate(alias), /Unknown candidate scene template/)
    for (const [key, value] of Object.entries(preset)) {
      const spec = resolved.template.controls[key]
      assert.equal(spec.kind, 'choice', `${alias}/${key}`)
      assert.ok(spec.options.includes(value) && spec.default !== value, `${alias}/${key} differs from the card default`)
    }
  }
  assert.deepEqual(resolveSceneTemplate('music-pulse'), { template: getCandidateSceneTemplate('music-pulse'), preset: {} })
})

test('retired ids fail with template_retired and say what to use instead', () => {
  assert.deepEqual(Object.keys(RETIRED_SCENE_TEMPLATES).sort(), ['lyric-vertical', 'trailer-teaser'])
  for (const id of ['trailer-teaser', 'lyric-vertical']) {
    try {
      resolveSceneTemplate(id)
      assert.fail(`${id} must be retired`)
    } catch (error) {
      assert.equal(error.code, 'template_retired')
      assert.deepEqual(error.details.use_instead, RETIRED_SCENE_TEMPLATES[id].useInstead)
      assert.match(error.message, new RegExp(id))
    }
  }
  assert.deepEqual(RETIRED_SCENE_TEMPLATES['trailer-teaser'].useInstead, ['title-card', 'trailer-slam'])
  assert.deepEqual(RETIRED_SCENE_TEMPLATES['lyric-vertical'].useInstead, ['scenes.lyrics.import'])
  assert.equal(codeOf(() => resolveSceneTemplate('nope')), 'template_unknown')
})

test('one slot vocabulary: cards use only the new names and backgrounds take a picture or a loop', () => {
  for (const template of ALL_SCENE_TEMPLATES) {
    for (const item of template.slots) assert.ok(SLOT_NAMES.has(item.id), `${template.id}/${item.id}`)
    assert.ok(slot(template, 'subject_1')?.required, `${template.id} has subject_1`)
    const background = slot(template, 'background')
    assert.ok(background?.required, `${template.id} has a background`)
    const imageOnly = template.group === 'video2d'
    assert.deepEqual(background.kinds, imageOnly ? ['image'] : ['image', 'video'], `${template.id}/background kinds`)
    if (imageOnly) for (const item of template.slots) assert.deepEqual(item.kinds, ['image'], `${template.id}/${item.id} is image-only`)
    if (template.family === 'space') assert.deepEqual(slot(template, 'subject_1').kinds, ['image', 'model3d'], `${template.id} ship takes a picture or a GLB`)
  }
  assert.deepEqual(['cinema-two-shot', 'music-duet'].map(id => slot(getCandidateSceneTemplate(id), 'subject_2')?.required), [true, true])
  for (const id of ['space-orbit', 'space-docking', 'space-chase', 'space-broadside']) assert.deepEqual(slot(getCandidateSceneTemplate(id), 'prop_1').kinds, ['image', 'model3d'])
  assert.deepEqual(slot(getCandidateSceneTemplate('music-orbit'), 'prop_1').kinds, ['image', 'model3d'])
})

test('old slot names translate once, by card, and two names for one slot conflict', () => {
  const twoShot = getCandidateSceneTemplate('cinema-two-shot')
  const orbit = getCandidateSceneTemplate('space-orbit')
  const establishing = getCandidateSceneTemplate('cinema-establishing')
  assert.deepEqual(canonicalBindings(twoShot, { hero: 1, plate: 2, prop: 3, foreground: 4 }), { subject_1: 1, background: 2, subject_2: 3, foreground: 4 })
  assert.deepEqual(canonicalBindings(getCandidateSceneTemplate('music-duet'), { prop: 'p' }), { subject_2: 'p' })
  assert.deepEqual(canonicalBindings(orbit, { hero: 'ship', prop: 'planet' }), { subject_1: 'ship', prop_1: 'planet' })
  assert.deepEqual(canonicalBindings(getCandidateSceneTemplate('music-spiral-exit'), { hero: 'a', plate: 'b' }), { subject_1: 'a', background: 'b' })
  assert.equal(codeOf(() => canonicalBindings(establishing, { hero: 'a', subject_1: 'b' })), 'slot_alias_conflict')
  assert.equal(codeOf(() => canonicalBindings(orbit, { prop: 'a', prop_1: 'b' })), 'slot_alias_conflict')
  assert.equal(codeOf(() => canonicalBindings(establishing, { prop: 'a' })), 'template_bad_asset', 'no prop_1 on this card')
  assert.equal(codeOf(() => canonicalBindings(establishing, { unknown: 'a' })), 'template_bad_asset')
})

test('controls are numbers, choices or texts, and exposed flags replace the hand-written pulse list', () => {
  const kinds = new Set()
  for (const template of ALL_SCENE_TEMPLATES) {
    assert.deepEqual(Object.keys(template.controls).slice(0, 3), ['duration', 'bpm', 'intensity'], template.id)
    assert.equal(template.controls.duration.default, template.defaultDuration, template.id)
    for (const spec of Object.values(template.controls)) kinds.add(spec.kind)
    assert.equal('drift' in template.controls, template.id.startsWith('music-'), `${template.id} drift belongs to the music cards`)
    if (template.controls.drift) assert.deepEqual(template.controls.drift, { kind: 'number', min: 0, max: 1, default: .5, exposed: true })
  }
  assert.deepEqual([...kinds].sort(), ['choice', 'number', 'text'])
  const rhythmic = ALL_SCENE_TEMPLATES.filter(template => template.controls.bpm.exposed).map(template => template.id)
  assert.deepEqual(rhythmic, ['music-pulse', 'music-duet', 'music-orbit'])
  assert.deepEqual(getCandidateSceneTemplate('music-pulse').controls.camera, { kind: 'choice', options: ['push', 'sweep', 'open', 'beat'], default: 'push', exposed: true })
  assert.deepEqual(getCandidateSceneTemplate('documentary-history').controls.caption, { kind: 'text', maxLength: 80, default: 'The harbour keeps the light', exposed: true })
  assert.equal(getCandidateSceneTemplate('documentary-history').defaultDuration, 6)
  assert.equal(getCandidateSceneTemplate('city-postcard').defaultDuration, 6)
})

test('a slot can be required by a choice: pinball needs prop_1 only when the prop bounces', () => {
  const pinball = getCandidateSceneTemplate('music-pinball')
  assert.deepEqual(requiredSlots(pinball, { bouncer: 'subject' }).map(item => item.id), ['subject_1', 'background'])
  assert.deepEqual(requiredSlots(pinball, { bouncer: 'prop' }).map(item => item.id), ['subject_1', 'background', 'prop_1'])
})

test('cinema cards name their narrative twins and stay off the composer shelf', () => {
  const narrative = new Set(NARRATIVE_SCENE_TEMPLATES.map(template => template.id))
  for (const template of ALL_SCENE_TEMPLATES) {
    assert.equal(template.twins.length > 0, template.id.startsWith('cinema-'), template.id)
    for (const twin of template.twins) assert.ok(narrative.has(twin), `${template.id} twin ${twin}`)
  }
  const shelf = COMPOSER_SCENE_TEMPLATES.map(template => template.id)
  assert.equal(shelf.some(id => id.startsWith('cinema-')), false)
  assert.ok(shelf.includes('documentary-history') && shelf.includes('city-postcard'))
  assert.equal(shelf.length, 34)
})

test('the loader accepts candidate and approved and rejects any other status', () => {
  const entry = structuredClone(catalogJson.entries[0])
  assert.equal(parseSceneTemplateEntry({ ...entry, reviewStatus: 'approved' }).status, 'approved')
  assert.equal(parseSceneTemplateEntry(entry).status, 'candidate')
  assert.throws(() => parseSceneTemplateEntry({ ...entry, reviewStatus: 'keep' }), /candidate or approved/)
  assert.throws(() => parseSceneTemplateEntry({ ...entry, controls: { ...entry.controls, mood: { options: ['a'], default: 'b' } } }), /invalid control mood/)
  assert.throws(() => parseSceneTemplateEntry({ ...entry, slots: [{ ...entry.slots[0], id: 'hero' }] }), /unknown slot/)
})
