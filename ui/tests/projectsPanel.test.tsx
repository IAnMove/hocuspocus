import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('projects open on the current workspace and still offer every workspace', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ProjectsPanel } = await import('../src/features/projects/ProjectsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const urls: string[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async input => {
    urls.push(String(input))
    return { ok: true, json: async () => ({ projects: [], total: 0, warnings: [] }) } as Response
  }
  const loadWorkspaces = useStore.getState().loadWorkspaces
  useStore.setState({
    activeWorkspace: 'comic-view',
    workspaces: [{ name: 'comic-view', path: '/comic' }, { name: 'other', path: '/other' }],
    loadWorkspaces: async () => undefined,
  })
  try {
    render(<ProjectsPanel />)
    const select = screen.getByRole('combobox', { name: 'Project workspace' }) as HTMLSelectElement
    assert.equal(select.value, 'comic-view')
    assert.ok([...select.options].some(option => option.value === '' && option.textContent === 'All workspaces'))
    await waitFor(() => assert.ok(urls.some(url => url.includes('workspace=comic-view'))))

    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => assert.ok(urls.some(url => url.includes('/api/v1/projects?') && !url.includes('workspace='))))
    useStore.setState({ activeWorkspace: 'other' })
    await waitFor(() => assert.equal((screen.getByRole('combobox', { name: 'Project workspace' }) as HTMLSelectElement).value, ''))
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    useStore.setState({ activeWorkspace: 'default', workspaces: [], loadWorkspaces })
  }
})
