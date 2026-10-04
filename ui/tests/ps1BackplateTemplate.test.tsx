import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import definition from '../../pinokio_agent/skills/api/hocuspocus/clients/ps1_backplates_template.json' with { type: 'json' }
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import type { World3DUserTemplate } from '../src/features/scene3d/userTemplates.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver, getComputedStyle: dom.window.getComputedStyle,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('imported PS1 template is selectable with its preview and missing asset hints', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DUserTemplates } = await import('../src/features/scene3d/Scene3DUserTemplates')
  const scene = parseScene3DDocument(definition.document)
  assert.ok(scene)
  const summary = { ...definition.manifest, source: 'imported', createdAt: '', updatedAt: '', media: 0,
    previewUrl: '/api/v1/templates/hocuspocus/ps1-backplates/preview' }
  const original = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (String(url).endsWith('/api/v1/templates?editor=video3d')) {
      return new Response(JSON.stringify({ templates: [summary] }), { status: 200 })
    }
    if (String(url).endsWith('/hocuspocus/ps1-backplates/apply')) {
      assert.deepEqual(JSON.parse(String(init?.body)), { workspace: 'ps1-demo' })
      return new Response(JSON.stringify({ document: definition.document, missingSlots: ['background', 'actor'], copiedMedia: [] }), { status: 200 })
    }
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch
  const applied: World3DUserTemplate[] = []
  try {
    render(<Scene3DUserTemplates document={scene} workspace="ps1-demo" disabled={false} onApply={pack => applied.push(pack)} />)
    const card = await screen.findByRole('button', { name: 'Escena estilo PS1' })
    assert.match(card.querySelector('img')?.getAttribute('src') ?? '', /\/hocuspocus\/ps1-backplates\/preview$/)
    fireEvent.click(card)
    await waitFor(() => assert.equal(applied.length, 1))
    assert.equal(applied[0].id, definition.manifest.id)
    assert.equal(applied[0].document.camera.family, 'fixed')
    assert.deepEqual(applied[0].document.slots[1].motion, scene.slots[1].motion)
    await screen.findByText(/Still to fill: background, actor/)
    assert.ok(calls.some(call => call.startsWith('POST ')))
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('native editor reopens changed background, GLB, clip and path without restoring the template defaults', () => {
  const changed = structuredClone(definition.document)
  changed.slots[0].sourceUrl = '/api/v1/file/new-station.png?workspace=ps1-demo'
  changed.slots[1].sourceUrl = '/api/v1/file/new-robot.glb?workspace=ps1-demo'
  changed.slots[1].position = [-2, 0, .5]
  changed.slots[1].motion = { to: [2, 0, -.8], faceTravel: true, easing: 'linear' }
  changed.slots[1].clip = { index: 1, name: 'Run' }
  changed.duration = 12
  const loaded = parseScene3DDocument(changed)
  assert.ok(loaded)
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(loaded)))
  assert.ok(reopened)
  assert.equal(reopened.duration, 12)
  assert.equal(reopened.camera.family, 'fixed')
  assert.equal(reopened.environment?.floorStyle, 'none')
  assert.equal(reopened.slots[0].surface, 'environment')
  assert.equal(reopened.slots[0].sourceUrl, changed.slots[0].sourceUrl)
  assert.equal(reopened.slots[1].sourceUrl, changed.slots[1].sourceUrl)
  assert.deepEqual(reopened.slots[1].clip, changed.slots[1].clip)
  assert.deepEqual(reopened.slots[1].position, changed.slots[1].position)
  assert.deepEqual(reopened.slots[1].motion, loaded.slots[1].motion)
  assert.deepEqual(reopened.slots[1].motion?.to, changed.slots[1].motion.to)
})

test('template animation speed bounds agree with the native parser', () => {
  const control = definition.manifest.controls.find(item => item.id === 'clip_speed')
  assert.ok(control)
  for (const speed of [control.min!, control.max!]) {
    const document = structuredClone(definition.document)
    document.slots[1].clipPlayback = { speed, loop: true }
    const parsed = parseScene3DDocument(document)
    assert.ok(parsed)
    assert.equal(parsed.slots[1].clipPlayback?.speed, speed)
  }
})
