import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver, ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const reply = (result: unknown) => json({ version: 1, operation: 'model3d.real', status: 'completed', result })

const presets = {
  outfits: [{ id: 'suit', gender: 'any', label: { es: 'Traje', en: 'Suit' }, prompt: 'A grey suit.' }],
  faces: [{ id: 'old-man', gender: 'man', label: { es: 'Señor mayor', en: 'Older man' }, prompt: 'A grey-haired man.' },
          { id: 'red-bun', gender: 'woman', label: { es: 'Pelirroja', en: 'Red hair' }, prompt: 'A woman with red hair in a bun.' }],
}
const marta = { name: 'Marta', slug: 'marta', gender: 'woman', outfit_prompt: 'A green jacket.', face_prompt: 'Red hair.', seed: 11, kit_id: 'real-marta',
  rigged_file: 'blob-Marta-1-rigged.glb', face_url: '/api/v1/file/real-marta-face-1.png?workspace=w', missing: false }
const done = {
  jobId: 'real-2', name: 'Marta', status: 'completed', stage: 'done',
  steps: [{ id: 'guides', status: 'done' }, { id: 'body', status: 'done' }, { id: 'head', status: 'reused' }, { id: 'character', status: 'done' }, { id: 'kit', status: 'reused' }],
  result: { file: 'blob-Marta-2.glb', rigged_file: 'blob-Marta-2-rigged.glb', rigged_url: '/api/v1/file/blob-Marta-2-rigged.glb?workspace=w', kit_id: 'real-marta',
    preview: '/api/v1/file/real-marta-face-1.png?workspace=w', reused: ['head', 'kit'], recipe: { name: 'Marta', slug: 'marta', input: {}, kit_id: 'real-marta' },
    warnings: [{ code: 'relief_skipped', message: 'The face relief was skipped.' }] },
}

test('Studio 3D › Realista (PS2) reopens a saved character, changes its clothes and shows the job, the result and its warnings', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { RealCharacterPanel } = await import('../src/components/Sidebar/RealCharacterPanel.tsx')
  const posts: Array<{ url: string; body: Record<string, unknown> }> = []
  const refreshed: unknown[] = []
  const original = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const body = JSON.parse(String(init?.body ?? '{}'))
    posts.push({ url, body })
    if (url.endsWith('/presets')) return reply(presets)
    if (url.endsWith('/list')) return reply({ characters: [marta] })
    if (url.endsWith('/get')) return reply({ name: 'Marta', slug: 'marta', kit_id: 'real-marta', input: { gender: 'woman', outfit_prompt: 'A green jacket.', face_prompt: 'Red hair.', seed: 11 } })
    if (url.endsWith('/api/v1/model3d/real')) return reply(done)
    return json({ detail: { code: 'not_found', message: 'nothing' } }, 404)
  }) as typeof fetch
  useStore.setState({ activeWorkspace: 'w', setMediaFilter: () => undefined, maybeRefreshGallery: async (options: unknown) => { refreshed.push(options) } } as never)
  try {
    render(<RealCharacterPanel />)
    const row = await waitFor(() => screen.getByTestId('real-saved-marta'))
    fireEvent.click(row.querySelector('button')!)
    const textareas = () => [...document.querySelectorAll('textarea')] as HTMLTextAreaElement[]
    await waitFor(() => assert.equal(textareas()[1].value, 'Red hair.'))
    assert.equal(textareas()[0].value, 'A green jacket.')
    assert.equal((screen.getByDisplayValue('11') as HTMLInputElement).value, '11', 'the stored seed comes back so the face is not repainted')
    const faceOptions = [...(document.querySelectorAll('select')[2] as HTMLSelectElement).options].map(option => option.value)
    assert.deepEqual(faceOptions, ['', 'red-bun'], 'the quick faces follow the gender')
    fireEvent.change(document.querySelectorAll('select')[1], { target: { value: 'suit' } })
    assert.equal(textareas()[0].value, 'A grey suit.')
    fireEvent.click(screen.getByRole('button', { name: /Crear o rehacer|Make or remake/ }))
    await waitFor(() => assert.ok(screen.getByTestId('real-result')))
    const made = posts.find(item => item.url.endsWith('/api/v1/model3d/real'))!
    assert.equal(made.body.version, 1)
    assert.ok(made.body.intent_id)
    assert.deepEqual(made.body.input, { workspace: 'w', name: 'Marta', gender: 'woman', outfit_prompt: 'A grey suit.', face_prompt: 'Red hair.', seed: 11 })
    assert.match(screen.getByTestId('real-step-head').textContent!, /reaprovechado|reused/)
    assert.match(screen.getByTestId('real-result').textContent!, /relief_skipped: The face relief was skipped\./)
    assert.match(screen.getByTestId('real-result').textContent!, /blob-Marta-2-rigged\.glb/)
    assert.equal(refreshed.length, 1, 'the 3D gallery is refreshed when the character is ready')
    assert.ok(posts.filter(item => item.url.endsWith('/list')).length >= 2, 'the saved list is read again after the make')
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})
