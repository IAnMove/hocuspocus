import assert from 'node:assert/strict'
import test from 'node:test'
import { persistMiniMaxSubjectReference } from '../src/lib/imageGeneration.ts'

test('MiniMax keeps workspace files and uploads bundled example stills', async () => {
  assert.equal(
    await persistMiniMaxSubjectReference('/api/v1/file/nilo.png?workspace=default', 'default'),
    '/api/v1/file/nilo.png',
  )
  await assert.rejects(
    persistMiniMaxSubjectReference('/api/v1/file/nilo.png?workspace=other', 'default'),
    /requested workspace/,
  )
  const previous = globalThis.fetch
  globalThis.fetch = async url => {
    if (String(url).includes('/examples/cut-paper/')) {
      return new Response(new Uint8Array([1, 2, 3]), { status: 200, headers: { 'Content-Type': 'image/png' } })
    }
    if (String(url).includes('/api/v1/upload')) {
      return Response.json({ filename: 'nilo-canonical.jpg', url: '/api/v1/uploads/nilo-canonical.jpg', path: 'nilo-canonical.jpg' })
    }
    return new Response('missing', { status: 404 })
  }
  try {
    assert.equal(
      await persistMiniMaxSubjectReference('/examples/cut-paper/puppets/nilo-canonical.jpg', 'default'),
      '/api/v1/uploads/nilo-canonical.jpg',
    )
  } finally {
    globalThis.fetch = previous
  }
})
