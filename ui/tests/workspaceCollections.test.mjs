import assert from 'node:assert/strict'
import test from 'node:test'

test('Workspace collection client persists exact references and revisions', async () => {
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    if (options.method === 'DELETE') return new Response(null, { status: 204 })
    const value = options.body ? JSON.parse(String(options.body)) : {}
    return new Response(JSON.stringify(options.method === 'POST' || options.method === 'PUT'
      ? { schema: 'hocuspocus.workspace-record', schema_version: 1, id: 'workspace-1', revision: 2, name: value.name || 'Film', description: value.description || '', project_ids: value.project_ids || [], asset_ids: value.asset_ids || [], production_ids: value.production_ids || [], created_at: null, updated_at: null }
      : { workspaces: [], total: 0 }), { status: options.method === 'POST' ? 201 : 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    const client = await import('../src/api/client.ts')
    await client.fetchWorkspaceCollections()
    await client.createWorkspaceCollection({ name: 'Film' })
    await client.updateWorkspaceCollection({ schema: 'hocuspocus.workspace-record', schema_version: 1, id: 'workspace-1', revision: 1, name: 'Film', description: '', project_ids: ['project-1'], asset_ids: ['asset-1'], production_ids: ['production-1'], created_at: null, updated_at: null })
    await client.deleteWorkspaceCollection('workspace-1')

    assert.equal(new URL(calls[0].url, 'http://localhost').pathname, '/api/v1/workspace-collections')
    assert.equal(calls[1].options.method, 'POST')
    assert.equal(JSON.parse(calls[2].options.body).expected_revision, 1)
    assert.deepEqual(JSON.parse(calls[2].options.body).project_ids, ['project-1'])
    assert.equal(calls[3].options.method, 'DELETE')
  } finally { globalThis.fetch = originalFetch }
})

test('Workspaces panel is a collection editor and physical locations are labelled output folders', async () => {
  const fs = await import('node:fs/promises')
  const [tabs, main, outputSelector, panel] = await Promise.all([
    fs.readFile(new URL('../src/components/MainContent/TabFilter.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/components/MainContent/MainContent.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/components/MainContent/OutputFolderSelector.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/features/workspaceCollections/WorkspaceCollectionsPanel.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(tabs, /value: 'workspaces'/)
  assert.match(tabs, /<OutputFolderSelector/)
  assert.match(main, /<WorkspaceCollectionsPanel/)
  assert.doesNotMatch(main, /outputFolder\.list|<OutputFolderSelector/)
  assert.match(outputSelector, /outputFolder\.list/)
  assert.match(panel, /aria-label=\{tWs\('collections.aria'\)\}/)
  assert.doesNotMatch(panel, /switchWorkspace|setActiveWorkspace/)
})
