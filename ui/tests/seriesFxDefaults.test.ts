import assert from 'node:assert/strict'
import test from 'node:test'
import classes from '../../app/shared/scene_effect_classes.json' with { type: 'json' }
import { defaultFxLength } from '../src/features/series/inspector/fxDefaults.ts'
import { FX_CATALOG } from '../src/features/sceneFx/types.ts'

test('every effect of the catalog has a class, and the inspector shows what an omitted duration means', () => {
  const effects = classes.effects as Record<string, { class: string; duration?: number }>
  assert.deepEqual(Object.keys(effects).sort(), FX_CATALOG.map(item => item.id).sort())
  for (const item of FX_CATALOG) {
    const length = defaultFxLength(item.id)
    if (effects[item.id].class === 'presence') assert.equal(length, 'shot', item.id)
    else assert.ok(typeof length === 'number' && length >= 0.25 && length <= 1, `${item.id}: ${length}`)
  }
  assert.equal(defaultFxLength('anime_aura'), 'shot')
  assert.equal(defaultFxLength('impact_flash'), 0.25)
  assert.equal(defaultFxLength('not-an-effect'), 1)
  assert.equal(defaultFxLength(undefined), 1)
})
