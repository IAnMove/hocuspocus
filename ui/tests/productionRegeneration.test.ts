import assert from 'node:assert/strict'
import test from 'node:test'
import { postShotAction } from '../src/features/production-shots/api.ts'

for (const status of [200, 409]) {
  test(`shared regeneration delegates once and resets review only after success (${status})`, async context => {
    const calls: { url: string; body: Record<string, unknown> }[] = []
    const generator = '/api/v1/music-productions/clip1/shots/s1/redo?workspace=film'
    context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
      const body = JSON.parse(options.body as string)
      calls.push({ url, body })
      if (url === generator) return new Response('{}', { status })
      return Response.json(body.action === 'regenerate'
        ? { applied: false, regeneration: { executor: 'http', path: generator, body: { from: 'clip' } } }
        : { applied: true })
    })
    const request = postShotAction('film', 'clip1', 's1', { action: 'regenerate', expected_revision: 3 })
    if (status === 200) {
      await request
      assert.equal(calls.length, 3)
      assert.equal(calls[2].body.status, 'pending')
    } else {
      await assert.rejects(request, /409/)
      assert.equal(calls.length, 2)
    }
    assert.equal(calls[1].url, generator)
  })
}

test('missing generation target is reported rather than recording a successful retake', async context => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ applied: false }))
  await assert.rejects(postShotAction('film', 'clip1', 's1', { action: 'regenerate' }), /unavailable/)
})
