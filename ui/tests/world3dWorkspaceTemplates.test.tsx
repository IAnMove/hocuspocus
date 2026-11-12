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
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('a video export reopens the Video 2D or Video 3D scene saved in its sidecar', async () => {
  const { exportedSceneKind } = await import('../src/lib/exportedScene.ts')
  assert.equal(exportedSceneKind({ scene_recipe: { engine: 'world3d', document: { slots: [] } } }), '3d')
  assert.equal(exportedSceneKind({ scene_recipe: { engine: 'video2d', refs: [] }, scene: { version: 1, layers: [] } }), '2d')
  assert.equal(exportedSceneKind({ scene_recipe: { engine: 'video2d' } }), null)
  assert.equal(exportedSceneKind({ prompt: 'a cat' }), null)
  assert.equal(exportedSceneKind(null), null)
})

test('workspace template ids are not built-in shots, so the editor does not try to build them', async () => {
  const { isBuiltinScene3DTemplate } = await import('../src/features/scene3d/templateCatalog.ts')
  assert.equal(isBuiltinScene3DTemplate('two-shot'), true)
  assert.equal(isBuiltinScene3DTemplate('user-pu3d-flota'), false)
})

test('the shot card names a scene built from a workspace template instead of a missing translation', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { Scene3DShotLibraryCard } = await import('../src/features/scene3d/Scene3DShotLibraryCard.tsx')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates.ts')
  const document = { ...applyScene3DTemplate('two-shot'), templateId: 'user-pu3d-flota' as never }
  try {
    render(<Scene3DShotLibraryCard document={document} applyDisabled={false} editingLocked={false} keepAssets
      onKeepAssets={() => undefined} onTemplate={() => undefined} onUserTemplate={() => undefined} />)
    assert.ok(screen.getByText(/user-pu3d-flota/))
    assert.equal(screen.queryByText(/template\.user-pu3d-flota\.title/), null)
    assert.equal(document.templateId, 'user-pu3d-flota')
  } finally {
    cleanup()
  }
})

test('templates an agent saved in the workspace are listed and open as an editable pack', async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates.ts')
  const { Scene3DWorkspaceTemplates } = await import('../src/features/scene3d/Scene3DWorkspaceTemplates.tsx')
  const stored = { ...applyScene3DTemplate('two-shot'), duration: 6 }
  const requests: string[] = []
  const realFetch = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    requests.push(url)
    if (url.includes('/workspace/user-agent-duelo')) {
      return new Response(JSON.stringify({ template: { id: 'user-agent-duelo', title: 'Duelo', document: stored } }), { status: 200 })
    }
    return new Response(JSON.stringify({ templates: [{
      id: 'user-agent-duelo', title: 'Duelo', description: 'Made by an agent', createdBy: 'agent', updatedAt: '2026-10-06T10:00:00Z',
      duration: 6, width: 1920, height: 1080, format: 'landscape', slots: 3, pending: 1,
    }] }), { status: 200 })
  }) as typeof fetch
  const applied: Array<{ id: string; title: string; duration: number }> = []
  try {
    render(<Scene3DWorkspaceTemplates workspace="plus-ultra" disabled={false}
      onApply={pack => applied.push({ id: pack.id, title: pack.title, duration: pack.document.duration })} />)
    const card = await screen.findByTestId('world3d-workspace-template-user-agent-duelo')
    assert.match(card.textContent || '', /Duelo/)
    assert.ok(card.textContent?.includes('Made by an agent'))
    fireEvent.click(card)
    await waitFor(() => assert.equal(applied.length, 1))
    assert.deepEqual(applied[0], { id: 'user-agent-duelo', title: 'Duelo', duration: 6 })
    assert.ok(requests[0].includes('/api/v1/world3d/templates/workspace?workspace=plus-ultra'))
  } finally {
    globalThis.fetch = realFetch
    cleanup()
  }
})

test('a workspace with no personal templates adds nothing to My templates', async () => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { Scene3DWorkspaceTemplates } = await import('../src/features/scene3d/Scene3DWorkspaceTemplates.tsx')
  const realFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => { calls += 1; return new Response(JSON.stringify({ templates: [] }), { status: 200 }) }) as typeof fetch
  try {
    const { container } = render(<Scene3DWorkspaceTemplates workspace="empty" disabled={false} onApply={() => undefined} />)
    await waitFor(() => assert.equal(calls, 1))
    await waitFor(() => assert.equal(container.querySelector('[data-testid="world3d-workspace-templates"]'), null))
  } finally {
    globalThis.fetch = realFetch
    cleanup()
  }
})
