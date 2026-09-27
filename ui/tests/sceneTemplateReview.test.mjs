import assert from 'node:assert/strict'
import test from 'node:test'
import {
  REVIEW_DECISIONS_STORAGE_KEY,
  createReviewChoices,
  createReviewExport,
  loadReviewChoicesResult,
  parseReviewChoicesResult,
  saveReviewChoices,
  serializeReviewChoices,
  serializeReviewExport,
  updateReviewChoice,
} from '../src/features/sceneTemplates/reviewDecisions.ts'

const catalogVersion = 'catalog-1'
const templates = [
  { id: 'cinema-reveal', version: 1 },
  { id: 'space-chase', version: 2 },
]

const fixedChoices = () => JSON.stringify({
  schemaVersion: 1,
  catalogVersion,
  choices: {
    'cinema-reveal': { id: 'cinema-reveal', templateVersion: 1, decision: 'keep', notes: 'Buen ritmo.' },
    'space-chase': { id: 'space-chase', templateVersion: 2, decision: 'discard', notes: 'Revisar el prop.' },
  },
})

test('creates every known template as pending and never auto-approves it', () => {
  const state = createReviewChoices(catalogVersion, templates)
  assert.deepEqual(Object.keys(state.choices), ['cinema-reveal', 'space-chase'])
  assert.equal(state.choices['cinema-reveal'].decision, 'pending')
  assert.equal(state.choices['space-chase'].decision, 'pending')
})

test('parses a fixed catalog and preserves decisions, versions, and notes', () => {
  const result = parseReviewChoicesResult(fixedChoices(), catalogVersion, templates)
  assert.equal(result.warning, undefined)
  assert.deepEqual(result.state.choices['cinema-reveal'], {
    id: 'cinema-reveal', templateVersion: 1, decision: 'keep', notes: 'Buen ritmo.',
  })
  assert.deepEqual(result.state.choices['space-chase'], {
    id: 'space-chase', templateVersion: 2, decision: 'discard', notes: 'Revisar el prop.',
  })
})

test('malformed JSON resets all choices to pending instead of approving anything', () => {
  const result = parseReviewChoicesResult('{not-json', catalogVersion, templates)
  assert.match(result.warning, /valid JSON/)
  assert.deepEqual(Object.values(result.state.choices).map(choice => choice.decision), ['pending', 'pending'])
})

test('a stale catalog version resets all decisions', () => {
  const result = parseReviewChoicesResult(fixedChoices(), 'catalog-2', templates)
  assert.match(result.warning, /another catalog version/)
  assert.deepEqual(Object.values(result.state.choices).map(choice => choice.decision), ['pending', 'pending'])
})

test('unknown IDs and stale template versions are ignored without losing valid choices', () => {
  const raw = JSON.stringify({
    schemaVersion: 1,
    catalogVersion,
    choices: {
      ...JSON.parse(fixedChoices()).choices,
      unknown: { id: 'unknown', templateVersion: 99, decision: 'keep', notes: 'No importar.' },
      'space-chase': { id: 'space-chase', templateVersion: 1, decision: 'keep', notes: 'Versión vieja.' },
    },
  })
  const result = parseReviewChoicesResult(raw, catalogVersion, templates)
  assert.match(result.warning, /IDs or versions/)
  assert.equal(result.state.choices['cinema-reveal'].decision, 'keep')
  assert.equal(result.state.choices['space-chase'].decision, 'pending')
  assert.equal(result.state.choices.unknown, undefined)
})

test('serializes in stable ID order and round-trips fixed versions', () => {
  const parsed = parseReviewChoicesResult(fixedChoices(), catalogVersion, templates).state
  const serialized = serializeReviewChoices(parsed)
  const ids = Object.keys(JSON.parse(serialized).choices)
  assert.deepEqual(ids, ['cinema-reveal', 'space-chase'])
  assert.deepEqual(parseReviewChoicesResult(serialized, catalogVersion, templates).state, parsed)
})

test('updates known choices while clamping notes and rejects unknown IDs', () => {
  const state = createReviewChoices(catalogVersion, templates)
  const longNotes = 'x'.repeat(5_000)
  const updated = updateReviewChoice(state, 'cinema-reveal', 'keep', longNotes)
  assert.equal(updated.choices['cinema-reveal'].decision, 'keep')
  assert.equal(updated.choices['cinema-reveal'].notes.length, 4_000)
  assert.strictEqual(updateReviewChoice(updated, 'missing', 'keep'), updated)
})

test('inaccessible storage fails closed and does not throw', () => {
  const inaccessible = { getItem: () => { throw new Error('blocked') } }
  const loaded = loadReviewChoicesResult(inaccessible, catalogVersion, templates)
  assert.match(loaded.warning, /Storage/)
  assert.deepEqual(Object.values(loaded.state.choices).map(choice => choice.decision), ['pending', 'pending'])

  const failedWrite = { setItem: () => { throw new Error('blocked') } }
  assert.equal(saveReviewChoices(failedWrite, loaded.state), false)
})

test('local storage uses the versioned key and exports explicit review decisions', () => {
  let storedKey
  let storedValue
  const storage = {
    getItem: key => key === REVIEW_DECISIONS_STORAGE_KEY ? storedValue ?? null : null,
    setItem: (key, value) => { storedKey = key; storedValue = value },
  }
  const state = createReviewChoices(catalogVersion, templates)
  assert.equal(saveReviewChoices(storage, state), true)
  assert.equal(storedKey, REVIEW_DECISIONS_STORAGE_KEY)
  assert.deepEqual(loadReviewChoicesResult(storage, catalogVersion, templates).state, state)

  const exported = createReviewExport(state, '2026-09-06T00:00:00.000Z')
  assert.equal(exported.exportedAt, '2026-09-06T00:00:00.000Z')
  assert.deepEqual(exported.templates.map(template => template.decision), ['pending', 'pending'])
  assert.deepEqual(JSON.parse(serializeReviewExport(state, exported.exportedAt)), exported)
})
