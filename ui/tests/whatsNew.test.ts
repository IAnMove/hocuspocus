import assert from 'node:assert/strict'
import test from 'node:test'
import i18n from '../src/i18n/index.ts'
import { WHATS_NEW, WHATS_NEW_MIN_PR, latestWhatsNewPr } from '../src/whatsNew.ts'

test('the newest welcome line stays at or above the reminder constant', () => {
  assert.ok(
    latestWhatsNewPr() >= WHATS_NEW_MIN_PR,
    `newest welcome PR ${latestWhatsNewPr()} is below WHATS_NEW_MIN_PR ${WHATS_NEW_MIN_PR}`,
  )
  const numbers = WHATS_NEW.map(item => item.pr)
  assert.equal(latestWhatsNewPr(), Math.max(...numbers))
  assert.deepEqual(numbers, [...numbers].sort((a, b) => b - a))
  for (const item of WHATS_NEW) {
    const en = String(i18n.t(item.key, { ns: 'common', lng: 'en' }))
    const es = String(i18n.t(item.key, { ns: 'common', lng: 'es' }))
    assert.notEqual(en, item.key)
    assert.notEqual(es, item.key)
    assert.notEqual(en, es)
  }
})
