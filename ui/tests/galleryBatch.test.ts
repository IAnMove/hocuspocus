import assert from 'node:assert/strict'
import test from 'node:test'
import type { OutputFile } from '../src/types/index.ts'

const calls: string[] = []
let failing = new Set<string>()
const favorites = new Map<string, boolean>()
globalThis.fetch = (async (input: string | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method || 'GET'
  const name = decodeURIComponent(url.split('/').filter(Boolean).at(method === 'POST' && url.endsWith('/move') ? -2 : -1)!)
  calls.push(`${method} ${name}`)
  if (failing.has(name)) return new Response('no', { status: 500 })
  if (url.includes('/favorites/')) {
    favorites.set(name, !favorites.get(name))
    return Response.json({ name, favorite: favorites.get(name) })
  }
  return Response.json({ ok: true })
}) as typeof fetch

const file = (name: string, favorite = false): OutputFile => ({ name, url: `/f/${name}`, type: 'image', mode: 'image', favorite, size: 1, created_at: 1 })

test('batch favorite only toggles items that need it and reports failures', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { runGalleryBatch } = await import('../src/components/MainContent/galleryBatch.ts')
  const outputs = [file('a.png'), file('b.png', true), file('c.png')]
  favorites.set('b.png', true)
  useStore.setState({ outputs, outputsTotal: 3 })
  calls.length = 0
  failing = new Set(['c.png'])
  const { failed } = await runGalleryBatch({ kind: 'favorite', favorite: true }, outputs)
  assert.deepEqual(failed, ['c.png'])
  assert.deepEqual(calls.sort(), ['POST a.png', 'POST c.png'])
  assert.deepEqual(useStore.getState().outputs.map(item => item.favorite), [true, true, false])
})

test('batch delete and move remove only what succeeded', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { runGalleryBatch } = await import('../src/components/MainContent/galleryBatch.ts')
  const outputs = [file('a.png'), file('b.png'), file('c.png'), file('d.png')]
  useStore.setState({ outputs, outputsTotal: 10, selectedOutput: 3 })
  failing = new Set(['b.png'])
  const deleted = await runGalleryBatch({ kind: 'delete' }, [outputs[0], outputs[1]])
  assert.deepEqual(deleted.failed, ['b.png'])
  assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['b.png', 'c.png', 'd.png'])
  assert.equal(useStore.getState().outputsTotal, 9)
  assert.equal(useStore.getState().selectedOutput, 2)

  failing = new Set()
  calls.length = 0
  const moved = await runGalleryBatch({ kind: 'move', workspace: 'archive' }, [outputs[2]])
  assert.deepEqual(moved.failed, [])
  assert.deepEqual(calls, ['POST c.png'])
  assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['b.png', 'd.png'])
})
