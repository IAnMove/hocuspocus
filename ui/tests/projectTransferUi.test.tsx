import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLAnchorElement: dom.window.HTMLAnchorElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const shot = {
  version: 1, units: 'meters', up: 'y', width: 1280, height: 720, fps: 30, duration: 4, templateId: 'two-shot',
  camera: { family: 'establishment', eye: [0, 1.6, 4.2], look: [0, 1, 0], fov: 50 },
  light: { kind: 'directional', direction: [-0.35, -1, -0.25], intensity: 1.15, color: '#fff4e5' },
  slots: [{
    id: 'subject_1', slot: 'subject_1', position: [0, 0, 0], rotationY: 0, scale: 1,
    sourceUrl: '/api/v1/file/hero.glb?workspace=film',
    sourceRef: { workspaceId: 'film', filename: 'hero.glb', url: '/api/v1/file/hero.glb?workspace=film' },
    media: 'model3d', clip: { index: 0, name: 'Idle' },
  }],
}

test('export tab lists used assets and import tab shows preflight repair picker', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { ProjectTransferDialog } = await import('../src/features/project-transfer/ProjectTransferDialog.tsx')
  const previousFetch = globalThis.fetch
  const exported: unknown[] = []
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/scene-packages/export')) {
      exported.push(JSON.parse(String(init?.body || '{}')))
      return new Response(new Blob(['PK']), { headers: { 'content-type': 'application/zip' } })
    }
    if (url.includes('/scene-packages/preflight')) {
      return Response.json({
        ok: false, canImport: false, title: 'Pair', unknownFields: ['customRendererFlag'], warnings: [],
        documents: [{ id: 'shot-1', role: 'shot', name: 'One' }],
        assets: [{ sha256: 'abc', filename: 'hero.glb', path: 'media/abc.glb', status: 'tampered' }],
        issues: [{ code: 'tampered_asset', message: 'hero.glb', repair: true, path: 'media/abc.glb' }],
      })
    }
    if (url.includes('/scene-packages/import')) {
      return Response.json({ ok: true, scenes: [{ name: 'Imported.world3d.scene.json' }], unknown_fields: ['customRendererFlag'] })
    }
    return new Response('{}', { status: 404 })
  }
  const created: string[] = []
  const originalCreate = URL.createObjectURL
  const originalRevoke = URL.revokeObjectURL
  URL.createObjectURL = () => 'blob:test'
  URL.revokeObjectURL = () => undefined
  const originalClick = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function click() { created.push(this.download) }
  try {
    render(<ProjectTransferDialog open onClose={() => undefined} workspace="film" documents={[shot, shot]} />)
    assert.ok(screen.getByRole('dialog', { name: 'Transfer project' }))
    assert.match(screen.getByText(/unique media/).textContent || '', /1 unique/)
    fireEvent.click(screen.getByRole('button', { name: 'Download scene package' }))
    await waitFor(() => assert.equal(exported.length, 1))
    fireEvent.click(screen.getByRole('button', { name: 'Import package' }))
    const input = screen.getByLabelText('Choose scene package zip') as HTMLInputElement
    const file = new File(['PK'], 'pair.scene-package.zip', { type: 'application/zip' })
    fireEvent.change(input, { target: { files: [file] } })
    await screen.findByText('Unknown fields (kept, not dropped)')
    assert.ok(screen.getByText('customRendererFlag'))
    assert.ok(screen.getByText(/Tampered: hero.glb/))
    assert.ok(screen.getByRole('button', { name: 'Import into this workspace' }).hasAttribute('disabled'))
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    URL.createObjectURL = originalCreate
    URL.revokeObjectURL = originalRevoke
    HTMLAnchorElement.prototype.click = originalClick
  }
})
