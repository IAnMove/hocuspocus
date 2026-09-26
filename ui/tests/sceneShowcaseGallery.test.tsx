import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { Scene } from '../src/types/index.ts'
import { MAX_SCENE_JSON_BYTES, parseShowcaseManifest, type ShowcaseFileReference, type ShowcaseManifest } from '../src/features/sceneTemplates/showcaseManifest.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const scene = (name: string, policy: 'provided_only' | 'auto' = 'provided_only'): Scene => ({
  version: 1, name, generationPolicy: policy, width: 1280, height: 720, duration: 4,
  layers: [{ id: 'camera', type: 'camera', name: 'camera', source: '' } as Scene['layers'][number]],
})

const sceneBytes = (value: Scene) => new TextEncoder().encode(JSON.stringify(value))
const reference = (url: string, bytes: Uint8Array, sceneName?: string): ShowcaseFileReference => ({
  url, bytes: bytes.byteLength, sha256: createHash('sha256').update(bytes).digest('hex'), ...(sceneName ? { sceneName } : {}),
})

const manifestFixture = (): { manifest: ShowcaseManifest; sceneBytes: Uint8Array; shotBytes: Uint8Array } => {
  const scenePayload = scene('Stored scene snapshot')
  const shotPayload = scene('Stored exact shot')
  const sceneData = sceneBytes(scenePayload)
  const shotData = sceneBytes(shotPayload)
  const video = reference('/scene-showcase/full.mp4', new TextEncoder().encode('video'))
  const poster = reference('/scene-showcase/full.png', new TextEncoder().encode('poster'))
  return {
    sceneBytes: sceneData,
    shotBytes: shotData,
    manifest: {
      schema: 'hocuspocus.scene-showcase', version: 1,
      title: 'Showcase MiniMax', description: 'Tres outputs locales para revisión.',
      items: [
        {
          id: 'music-full', title: 'Videoclip completo', kind: 'music_video', description: 'Montaje local con planos guardados.', effects: ['paralaje', 'destello'],
          video, poster, shots: [
            { title: 'Plano de apertura', scene: reference('/scene-showcase/shot-1.json', shotData, 'Stored exact shot') },
            { title: 'Plano de cierre', scene: reference('/scene-showcase/shot-2.json', sceneData, 'Stored scene snapshot') },
          ], sourceAudio: { id: 'asset-song', filename: 'song.wav', duration: 12.5 }, imageProvider: 'minimax', imageModel: 'image-01', approval: 'pending',
        },
        {
          id: 'music-second', title: 'Segundo videoclip', kind: 'music_video', description: 'Otro vídeo completo.', effects: ['zoom'],
          video: reference('/scene-showcase/second.mp4', new TextEncoder().encode('video-2')), scene: reference('/scene-showcase/second.json', sceneData, 'Stored scene snapshot'), imageProvider: 'minimax', imageModel: 'image-01', approval: 'pending',
        },
        {
          id: 'scene-one', title: 'Escena guardada', kind: 'scene', description: 'Escena programática persistida.', effects: ['cámara'],
          video: reference('/scene-showcase/scene.mp4', new TextEncoder().encode('video-3')), poster, scene: reference('/scene-showcase/scene.json', sceneData, 'Stored scene snapshot'), imageProvider: 'minimax', imageModel: 'image-01', approval: 'pending',
        },
      ],
    },
  }
}

async function renderGallery(manifest: ShowcaseManifest, onOpenScene: (value: Scene) => void = () => undefined) {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SceneShowcaseGallery } = await import('../src/features/sceneTemplates/SceneShowcaseGallery.tsx')
  const view = render(<SceneShowcaseGallery manifest={manifest} onOpenScene={onOpenScene} />)
  return { ...view, screen, fireEvent, waitFor, cleanup }
}

test('valida el catálogo, muestra tres vídeos completos primero y mantiene un único vídeo activo', async () => {
  const { manifest } = manifestFixture()
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = (async input => { calls.push(String(input)); throw new Error('No debe descargar al renderizar la galería') }) as typeof fetch
  try {
    const view = await renderGallery(manifest)
    assert.deepEqual([...view.container.querySelectorAll('[data-showcase-id]')].map(node => node.getAttribute('data-showcase-id')), ['music-full', 'music-second', 'scene-one'])
    assert.ok(view.screen.getByText('Full music videos'))
    assert.ok(view.screen.getByText('Saved scenes'))
    assert.ok(view.screen.getByText(/On a LAN HTTP URL you can play previews/))
    assert.ok(view.screen.getByText(/Video and poster playback does not verify SHA-256/))
    assert.equal(view.container.querySelectorAll('video').length, 0)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Watch the full video of Videoclip completo' }))
    assert.equal(view.container.querySelectorAll('video').length, 1)
    assert.equal(view.container.querySelector('video')?.getAttribute('autoplay'), null)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Watch the full video of Segundo videoclip' }))
    assert.equal(view.container.querySelectorAll('video').length, 1)
    assert.match(view.container.querySelector('video')?.getAttribute('src') || '', /second\.mp4$/)
    assert.deepEqual(calls, [])
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('abre el JSON exacto tras comprobar bytes, SHA y provided_only; los planos se muestran individualmente', async () => {
  const { manifest, sceneBytes: storedBytes, shotBytes } = manifestFixture()
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  const opened: Scene[] = []
  globalThis.fetch = (async input => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith('/scene.json')) return new Response(storedBytes, { headers: { 'content-length': String(storedBytes.byteLength) } })
    if (url.endsWith('/shot-1.json')) return new Response(shotBytes)
    throw new Error(`Unexpected showcase request: ${url}`)
  }) as typeof fetch
  try {
    const view = await renderGallery(manifest, sceneValue => opened.push(sceneValue))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    await view.waitFor(() => assert.equal(opened.length, 1))
    assert.equal(opened[0].name, 'Stored scene snapshot')
    assert.equal(opened[0].generationPolicy, 'provided_only')
    assert.deepEqual(calls, ['/scene-showcase/scene.json'])

    view.fireEvent.click(view.screen.getByRole('button', { name: 'Show exact shots (2)' }))
    assert.ok(view.screen.getByText(/Shots saved individually/))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open shot 1' }))
    await view.waitFor(() => assert.equal(opened.length, 2))
    assert.equal(opened[1].name, 'Stored exact shot')
    assert.deepEqual(calls, ['/scene-showcase/scene.json', '/scene-showcase/shot-1.json'])
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('muestra hash mismatch y no abre una salida alternativa', async () => {
  const fixture = manifestFixture()
  const originalFetch = globalThis.fetch
  const opened: Scene[] = []
  const tampered = new Uint8Array(fixture.sceneBytes.byteLength).fill(0)
  globalThis.fetch = (async () => new Response(tampered)) as typeof fetch
  try {
    const view = await renderGallery(fixture.manifest, value => opened.push(value))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /SHA-256/i)
    assert.equal(opened.length, 0)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rechaza URLs remotas y IDs duplicados antes de descargar', async () => {
  const fixture = manifestFixture()
  const remote = structuredClone(fixture.manifest)
  remote.items[0].video.url = 'https://evil.example/full.mp4'
  const duplicate = structuredClone(fixture.manifest)
  duplicate.items[1].id = duplicate.items[0].id
  const originalFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = (async () => { calls += 1; throw new Error('No debe descargarse un manifest inválido') }) as typeof fetch
  try {
    assert.throws(() => parseShowcaseManifest(remote), /relative \/scene-showcase\/ URL/)
    assert.throws(() => parseShowcaseManifest(duplicate), /duplicate id/)
    const first = await renderGallery(remote)
    assert.ok(first.screen.getByRole('alert'))
    first.cleanup()
    const second = await renderGallery(duplicate)
    assert.ok(second.screen.getByRole('alert'))
    second.cleanup()
    assert.equal(calls, 0)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rechaza una escena con política distinta aunque el hash sea correcto', async () => {
  const invalidScene = scene('No generation', 'auto')
  const bytes = sceneBytes(invalidScene)
  const fixture = manifestFixture()
  const invalid = structuredClone(fixture.manifest)
  invalid.items[2].scene = reference('/scene-showcase/invalid-policy.json', bytes, 'No generation')
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response(bytes)) as typeof fetch
  try {
    const view = await renderGallery(invalid)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /provided_only/i)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('exige escena editable para escenas y videoclip con planos; el nombre semántico es obligatorio sólo en JSON', () => {
  const fixture = manifestFixture()
  const missingScene = structuredClone(fixture.manifest)
  delete missingScene.items[2].scene
  assert.throws(() => parseShowcaseManifest(missingScene), /editable JSON reference/i)

  const emptyMusicVideo = structuredClone(fixture.manifest)
  delete emptyMusicVideo.items[0].scene
  emptyMusicVideo.items[0].shots = []
  assert.throws(() => parseShowcaseManifest(emptyMusicVideo), /editable scene or at least one saved shot/i)

  const missingSceneName = structuredClone(fixture.manifest)
  delete missingSceneName.items[2].scene!.sceneName
  assert.throws(() => parseShowcaseManifest(missingSceneName), /sceneName/i)

  const oversized = structuredClone(fixture.manifest)
  oversized.items[2].scene!.bytes = MAX_SCENE_JSON_BYTES + 1
  assert.throws(() => parseShowcaseManifest(oversized), /4 MiB/i)
})

test('rechaza un JSON válido con identidad semántica distinta', async () => {
  const fixture = manifestFixture()
  const invalid = structuredClone(fixture.manifest)
  invalid.items[2].scene!.sceneName = 'Otra escena'
  const originalFetch = globalThis.fetch
  const opened: Scene[] = []
  globalThis.fetch = (async () => new Response(fixture.sceneBytes)) as typeof fetch
  try {
    const view = await renderGallery(invalid, value => opened.push(value))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /semantic identity/i)
    assert.equal(opened.length, 0)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rechaza Content-Length sobredimensionado antes de consumir el JSON', async () => {
  const fixture = manifestFixture()
  const originalFetch = globalThis.fetch
  let reads = 0
  globalThis.fetch = (async () => {
    return {
      ok: true,
      status: 200,
      url: '',
      headers: new Headers({ 'content-length': String(MAX_SCENE_JSON_BYTES + 1) }),
      body: { getReader: () => { reads += 1; throw new Error('No debe iniciar el stream') } },
      arrayBuffer: async () => { reads += 1; throw new Error('No debe leer el body') },
    } as unknown as Response
  }) as typeof fetch
  try {
    const view = await renderGallery(fixture.manifest)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /4 MiB/i)
    assert.equal(reads, 0)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rechaza un Content-Length inválido de una escena antes de leer su body', async () => {
  const fixture = manifestFixture()
  const originalFetch = globalThis.fetch
  let reads = 0
  globalThis.fetch = (async () => ({
    ok: true,
    status: 200,
    url: '',
    headers: new Headers({ 'content-length': 'no-es-un-entero' }),
    body: { getReader: () => { reads += 1; throw new Error('No debe iniciar el stream') } },
    arrayBuffer: async () => { reads += 1; throw new Error('No debe leer el body') },
  }) as unknown as Response) as typeof fetch
  try {
    const view = await renderGallery(fixture.manifest)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /Content-Length.*valid/i)
    assert.equal(reads, 0)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('corta un stream de JSON cuando los bytes observados superan 4 MiB', async () => {
  const fixture = manifestFixture()
  const originalFetch = globalThis.fetch
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(MAX_SCENE_JSON_BYTES))
      controller.enqueue(new Uint8Array(1))
      controller.close()
    },
  })
  globalThis.fetch = (async () => new Response(stream, { headers: { 'content-length': '1' } })) as typeof fetch
  try {
    const view = await renderGallery(fixture.manifest)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    const alert = await view.screen.findByRole('alert')
    assert.match(alert.textContent || '', /4 MiB/i)
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('acepta respuestas sin body stream usando el lector arrayBuffer limitado', async () => {
  const fixture = manifestFixture()
  const originalFetch = globalThis.fetch
  const response = {
    ok: true,
    status: 200,
    url: '',
    headers: new Headers(),
    body: null,
    arrayBuffer: async () => fixture.sceneBytes.buffer.slice(fixture.sceneBytes.byteOffset, fixture.sceneBytes.byteOffset + fixture.sceneBytes.byteLength),
  } as Response
  const opened: Scene[] = []
  globalThis.fetch = (async () => response) as typeof fetch
  try {
    const view = await renderGallery(fixture.manifest, value => opened.push(value))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Open scene in editor' }))
    await view.waitFor(() => assert.equal(opened.length, 1))
    assert.equal(opened[0].name, 'Stored scene snapshot')
    view.cleanup()
  } finally {
    globalThis.fetch = originalFetch
  }
})
