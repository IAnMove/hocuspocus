import assert from 'node:assert/strict'
import test from 'node:test'
import { loadArchitectureGraph } from '../src/features/architecture/architectureLoader'

test('graph loader bounds chunked response bytes without trusting content-length', async () => {
  let cancelled = false
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) { controller.enqueue(new Uint8Array(512 * 1024)) },
    cancel() { cancelled = true },
  })
  await assert.rejects(loadArchitectureGraph(async () => new Response(stream)), /too large/)
  assert.equal(cancelled, true)
})

test('graph loader rejects missing, oversized declared and invalid JSON responses', async () => {
  await assert.rejects(loadArchitectureGraph(async () => new Response('', { status: 404 })), /404/)
  await assert.rejects(loadArchitectureGraph(async () => new Response('{}', {
    headers: { 'Content-Length': '3000000' },
  })), /too large/)
  await assert.rejects(loadArchitectureGraph(async () => new Response('not json')), /invalid JSON/)
})
