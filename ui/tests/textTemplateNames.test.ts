import assert from 'node:assert/strict'
import test from 'node:test'
import lines from '../../app/shared/video2d_lines.json' with { type: 'json' }
import en from '../src/i18n/locales/en/kineticText.json' with { type: 'json' }
import es from '../src/i18n/locales/es/kineticText.json' with { type: 'json' }
import { TEXT_TEMPLATES } from '../src/lib/kineticText/templates.ts'

const lookup = (catalog: unknown, key: string) =>
  key.split('.').reduce<unknown>((node, part) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined), catalog)

test('the text template picker shows a name in both languages, the one scenes.catalog gives', () => {
  const copy = lines.text as Record<string, { titleEs: string; titleEn: string }>
  for (const template of TEXT_TEMPLATES) {
    assert.equal(lookup(es, template.labelKey), copy[template.id].titleEs, template.id)
    assert.equal(lookup(en, template.labelKey), copy[template.id].titleEn, template.id)
    for (const field of template.fields) {
      for (const catalog of [es, en]) {
        const name = lookup(catalog, field.labelKey)
        assert.ok(typeof name === 'string' && name.length > 0, `${template.id}.${field.key}`)
      }
    }
  }
  assert.deepEqual(Object.keys(es.templates), Object.keys(en.templates))
  assert.deepEqual(Object.keys(es.fields), Object.keys(en.fields))
})
