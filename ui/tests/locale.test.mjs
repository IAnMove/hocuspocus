import assert from 'node:assert/strict'
import test from 'node:test'

import { formatAppAction, formatAppTimestamp } from '../src/lib/locale.ts'

const timestamp = Date.UTC(2026, 7, 16, 13, 14, 15)

test('formats media and Activity timestamps deterministically for es-ES', () => {
  assert.equal(
    formatAppTimestamp(timestamp, { locale: 'es-ES', timeZone: 'UTC' }),
    '16 ago 2026, 13:14:15',
  )
  assert.equal(formatAppAction('finished', 'es-ES'), 'Finalizado')
  assert.equal(formatAppAction('updated', 'es-ES'), 'Actualizado')
})

test('formats the same timestamp and glossary in an alternate locale', () => {
  assert.equal(
    formatAppTimestamp(timestamp, { locale: 'en-US', timeZone: 'UTC' }),
    'Aug 16, 2026, 01:14:15 PM',
  )
  assert.equal(formatAppAction('added', 'en-US'), 'Added')
  assert.equal(formatAppAction('finished', 'en-US'), 'Finished')
})
