import assert from 'node:assert/strict'
import test from 'node:test'
import { useStore } from '../src/stores/useStore.ts'
import { galleryThumbnailUrl } from '../src/components/MainContent/galleryThumbnail.ts'

const originalFetch = globalThis.fetch
test.afterEach(() => { globalThis.fetch = originalFetch })
const file = (name: string) => ({ name, url: `/api/v1/file/${name}`, type: 'image' as const,
  mode: 'image' as const, favorite: false, size: 10, created_at: 1 })
const flush = () => new Promise(resolve => setTimeout(resolve, 0))

test('refresh reconciles deletions, order and selected identity', async () => {
  const files = ['a.png', 'b.png', 'c.png'].map(file)
  useStore.setState({ activeWorkspace: 'default', browsingUploads: false, mediaFilter: 'images',
    outputSearchQuery: '', galleryOrder: 'oldest', galleryFeedAtTop: true,
    outputs: files, outputsTotal: 3, selectedOutput: 2 })
  globalThis.fetch = async () => Response.json({ outputs: [file('c.png'), file('a.png')], total: 2 })
  await useStore.getState().refreshOutputs()
  assert.deepEqual(useStore.getState().outputs.map(f => f.name), ['c.png', 'a.png'])
  assert.equal(useStore.getState().selectedOutput, 0)
  assert.equal(useStore.getState().outputsTotal, 2)
})

test('generation refreshes wait for initial loading and coalesce into one follow-up', async () => {
  useStore.setState({ activeWorkspace: 'default', browsingUploads: false, mediaFilter: 'images',
    outputSearchQuery: '', galleryFeedAtTop: true, outputs: [], outputsTotal: 0 })
  let release!: (response: Response) => void
  let requests = 0
  let signal: AbortSignal | null | undefined
  globalThis.fetch = async (input, options) => {
    if (String(input).includes('/metadata')) return Response.json({ params: null })
    requests++
    if (requests === 1) {
      signal = options?.signal
      return new Promise(resolve => { release = resolve })
    }
    return Response.json({ outputs: [file('new.png'), file('old.png')], total: 2 })
  }
  const loading = useStore.getState().loadOutputs()
  await useStore.getState().refreshOutputs()
  await useStore.getState().refreshOutputs()
  assert.equal(requests, 1)
  assert.equal(signal?.aborted, false)
  release(Response.json({ outputs: [file('old.png')], total: 1 }))
  await loading
  await flush()
  assert.equal(requests, 2)
  assert.deepEqual(useStore.getState().outputs.map(f => f.name), ['new.png', 'old.png'])
})

test('legacy original-file thumbnail URLs cannot load full images in the gallery', () => {
  const src = galleryThumbnailUrl({ ...file('large.png'), thumbnail_url: '/api/v1/file/large.png' }, 'archive', 'sm')!
  assert.match(src, /\/outputs\/thumbnail\/large.png/)
  assert.match(src, /workspace=archive/)
  assert.match(src, /size=sm/)
})
