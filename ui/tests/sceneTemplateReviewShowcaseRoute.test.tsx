import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import React from 'react'
import { JSDOM, VirtualConsole } from 'jsdom'
import type { Scene } from '../src/types/index.ts'
import type { ShowcaseFileReference, ShowcaseManifest } from '../src/features/sceneTemplates/showcaseManifest.ts'
import { PENDING_SCENE_KEY } from '../src/lib/sceneOutput.ts'

const virtualConsole = new VirtualConsole()
virtualConsole.forwardTo(console, { jsdomErrors: 'none' })
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/scene-template-review', virtualConsole })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  sessionStorage: dom.window.sessionStorage,
  localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const routePath = '/scene-template-review'

const scene = {
  version: 1,
  name: 'Escena de ruta showcase',
  generationPolicy: 'provided_only',
  width: 1280,
  height: 720,
  fps: 30,
  duration: 4,
  layers: [{ id: 'camera', name: 'Cámara', type: 'camera', source: '', visible: true, z: 0 }],
  narrative: { templateId: 'scene-route', variant: 'coral' },
} as unknown as Scene

const bytesOf = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))

const reference = (url: string, bytes: Uint8Array, sceneName?: string): ShowcaseFileReference => ({
  url,
  bytes: bytes.byteLength,
  sha256: createHash('sha256').update(bytes).digest('hex'),
  ...(sceneName === undefined ? {} : { sceneName }),
})

const createManifest = (): ShowcaseManifest => {
  const sceneBytes = bytesOf(scene)
  const videoBytes = new Uint8Array([0, 1, 2, 3])
  return {
    schema: 'hocuspocus.scene-showcase',
    version: 1,
    title: 'Showcase de prueba',
    description: 'Paquete local para comprobar la ruta.',
    items: [{
      id: 'scene-route',
      title: 'Escena de ruta',
      kind: 'scene',
      description: 'Una escena guardada de prueba.',
      effects: ['cámara'],
      video: reference('/scene-showcase/scene-route.mp4', videoBytes),
      scene: reference('/scene-showcase/scene-route.json', sceneBytes, scene.name),
      imageProvider: 'minimax',
      imageModel: 'image-01',
      approval: 'pending',
    }],
  }
}

const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), {
  headers: { 'content-type': 'application/json; charset=utf-8' },
})

async function renderRoute() {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { default: SceneTemplateReviewPage } = await import('../src/features/sceneTemplates/SceneTemplateReviewPage.tsx')
  const view = render(<SceneTemplateReviewPage />)
  return { ...view, screen, fireEvent, waitFor, cleanup }
}

function resetRoute() {
  window.history.replaceState({}, '', routePath)
  window.sessionStorage.clear()
  window.localStorage.clear()
}

test('mantiene la ruta original y vuelve a la galería coral cuando el paquete no existe', { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch
  let requested = false
  resetRoute()
  globalThis.fetch = (async input => {
    assert.equal(String(input), '/scene-showcase/manifest.json')
    requested = true
    return new Response('', { status: 404 })
  }) as typeof fetch
  try {
    const view = await renderRoute()
    await view.waitFor(() => assert.equal(requested, true))
    assert.ok(view.screen.getByRole('heading', { name: 'Reusable programmatic scenes' }))
    assert.equal(view.screen.queryByText('Showcase local'), null)
    assert.equal(window.location.pathname, routePath)
    assert.equal(view.screen.getByRole('link', { name: /Candidate scene lab/ }).getAttribute('href'), routePath)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('trata el index.html de una SPA como showcase ausente, sin ocultar un manifest JSON hostil', { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch
  let requested = false
  resetRoute()
  globalThis.fetch = (async input => {
    assert.equal(String(input), '/scene-showcase/manifest.json')
    requested = true
    return new Response('<!doctype html><title>HocusPocus</title>', {
      status: 200,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    })
  }) as typeof fetch
  try {
    const view = await renderRoute()
    await view.waitFor(() => assert.equal(requested, true))
    await view.waitFor(() => assert.equal(view.screen.queryByRole('alert'), null))
    assert.ok(view.screen.getByRole('heading', { name: 'Reusable programmatic scenes' }))
    assert.equal(view.screen.queryByText('Showcase local'), null)
    assert.equal(window.location.pathname, routePath)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('muestra un manifest hostil como error visible y conserva las referencias originales', { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch
  let calls = 0
  const hostile = createManifest()
  hostile.items[0].video.url = 'https://evil.example/scene-route.mp4'
  resetRoute()
  globalThis.fetch = (async input => {
    calls += 1
    assert.equal(String(input), '/scene-showcase/manifest.json')
    return jsonResponse(hostile)
  }) as typeof fetch
  try {
    const view = await renderRoute()
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /relative \/scene-showcase\/ URL/i)
    assert.ok(view.screen.getByRole('heading', { name: 'Reusable programmatic scenes' }))
    assert.equal(view.screen.queryByText('Showcase local'), null)
    assert.equal(calls, 1)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('comprueba SHA y transfiere la escena exacta al editor por el handoff versionado', { concurrency: false }, async () => {
  const originalFetch = globalThis.fetch
  const manifest = createManifest()
  const sceneBytes = bytesOf(scene)
  const calls: string[] = []
  resetRoute()
  globalThis.fetch = (async input => {
    const url = String(input)
    calls.push(url)
    if (url === '/scene-showcase/manifest.json') return jsonResponse(manifest)
    if (url === '/scene-showcase/scene-route.json') {
      return new Response(sceneBytes, {
        headers: {
          'content-type': 'application/json',
          'content-length': String(sceneBytes.byteLength),
        },
      })
    }
    throw new Error(`Unexpected route request: ${url}`)
  }) as typeof fetch
  try {
    const view = await renderRoute()
    const open = await view.screen.findByRole('button', { name: 'Open scene in editor' })
    view.fireEvent.click(open)
    await view.waitFor(() => {
      const pending = window.sessionStorage.getItem(PENDING_SCENE_KEY)
      assert.ok(pending)
      const transferred = JSON.parse(pending) as Scene
      assert.equal(transferred.name, scene.name)
      assert.equal(transferred.generationPolicy, 'provided_only')
      assert.equal(transferred.narrative?.templateId, scene.narrative?.templateId)
    })
    assert.deepEqual(calls, ['/scene-showcase/manifest.json', '/scene-showcase/scene-route.json'])
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})
