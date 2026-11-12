import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { ensureUiI18n } from '../src/i18n'
import { NARRATIVE_SCENE_TEMPLATES } from '../src/lib/sceneNarrative'

ensureUiI18n()

test('narrative slot names translate, and the stored title stays the English prompt', () => {
  const en = i18n.getFixedT('en', 'studio')
  const es = i18n.getFixedT('es', 'studio')
  const thought = NARRATIVE_SCENE_TEMPLATES.find(item => item.id === 'inner-thought')
  assert.ok(thought)
  assert.equal(thought.title, 'Inner thought')
  assert.equal(thought.description, 'A three-quarter medium close-up for voice-over and a contemplative beat.')
  assert.equal(thought.assetSlots[0].labelKey, 'narrativeSlots.character')
  assert.equal(en(thought.assetSlots[0].labelKey as 'narrativeSlots.character'), 'Character')
  assert.equal(es(thought.assetSlots[0].labelKey as 'narrativeSlots.character'), 'Personaje')
  const keys = new Set(NARRATIVE_SCENE_TEMPLATES.flatMap(item => item.assetSlots.map(slot => slot.labelKey)))
  assert.equal(keys.size, 24)
  for (const key of keys) {
    const typed = key as 'narrativeSlots.character'
    assert.notEqual(en(typed), es(typed), key)
  }
})
