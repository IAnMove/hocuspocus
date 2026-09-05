import assert from 'node:assert/strict'
import test from 'node:test'

import { canonicalClientTaskId, upsertCanonicalClientTask } from '../src/api/client.ts'


test('client task ids use exactly one isolated prefix', () => {
  assert.equal(canonicalClientTaskId('task-generation-demo'), 'task-client-task-generation-demo')
  assert.equal(canonicalClientTaskId('task-client-task-generation-demo'), 'task-client-task-generation-demo')
  assert.equal(canonicalClientTaskId('task-client-task-client-demo'), 'task-client-demo')
  assert.notEqual(canonicalClientTaskId(null), canonicalClientTaskId(null))
})


test('client upsert strips a caller-controlled root before publishing', async () => {
  let published
  globalThis.fetch = async (_input, init = {}) => {
    published = JSON.parse(String(init.body || '{}')).task
    return new Response(JSON.stringify({ id: published.id }), {
      headers: { 'content-type': 'application/json' },
    })
  }

  await upsertCanonicalClientTask({
    id: 'task-director-demo',
    root_id: 'task-generation-victim',
    rootId: 'task-generation-victim',
  })

  assert.deepEqual(published, { id: 'task-client-task-director-demo' })
})
