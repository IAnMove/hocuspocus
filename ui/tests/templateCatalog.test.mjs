import assert from 'node:assert/strict'
import test from 'node:test'
import { NARRATIVE_SCENE_TEMPLATES } from '../src/lib/sceneNarrative.ts'
import { buildTemplateCatalog } from '../src/lib/templateCatalog.ts'

test('the catalog covers the whole library exactly once', () => {
  const catalog = buildTemplateCatalog()
  assert.equal(catalog.length, NARRATIVE_SCENE_TEMPLATES.length)
  assert.deepEqual(
    catalog.map(entry => entry.id).sort(),
    NARRATIVE_SCENE_TEMPLATES.map(template => template.id).sort(),
  )
  assert.equal(new Set(catalog.map(entry => entry.id)).size, catalog.length)
})

test('every entry carries what a choice needs and nothing more', () => {
  const expected = ['id', 'category', 'visualIntent', 'defaultDuration', 'controls', 'constraints', 'slots']
  for (const entry of buildTemplateCatalog()) {
    assert.deepEqual(Object.keys(entry).sort(), [...expected].sort(), `${entry.id} exposes exactly the selection fields`)
    assert.ok(entry.visualIntent.length > 20, `${entry.id} states its visual intent`)
    assert.ok(entry.slots.length > 0, `${entry.id} declares at least one slot`)
    for (const slot of entry.slots) {
      assert.deepEqual(Object.keys(slot).sort(), ['id', 'required', 'types'], `${entry.id}/${slot.id} keeps the slot shape minimal`)
      assert.ok(slot.types.length > 0, `${entry.id}/${slot.id} accepts at least one asset type`)
      assert.equal(typeof slot.required, 'boolean', `${entry.id}/${slot.id} states whether it is required`)
    }
  }
})

test('the catalog is fully serializable', () => {
  const catalog = buildTemplateCatalog()
  // createScene is a function and would vanish silently through JSON, taking
  // any consumer that expected it with it. Prove it was never included.
  assert.doesNotThrow(() => JSON.stringify(catalog))
  assert.deepEqual(JSON.parse(JSON.stringify(catalog)), catalog)
  const walk = value => {
    if (typeof value === 'function') assert.fail('catalog contains a function')
    if (Array.isArray(value)) value.forEach(walk)
    else if (value && typeof value === 'object') Object.values(value).forEach(walk)
  }
  walk(catalog)
})

test('the catalog copies the library rather than aliasing it', () => {
  const catalog = buildTemplateCatalog()
  const entry = catalog.find(item => item.id === 'inner-thought')
  const template = NARRATIVE_SCENE_TEMPLATES.find(item => item.id === 'inner-thought')
  assert.notEqual(entry.controls, template.controls)
  assert.notEqual(entry.constraints, template.constraints)
  entry.controls.push('mood')
  assert.ok(!template.controls.includes('mood') || template.controls.filter(c => c === 'mood').length === 1)
})

test('the whole catalog stays inside a workable prompt budget', () => {
  const serialized = JSON.stringify(buildTemplateCatalog())
  // A selection prompt also has to carry the user request, the asset
  // inventory and the output schema. 24k characters is roughly 6k tokens,
  // which leaves room for all three. Crossing it is the signal that the
  // catalog needs faceted retrieval instead of a full dump.
  assert.ok(serialized.length < 24_000, `catalog serializes to ${serialized.length} characters`)
})
