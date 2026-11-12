import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from 'i18next'
import { ensureUiI18n } from '../src/i18n'
import { FAMILIES, themeTextKey } from '../src/lib/theme'

ensureUiI18n()

test('every theme family has a name and a description in both languages', () => {
  const en = i18n.getFixedT('en', 'settings')
  const es = i18n.getFixedT('es', 'settings')
  assert.equal(FAMILIES.length, 17)
  for (const family of FAMILIES) {
    const label = themeTextKey(family.id, 'label')
    const description = themeTextKey(family.id, 'description')
    assert.ok(en(label).trim(), family.id)
    assert.ok(es(description).trim(), family.id)
    assert.notEqual(en(description), es(description), family.id)
  }
  assert.equal(en(themeTextKey('golden-hour', 'label')), 'HocusPocus Blue')
  assert.equal(es(themeTextKey('golden-hour', 'label')), 'HocusPocus Blue')
  assert.equal(es(themeTextKey('default', 'label')), 'Clásico')
  assert.equal(es(themeTextKey('studio', 'label')), 'Estudio')
  assert.match(es(themeTextKey('onyx', 'description')), /negro puro/)
})
