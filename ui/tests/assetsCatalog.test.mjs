import assert from 'node:assert/strict'
import test from 'node:test'

test('asset API sends global filters and exposes the canonical client facade', async () => {
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return new Response(JSON.stringify({ assets: [], total: 0 }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const client = await import('../src/api/client.ts')
    assert.equal(typeof client.fetchAssets, 'function')
    await client.fetchAssets({ search: 'server choir', kind: 'video', workspace: 'film', limit: 25, offset: 5 })
    const url = new URL(calls[0].url, 'http://localhost')
    assert.equal(url.pathname, '/api/v1/assets')
    assert.equal(url.searchParams.get('search'), 'server choir')
    assert.equal(url.searchParams.get('kind'), 'video')
    assert.equal(url.searchParams.get('workspace'), 'film')
    assert.equal(url.searchParams.get('limit'), '25')
    assert.equal(url.searchParams.get('offset'), '5')
    await client.fetchAssets({ collection: 'inbox_legacy' })
    assert.equal(new URL(calls[1].url, 'http://localhost').searchParams.get('collection'), 'inbox_legacy')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Assets is a first-class tab with its own panel, not a fake active workspace', async () => {
  const fs = await import('node:fs/promises')
  const [tabs, main, panel] = await Promise.all([
    fs.readFile(new URL('../src/components/MainContent/TabFilter.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/components/MainContent/MainContent.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/features/assets/AssetsPanel.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(tabs, /value: 'assets'/)
  assert.match(main, /<AssetsPanel/)
  assert.match(panel, /aria-label="All assets"/)
  assert.match(panel, /Inbox \/ Legacy/)
  assert.match(panel, /Extra info/)
  assert.match(panel, /JSON completo/)
  assert.doesNotMatch(panel, /setActiveWorkspace|switchWorkspace/)
})
