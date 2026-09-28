import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  getComputedStyle: dom.window.getComputedStyle,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('community tab lists the index and installs a template', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { CommunityTemplates } = await import('../src/features/templates/CommunityTemplates')
  const entry = { id: 'ana/rocket', editor: 'video3d', title: 'Rocket launch', description: 'Pad at dawn', tags: ['space'], author: { x: 'ana' },
    license: 'CC0-1.0', templateVersion: '1.0.0', slots: 2, controls: 1, media: 0, bytes: 20480, preview: null }
  let state = 'available'
  const calls: string[] = []
  const original = globalThis.fetch
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (String(url).includes('/install')) { state = 'installed'; return new Response(JSON.stringify({ id: entry.id }), { status: 200 }) }
    return new Response(JSON.stringify({ url: 'x', updatedAt: '', templates: [{ ...entry, state }] }), { status: 200 })
  }) as typeof fetch
  let installed = 0
  try {
    render(<CommunityTemplates editor="video3d" onInstalled={() => { installed++ }} />)
    await screen.findByText('Rocket launch')
    assert.match(screen.getByText(/@ana/).textContent ?? '', /CC0-1\.0 · 2 slots · 20 KB/)
    fireEvent.click(screen.getByRole('button', { name: 'Install' }))
    await screen.findByText('Installed')
    assert.equal(installed, 1)
    assert.ok(calls.some(call => call.startsWith('POST') && call.endsWith('/api/v1/templates/community/install')))
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('share opens the pre-filled community submission form', async () => {
  const { communitySubmitUrl } = await import('../src/features/templates/templateForm')
  const url = new URL(communitySubmitUrl({ title: 'Mars at dusk', description: 'Two moons', tags: ['space', 'mars'], license: 'CC-BY-4.0' }))
  assert.equal(url.origin + url.pathname, 'https://github.com/IAnMove/hocuspocus-community/issues/new')
  assert.equal(url.searchParams.get('template'), 'submit-template.yml')
  assert.equal(url.searchParams.get('template_title'), 'Mars at dusk')
  assert.equal(url.searchParams.get('tags'), 'space, mars')
  assert.equal(url.searchParams.get('license'), 'CC-BY-4.0')
})
