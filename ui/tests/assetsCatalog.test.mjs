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
  assert.match(panel, /aria-label=\{t\('headings.assets'\)\}/)
  assert.match(panel, /t\('filters.allWorkspaces'\)/)
  assert.match(panel, /tActivity\('inboxLegacy'\)/)
  assert.match(panel, /tActivity\('extraInfo'\)/)
  assert.match(panel, /outputFolder\.uploads/)
  assert.match(panel, /tActivity\('inspector\.fullJson'\)/)
  assert.match(panel, /tActivity\('inspector\.loadFailed'\)/)
  assert.match(panel, /tCommon\('actions\.close'\)/)
  assert.match(panel, /labelKey: 'tabs\.all'/)
  assert.match(panel, /labelKey: 'tabs\.images'/)
  assert.match(panel, /labelKey: 'tabs\.videos'/)
  assert.match(panel, /labelKey: 'tabs\.audio'/)
  assert.match(panel, /labelKey: 'tabs\.model3d'/)
  assert.match(panel, /labelKey: 'tabs\.scenes'/)
  assert.match(panel, /labelKey: 'tabs\.documents'/)
  assert.match(panel, /tActivity\('catalog\.itemsAcrossLocations'/)
  assert.match(panel, /tActivity\('catalog\.searchPlaceholder'\)/)
  assert.match(panel, /tActivity\('catalog\.kindFilter'\)/)
  assert.match(panel, /tActivity\('catalog\.workspaceFilter'\)/)
  assert.match(panel, /tActivity\('catalog\.reload'\)/)
  assert.match(panel, /tActivity\('catalog\.loadFailed'\)/)
  assert.match(panel, /tActivity\('catalog\.reading'\)/)
  assert.match(panel, /tActivity\('catalog\.empty'\)/)
  assert.match(panel, /tActivity\('catalog\.loadMore'\)/)
  assert.match(panel, /tCommon\('actions\.search'\)/)
  assert.match(panel, /tCommon\('actions\.reload'\)/)
  assert.doesNotMatch(panel, /JSON completo/)
  assert.doesNotMatch(panel, /No se pudo cargar Extra info/)
  assert.doesNotMatch(panel, /elementos en todas las ubicaciones/)
  assert.doesNotMatch(panel, /Buscar prompt, modelo, herramienta/)
  assert.doesNotMatch(panel, /Leyendo el catálogo/)
  assert.doesNotMatch(panel, /No se pudo cargar el catálogo/)
  assert.doesNotMatch(panel, /No hay assets que coincidan/)
  assert.doesNotMatch(panel, /Actualizar catálogo/)
  assert.doesNotMatch(panel, /Cargar más/)
  assert.doesNotMatch(panel, /['"`]Asset kind['"`]/)
  assert.doesNotMatch(panel, /['"`]Asset workspace['"`]/)
  assert.doesNotMatch(panel, /setActiveWorkspace|switchWorkspace/)
})
