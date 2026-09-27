import assert from 'node:assert/strict'
import test from 'node:test'
import type { OutputFile } from '../src/types/index.ts'

const calls: string[] = []
let failing = new Set<string>()
let hold: Promise<void> = Promise.resolve()
const favorites = new Map<string, boolean>()
globalThis.fetch = (async (input: string | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method || 'GET'
  const path = url.split('?')[0]
  const name = decodeURIComponent(path.split('/').filter(Boolean).at(method === 'POST' && path.endsWith('/move') ? -2 : -1)!)
  const body = init?.body ? JSON.parse(String(init.body)) as { source_workspace?: string } : {}
  const listed = new URL(url, 'http://gallery.test').searchParams.get('workspace') || body.source_workspace || ''
  calls.push(`${method} ${name} ${listed}`.trim())
  await hold
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
  assert.deepEqual(calls, ['POST c.png default'])
  assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['b.png', 'd.png'])
})

test('batch delete and move pin the listed workspace and do not rewrite a switched list', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { runGalleryBatch } = await import('../src/components/MainContent/galleryBatch.ts')
  const hero = file('hero.png')
  useStore.setState({ activeWorkspace: 'film', browsingUploads: false, outputs: [hero], outputsTotal: 1 })
  let release!: () => void
  hold = new Promise<void>(resolve => { release = resolve })
  calls.length = 0
  failing = new Set()
  const pending = runGalleryBatch({ kind: 'delete' }, [hero])
  useStore.setState({ activeWorkspace: 'ads', browsingUploads: false, outputs: [hero, file('other.png')], outputsTotal: 2 })
  release()
  const { failed } = await pending
  assert.deepEqual(failed, [])
  assert.deepEqual(calls, ['DELETE hero.png film'])
  assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['hero.png', 'other.png'])

  hold = Promise.resolve()
  useStore.setState({ activeWorkspace: 'film', browsingUploads: false, outputs: [hero], outputsTotal: 1 })
  calls.length = 0
  await runGalleryBatch({ kind: 'move', workspace: 'archive' }, [hero])
  assert.deepEqual(calls, ['POST hero.png film'])
})
