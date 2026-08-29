import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { NARRATIVE_SCENE_TEMPLATES } from '../src/lib/sceneNarrative.ts'

const prompts = JSON.parse(readFileSync(new URL('./fixtures/goldenPrompts.json', import.meta.url), 'utf8'))
const known = new Set(NARRATIVE_SCENE_TEMPLATES.map(template => template.id))

test('every expectation names a template that actually exists', () => {
  // Without this, renaming a template quietly turns its golden prompts
  // unpassable and the eval reports a selection regression that never
  // happened.
  const missing = prompts.flatMap(entry =>
    entry.expects.templateAnyOf.filter(id => !known.has(id)).map(id => `${entry.id} -> ${id}`))
  assert.deepEqual(missing, [])
})

test('the prompt set keeps its shape', () => {
  const ids = prompts.map(entry => entry.id)
  assert.equal(new Set(ids).size, ids.length, 'prompt ids are unique')
  for (const entry of prompts) {
    assert.ok(['es', 'en'].includes(entry.lang), `${entry.id} declares a language`)
    assert.ok(entry.prompt.length > 20, `${entry.id} reads like a real request`)
    assert.ok(entry.expects.templateAnyOf.length > 0, `${entry.id} accepts at least one answer`)
    assert.ok(['landscape', 'portrait'].includes(entry.expects.aspect), `${entry.id} declares an aspect`)
    assert.ok(entry.expects.minShots >= 1 && entry.expects.maxShots >= entry.expects.minShots, `${entry.id} has a sane shot range`)
  }
})

test('the prompt set holds the coverage the evaluation depends on', () => {
  const count = predicate => prompts.filter(predicate).length
  assert.ok(prompts.length >= 25, 'at least 25 prompts')
  assert.ok(count(entry => entry.lang === 'es') >= 12, 'Spanish is properly represented')
  assert.ok(count(entry => entry.lang === 'en') >= 12, 'English is properly represented')
  // These two exist to trip known defects on purpose: the 10-second floor in
  // durationOf, and template coordinates hardcoded as 16:9 percentages. If
  // they are ever dropped, the eval stops being able to see either.
  assert.ok(count(entry => entry.expects.durationHint && entry.expects.durationHint <= 7) >= 6, 'short-beat requests')
  assert.ok(count(entry => entry.expects.aspect === 'portrait') >= 5, 'portrait requests')
  const conversational = new Set(['dialogue', 'character'])
  const categoryOf = id => NARRATIVE_SCENE_TEMPLATES.find(template => template.id === id)?.category
  assert.ok(
    count(entry => entry.expects.templateAnyOf.some(id => conversational.has(categoryOf(id)))) >= 8,
    'dialogue and character requests, where the near-duplicate templates live',
  )
  assert.ok(prompts.some(entry => entry.id === 'snowy-station'), 'the anchor prompt is present')
})

test('prompts do not leak template vocabulary into the request', () => {
  // A prompt containing its own answer tests string matching, not judgement.
  for (const entry of prompts) {
    const haystack = entry.prompt.toLowerCase()
    for (const id of entry.expects.templateAnyOf) {
      assert.ok(!haystack.includes(id), `${entry.id} names ${id} outright`)
      assert.ok(!haystack.includes(id.replace(/-/g, ' ')), `${entry.id} spells out ${id}`)
    }
  }
})
