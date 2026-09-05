import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    SVGElement: dom.window.SVGElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
    localStorage: dom.window.localStorage,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
}

installDom()

const payload = {
  nodes: [
    { id: 'ui.story', layer: 'ui', label: 'Story Lab', detail: 'Story panel', evidence: [{ file: 'ui/src/features/stories/StoryLabPanel.tsx', line: 12 }] },
    { id: 'api.director', layer: 'api', label: 'Director API', detail: 'Director route', evidence: [{ file: 'ui/src/api/director.ts', line: 22 }] },
  ],
  edges: [
    { source: 'ui.story', target: 'api.director', kind: 'http', label: 'POST', weight: 1, evidence: [{ file: 'ui/src/api/director.ts', line: 22 }] },
    { source: 'ui.story', target: 'api.director', kind: 'reference', label: '', weight: 0, evidence: [{ file: 'ui/src/api/director.ts', line: 23 }] },
  ],
  meta: {
    schema_version: 1,
    scope: 'Story Lab → Director',
    source_commit: '0123456789abcdef0123456789abcdef01234567',
    dirty: false,
    source_hash: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    generated_by: 'test',
    limitations: [],
    warnings: [],
  },
}

test('architecture data is not fetched until the developer Architecture tab opens', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { DeveloperToolsPanel } = await import('../src/features/auditdev/DeveloperToolsPanel.tsx')
  ensureUiI18n()
  await setUiLanguage('en')
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = async input => {
    const url = String(input)
    calls.push(url)
    if (url.includes('/dev/architecture/')) return new Response(JSON.stringify(payload), { status: 200 })
    return new Response(JSON.stringify({ outputs: [] }), { status: 200 })
  }
  try {
    render(<DeveloperToolsPanel />)
    await screen.findByRole('tab', { name: 'Architecture' })
    assert.equal(calls.some(url => url.includes('/dev/architecture/story-director-audio.json')), false)
    fireEvent.click(screen.getByRole('tab', { name: 'Architecture' }))
    await screen.findByText('Architecture map')
    assert.equal(calls.filter(url => url.includes('/dev/architecture/story-director-audio.json')).length, 1)
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('architecture viewer exposes filters, keyboard-safe selection and clean source links', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { ArchitectureViewer } = await import('../src/features/architecture/ArchitectureViewer.tsx')
  ensureUiI18n()
  await setUiLanguage('en')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify(payload), { status: 200 })
  try {
    render(<ArchitectureViewer />)
    await screen.findByText('Architecture map')
    fireEvent.click(screen.getByRole('button', { name: 'Story Lab ui' }))
    assert.ok(screen.getAllByText('Story panel').length >= 1)
    assert.equal(screen.getAllByRole('link').some(link => link.getAttribute('href')?.startsWith('https://github.com/IAnMove/hocuspocus/blob/')), true)
    assert.equal(screen.queryByText(/×0/), null)
    fireEvent.change(screen.getByPlaceholderText('Search nodes'), { target: { value: 'does-not-exist' } })
    await screen.findByText('No nodes match the current filters.')
    fireEvent.change(screen.getByPlaceholderText('Search nodes'), { target: { value: '' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'api' } })
    await waitFor(() => assert.ok(screen.getAllByText('Director API').length >= 1))
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('malicious evidence cannot become an external or HTML link', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { ArchitectureViewer } = await import('../src/features/architecture/ArchitectureViewer.tsx')
  ensureUiI18n()
  await setUiLanguage('en')
  const originalFetch = globalThis.fetch
  const unsafePayload = {
    ...payload,
    nodes: [{ ...payload.nodes[0], evidence: [{ file: 'ui/src/<script>.tsx', line: 1 }] }, payload.nodes[1]],
  }
  globalThis.fetch = async () => new Response(JSON.stringify(unsafePayload), { status: 200 })
  try {
    render(<ArchitectureViewer />)
    await screen.findByText('Could not load the architecture map.')
    assert.equal(screen.queryByRole('link'), null)
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})
