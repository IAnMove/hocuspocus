import assert from 'node:assert/strict'
import test from 'node:test'

test('project API sends global identity filters through the client facade', async () => {
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async url => {
    calls.push(String(url))
    return new Response(JSON.stringify({ projects: [], total: 0, warnings: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const client = await import('../src/api/client.ts')
    assert.equal(typeof client.fetchProjects, 'function')
    await client.fetchProjects({ search: 'server', kind: 'story', workspace: 'night', limit: 20, offset: 5 })
    const url = new URL(calls[0], 'http://localhost')
    assert.equal(url.pathname, '/api/v1/projects')
    assert.equal(url.searchParams.get('kind'), 'story')
    assert.equal(url.searchParams.get('workspace'), 'night')
    assert.equal(url.searchParams.get('offset'), '5')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Projects is global and does not mutate the active workspace', async () => {
  const fs = await import('node:fs/promises')
  const [tabs, main, panel] = await Promise.all([
    fs.readFile(new URL('../src/components/MainContent/TabFilter.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/components/MainContent/MainContent.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/features/projects/ProjectsPanel.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(tabs, /value: 'projects'/)
  assert.match(main, /<ProjectsPanel/)
  assert.match(panel, /aria-label="All projects"/)
  assert.doesNotMatch(panel, /setActiveWorkspace|switchWorkspace/)
})

test('project opening prefers the active registered source and never resolves by title', async () => {
  const { resolveProjectSource } = await import('../src/features/projects/openProject.ts')
  const project = {
    id: 'story-immutable', kind: 'story', title: 'A duplicated title',
    sources: [
      { workspace_id: 'alpha', adapter: 'story-library-v2', key: 'story:story-immutable' },
      { workspace_id: 'beta', adapter: 'story-library-v2', key: 'story:story-immutable' },
    ],
  }
  assert.equal(resolveProjectSource(project, 'beta').workspace_id, 'beta')
  assert.equal(resolveProjectSource(project, 'missing').workspace_id, 'alpha')
  assert.throws(() => resolveProjectSource({ ...project, sources: [] }, 'alpha'), /ubicación persistente/)
})
