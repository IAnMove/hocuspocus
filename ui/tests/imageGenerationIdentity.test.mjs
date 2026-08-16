import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

test('MiniMax recovery fetches the saved terminal job and preserves all task identities', async () => {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  globalThis.window = dom.window
  globalThis.document = dom.window.document
  // The production polling delay is intentionally bypassed in this unit test.
  dom.window.setTimeout = callback => { callback(); return 0 }
  const calls = []
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ url: String(input), method: init.method || 'GET' })
    if (String(input).includes('/jobs/saved-job')) {
      return new Response(JSON.stringify({
        jobId: 'saved-job', status: 'completed', workspace: 'default',
        phase: 'complete', message: 'Ready', current: 1, total: 1, progress: 1,
        taskId: 'task-from-job', rootTaskId: 'root-from-job',
        result: { asset: { id: 'asset-1', name: 'saved.webp', kind: 'local', metadata: {
          jobId: 'old-job', taskId: 'old-task', rootTaskId: 'old-root',
        } } },
      }), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`unexpected request: ${String(input)}`)
  }
  const { generateImageAsset } = await import('../src/lib/imageGeneration.ts')

  const asset = await generateImageAsset('minimax', 'A rainy cyclist', undefined, undefined, '', {
    existingJobId: 'saved-job',
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].method, 'GET')
  assert.match(calls[0].url, /\/jobs\/saved-job$/)
  assert.deepEqual(asset.metadata, {
    jobId: 'saved-job', taskId: 'task-from-job', rootTaskId: 'root-from-job',
  })
  dom.window.close()
})
