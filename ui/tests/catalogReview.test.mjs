import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ALL_SCENE_TEMPLATES,
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
  EXPANDED_CATALOG_VERSION,
} from '../src/features/sceneTemplates/catalog.ts'
import { CATALOG_REVIEW_STORAGE_KEY, loadCatalogReview, saveCatalogReview } from '../src/features/sceneTemplates/catalogReview.ts'
import {
  REVIEW_DECISIONS_STORAGE_KEY,
  serializeReviewChoices,
  serializeReviewExport,
} from '../src/features/sceneTemplates/reviewDecisions.ts'

const makeStorage = (raw = null) => ({
  getItem: key => key === REVIEW_DECISIONS_STORAGE_KEY ? raw : null,
})

const choice = (template, decision, notes = '') => ({
  id: template.id,
  templateVersion: template.version,
  decision,
  notes,
})

test('migrates valid legacy keep/discard/pending choices and keeps new IDs pending', () => {
  const legacyKeep = CANDIDATE_SCENE_TEMPLATES[0]
  const legacyDiscard = CANDIDATE_SCENE_TEMPLATES[1]
  const legacyPending = CANDIDATE_SCENE_TEMPLATES[2]
  const newTemplate = ALL_SCENE_TEMPLATES.find(template => !CANDIDATE_SCENE_TEMPLATES.includes(template))
  assert.ok(newTemplate)

  const raw = JSON.stringify({
    schemaVersion: 1,
    catalogVersion: CATALOG_VERSION,
    choices: {
      [legacyKeep.id]: choice(legacyKeep, 'keep', 'conservar'),
      [legacyDiscard.id]: choice(legacyDiscard, 'discard', 'descartar'),
      [legacyPending.id]: choice(legacyPending, 'pending', 'pendiente revisado'),
      [newTemplate.id]: choice(newTemplate, 'keep', 'no puede aprobarse desde legacy'),
      unknown: { id: 'unknown', templateVersion: 1, decision: 'keep', notes: 'falso' },
    },
  })

  const loaded = loadCatalogReview(makeStorage(raw))
  assert.equal(loaded.state.catalogVersion, EXPANDED_CATALOG_VERSION)
  assert.equal(loaded.state.choices[legacyKeep.id].decision, 'keep')
  assert.equal(loaded.state.choices[legacyDiscard.id].decision, 'discard')
  assert.equal(loaded.state.choices[legacyPending.id].decision, 'pending')
  assert.equal(loaded.state.choices[legacyPending.id].notes, 'pendiente revisado')
  assert.equal(loaded.state.choices[newTemplate.id].decision, 'pending')
  assert.equal(loaded.state.choices[newTemplate.id].notes, '')
  assert.equal(loaded.state.choices.unknown, undefined)
  assert.match(loaded.warning, /24 previous/)
  assert.match(loaded.warning, /24 new templates stay pending/)
})

test('does not preserve malformed legacy rows, even when another legacy row is valid', () => {
  const valid = CANDIDATE_SCENE_TEMPLATES[0]
  const stale = CANDIDATE_SCENE_TEMPLATES[1]
  const raw = JSON.stringify({
    schemaVersion: 1,
    catalogVersion: CATALOG_VERSION,
    choices: {
      [valid.id]: choice(valid, 'keep'),
      [stale.id]: { ...choice(stale, 'keep'), templateVersion: 999 },
    },
  })

  const loaded = loadCatalogReview(makeStorage(raw))
  assert.equal(loaded.state.choices[valid.id].decision, 'keep')
  assert.equal(loaded.state.choices[stale.id].decision, 'pending')
  assert.match(loaded.warning, /IDs or versions/)
  assert.match(loaded.warning, /new templates stay pending/)
})

test('invalid schema or catalog version fails closed with every expanded choice pending', () => {
  const rawInvalidSchema = JSON.stringify({
    schemaVersion: 999,
    catalogVersion: CATALOG_VERSION,
    choices: { [CANDIDATE_SCENE_TEMPLATES[0].id]: choice(CANDIDATE_SCENE_TEMPLATES[0], 'keep') },
  })
  const invalidSchema = loadCatalogReview(makeStorage(rawInvalidSchema))
  assert.match(invalidSchema.warning, /another catalog version/)
  assert.equal(Object.values(invalidSchema.state.choices).every(item => item.decision === 'pending'), true)

  const rawOtherVersion = JSON.stringify({
    schemaVersion: 1,
    catalogVersion: 'future-catalog',
    choices: { [CANDIDATE_SCENE_TEMPLATES[0].id]: choice(CANDIDATE_SCENE_TEMPLATES[0], 'keep') },
  })
  const otherVersion = loadCatalogReview(makeStorage(rawOtherVersion))
  assert.match(otherVersion.warning, /another catalog version/)
  assert.equal(Object.values(otherVersion.state.choices).every(item => item.decision === 'pending'), true)
})

test('malformed JSON fails closed and reports a warning', () => {
  const loaded = loadCatalogReview(makeStorage('{not-json'))
  assert.match(loaded.warning, /valid JSON/)
  assert.equal(loaded.state.catalogVersion, EXPANDED_CATALOG_VERSION)
  assert.equal(Object.values(loaded.state.choices).every(item => item.decision === 'pending'), true)
})

test('an expanded state reloads unchanged and exports the expanded catalog version', () => {
  const first = loadCatalogReview(makeStorage()).state
  const firstId = CANDIDATE_SCENE_TEMPLATES[0].id
  first.choices[firstId] = { ...first.choices[firstId], decision: 'keep', notes: 'sesión nueva' }
  const raw = serializeReviewChoices(first)
  const reloaded = loadCatalogReview(makeStorage(raw))
  assert.deepEqual(reloaded.state, first)
  assert.equal(reloaded.warning, undefined)

  const exported = JSON.parse(serializeReviewExport(reloaded.state, '2026-09-06T00:00:00.000Z'))
  assert.equal(exported.catalogVersion, EXPANDED_CATALOG_VERSION)
  assert.equal(exported.templates.length, ALL_SCENE_TEMPLATES.length)
})

test('storage errors fail closed without importing any decision', () => {
  const loaded = loadCatalogReview({ getItem: () => { throw new Error('blocked') } })
  assert.match(loaded.warning, /Storage/)
  assert.equal(Object.values(loaded.state.choices).every(item => item.decision === 'pending'), true)
})

test('saving expanded choices preserves legacy bytes and reads the expanded key first', () => {
  const legacy = JSON.stringify({ schemaVersion: 1, catalogVersion: CATALOG_VERSION,
    choices: { [CANDIDATE_SCENE_TEMPLATES[0].id]: choice(CANDIDATE_SCENE_TEMPLATES[0], 'keep') } })
  const values = new Map([[REVIEW_DECISIONS_STORAGE_KEY, legacy]])
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const state = loadCatalogReview(storage).state
  state.choices['music-spiral-exit'].decision = 'discard'
  assert.equal(saveCatalogReview(storage, state), true)
  assert.equal(values.get(REVIEW_DECISIONS_STORAGE_KEY), legacy)
  assert.equal(loadCatalogReview(storage).state.choices['music-spiral-exit'].decision, 'discard')
  values.set(CATALOG_REVIEW_STORAGE_KEY, '{broken')
  assert.equal(loadCatalogReview(storage).state.choices[CANDIDATE_SCENE_TEMPLATES[0].id].decision, 'pending')
  assert.equal(saveCatalogReview(storage, { ...state, catalogVersion: CATALOG_VERSION }), false)
  assert.equal(saveCatalogReview({ setItem() { throw new Error('full') } }, state), false)
})
