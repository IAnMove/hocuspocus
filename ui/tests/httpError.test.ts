import assert from 'node:assert/strict'
import test from 'node:test'

const json = (body: unknown, status: number) => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
})

test('fetchJobStatus throws an HttpError carrying the status and backend detail', async () => {
  const { fetchJobStatus } = await import('../src/api/generation.ts')
  const { HttpError, isHttpStatus } = await import('../src/api/http.ts')
  const previousFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => json({ detail: 'Job not found' }, 404)
    const lost = await fetchJobStatus('gone').catch(reason => reason as unknown)
    assert.ok(lost instanceof HttpError)
    assert.equal(lost.status, 404)
    assert.equal(lost.detail, 'Job not found')
    assert.equal(lost.message, 'Job not found')
    assert.equal(isHttpStatus(lost, 404), true)

    globalThis.fetch = async () => new Response('<html>Bad Gateway</html>', { status: 502 })
    const outage = await fetchJobStatus('live').catch(reason => reason as unknown)
    assert.ok(outage instanceof HttpError)
    assert.equal(outage.status, 502)
    assert.equal(outage.message, 'Failed to fetch job status')
    assert.equal(isHttpStatus(outage, 404), false)
    assert.equal(isHttpStatus(new Error('offline'), 404), false)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('fetchHunyuan3DJob shares the same error type', async () => {
  const { fetchHunyuan3DJob } = await import('../src/api/model3d.ts')
  const { HttpError } = await import('../src/api/http.ts')
  const previousFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response('', { status: 404 })
    const lost = await fetchHunyuan3DJob('gone').catch(reason => reason as unknown)
    assert.ok(lost instanceof HttpError)
    assert.equal(lost.status, 404)
    assert.equal(lost.message, 'Hunyuan3D job not found')
  } finally {
    globalThis.fetch = previousFetch
  }
})
