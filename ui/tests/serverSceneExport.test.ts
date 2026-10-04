import assert from 'node:assert/strict'
import test from 'node:test'
import { renderOnServer } from '../src/features/render/serverSceneExport.ts'

test('a final export posts the level and returns the published file', async () => {
  const bodies: unknown[] = []
  const fetchImpl = async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST' && url.endsWith('/export')) {
      bodies.push(JSON.parse(String(init.body)))
      return new Response('{}', { status: 200 })
    }
    return new Response(JSON.stringify({
      task: { status: 'completed', current: 2, total: 2 },
      receipt: { artifacts: [{ name: 'shot.mp4', url: '/api/v1/file/shot.mp4' }] },
    }), { status: 200 })
  }
  const saved = await renderOnServer({
    kind: 'world3d',
    workspace: 'default',
    document: { slots: [] },
    level: 'master',
    shutter: 90,
    fetchImpl,
    sleep: async () => undefined,
  })
  assert.equal(saved.name, 'shot.mp4')
  const posted = bodies[0] as { operation: string; input: { quality: string; shutter: number } }
  assert.equal(posted.operation, 'scenes.world3d.export')
  assert.equal(posted.input.quality, 'master')
  assert.equal(posted.input.shutter, 90)
})

test('a completed receipt keeps quality and geometry warnings', async () => {
  const fetchImpl = async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return new Response('{}', { status: 200 })
    return new Response(JSON.stringify({
      task: { status: 'completed' },
      receipt: {
        artifacts: [{ name: 'shot.mp4', url: '/api/v1/file/shot.mp4' }],
        qa: { verdict: 'fail', warnings: [{ code: 'black', t: 0.5 }] },
        geometry: { verdict: 'watch', warnings: [{ code: 'floating', severity: 'watch', slot: 'hero', start: 1, end: 2 }] },
      },
    }), { status: 200 })
  }
  const saved = await renderOnServer({
    kind: 'world3d', workspace: 'default', document: { slots: [] }, level: 'final', shutter: 0,
    fetchImpl, sleep: async () => undefined,
  })
  assert.equal(saved.qa?.warnings?.[0]?.code, 'black')
  assert.equal(saved.geometry?.warnings?.[0]?.slot, 'hero')
})

test('a failed server render surfaces the task message', async () => {
  const fetchImpl = async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return new Response('{}', { status: 200 })
    return new Response(JSON.stringify({ task: { status: 'failed', message: 'missing media' } }), { status: 200 })
  }
  await assert.rejects(
    () => renderOnServer({
      kind: 'video2d', workspace: 'default', document: { layers: [] }, level: 'final', shutter: 180,
      fetchImpl, sleep: async () => undefined,
    }),
    /missing media/,
  )
})
