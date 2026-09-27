import assert from 'node:assert/strict'
import test from 'node:test'
import { randomUuid } from '../src/lib/uuid'
import { createSeriesCharacter, createSeriesLocation, createSeriesProp, createVisualVariant } from '../src/features/series/model'

test('document IDs retain their UUID formats when LAN HTTP exposes only getRandomValues', (t) => {
  const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')!
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto)
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { getRandomValues } })
  t.after(() => Object.defineProperty(globalThis, 'crypto', cryptoDescriptor))
  assert.equal(typeof globalThis.crypto.randomUUID, 'undefined')

  const ids = Array.from({ length: 100 }, () => randomUuid())
  assert.equal(new Set(ids).size, ids.length)
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  for (const [prefix, create] of [
    ['character', createSeriesCharacter], ['location', createSeriesLocation],
    ['prop', createSeriesProp], ['variant', createVisualVariant],
  ] as const) {
    assert.match(create().id, new RegExp(`^${prefix}_[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$`))
  }
})
