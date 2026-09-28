import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  File: dom.window.File, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  HTMLCanvasElement: dom.window.HTMLCanvasElement, ResizeObserver: class { observe() {} disconnect() {} },
  getComputedStyle: dom.window.getComputedStyle,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('My templates saves to the library, uses and imports after review', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DUserTemplates } = await import('../src/features/scene3d/Scene3DUserTemplates')
  const scene = applyScene3DTemplate('cafe-dance')
  const summary = (id: string, title: string) => ({ id, editor: 'video3d', title, description: '', tags: ['cafe'], author: { x: 'theinaog' },
    license: 'CC-BY-4.0', templateVersion: '1.0.0', createdAt: '', updatedAt: '', slots: [{ id: 'subject_1' }], controls: [], media: 0, source: 'user', previewUrl: null })
  let library = [] as ReturnType<typeof summary>[]
  const requests: Array<{ url: string; method: string; body?: unknown }> = []
  const original = globalThis.fetch
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body
    requests.push({ url: String(url), method, body })
    const reply = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
    if (method === 'GET') return reply({ templates: library })
    if (url.endsWith('/api/v1/templates')) { library = [summary('theinaog/harbor-cafe', body.title)]; return reply(library[0]) }
    if (url.endsWith('/apply')) return reply({ document: scene, missingSlots: ['subject_1'], copiedMedia: [] })
    if (url.endsWith('/preflight')) return reply({ canImport: true, exists: false, template: { ...summary('ana/dock', 'Imported dock'), controls: [] }, media: [], issues: [] })
    if (url.includes('/import')) { library = [...library, summary('ana/dock', 'Imported dock')]; return reply(library.at(-1)) }
    if (method === 'DELETE') { library = library.filter(item => !url.endsWith(item.id)); return reply({ deleted: true }) }
    return new Response('{}', { status: 404 })
  }) as typeof fetch
  const applied: string[] = []
  try {
    render(<Scene3DUserTemplates document={scene} workspace="demo" disabled={false} onApply={pack => { applied.push(pack.id) }} />)
    await screen.findByText(/No templates yet/)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Harbor cafe' } })
    fireEvent.change(screen.getByLabelText('X handle'), { target: { value: '@theinaog' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save template' }))
    await screen.findByRole('button', { name: 'Harbor cafe' })
    const saved = requests.find(item => item.method === 'POST' && item.url.endsWith('/api/v1/templates'))!.body as Record<string, unknown>
    assert.equal(saved.editor, 'video3d')
    assert.deepEqual(saved.author, { x: 'theinaog' })
    assert.equal((saved.controls as Array<{ pointer: string }>)[0].pointer, '/duration')
    fireEvent.click(screen.getByRole('button', { name: 'Harbor cafe' }))
    await waitFor(() => assert.deepEqual(applied, ['theinaog/harbor-cafe']))
    await screen.findByText(/Still to fill: subject_1/)
    const file = new File(['PK'], 'dock.hptemplate', { type: 'application/zip' })
    fireEvent.change(screen.getByLabelText('.hptemplate file'), { target: { files: [file] } })
    await screen.findByText(/Imported dock/)
    fireEvent.click(screen.getByRole('button', { name: 'Import this template' }))
    await screen.findByRole('button', { name: 'Imported dock' })
    assert.ok(screen.getByRole('button', { name: 'Delete Imported dock' }))
    assert.match(screen.getAllByRole('link', { name: 'Download' })[0].getAttribute('href') ?? '', /\/api\/v1\/templates\/theinaog\/harbor-cafe\/package$/)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})
