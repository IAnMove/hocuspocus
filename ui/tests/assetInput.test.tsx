import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('crop coordinates are bounded original pixels, including reversed and outside drags', async () => {
  const { clampCrop, cropFromPoints } = await import('../src/lib/imageCrop')
  assert.deepEqual(clampCrop({ x: 95, y: -20, width: 40, height: 0 }, 100, 80), { x: 95, y: 0, width: 5, height: 1 })
  assert.deepEqual(cropFromPoints({ x: 80, y: 60 }, { x: 20, y: 10 }, 100, 80), { x: 20, y: 10, width: 60, height: 50 })
  assert.deepEqual(cropFromPoints({ x: 20, y: 10 }, { x: -100, y: 300 }, 100, 80), { x: 0, y: 10, width: 20, height: 70 })
})

test('input thumbnails use upload scope or original source workspace, not full resolution', async () => {
  const { inputThumbnailSource } = await import('../src/lib/inputImageThumbnail')
  const item = { name: 'pic.png', type: 'image' as const, mode: null, size: 1, created_at: 1, workspace_id: 'current', url: '/api/v1/uploads/crop.png' }
  assert.match(inputThumbnailSource(item), /crop.png\?workspace=__uploads__&size=sm/)
  assert.match(inputThumbnailSource({ ...item, url: '/api/v1/file/pic.png?workspace=old' }), /workspace=old&size=sm/)
})

test('saving a crop uploads a copy and does not modify the source or reuse its asset ID', async () => {
  const { saveCroppedImage } = await import('../src/lib/imageCrop')
  const original = globalThis.fetch
  const requests: string[] = []
  globalThis.fetch = async (url, init) => {
    requests.push(`${init?.method} ${url}`)
    assert.ok(init?.body instanceof FormData)
    return Response.json({ filename: 'new-crop.png', path: '/uploads/new-crop.png', url: '/api/v1/uploads/new-crop.png' })
  }
  try {
    const saved = await saveCroppedImage(new File(['crop'], 'crop.png', { type: 'image/png' }))
    assert.deepEqual(requests, ['POST /api/v1/upload'])
    assert.equal(saved.url, '/api/v1/uploads/new-crop.png')
    assert.equal(saved.workspace_id, '__uploads__')
    assert.equal(saved.asset_id, undefined)
    assert.match(saved.thumbnail_url!, /size=sm/)
  } finally { globalThis.fetch = original }
})

test('inferUploadKind maps image audio video and glb', async () => {
  const { inferUploadKind } = await import('../src/features/asset-picker/upload.ts')
  assert.equal(inferUploadKind(new File(['x'], 'a.png', { type: 'image/png' })), 'image')
  assert.equal(inferUploadKind(new File(['x'], 'a.mp3', { type: 'audio/mpeg' })), 'audio')
  assert.equal(inferUploadKind(new File(['x'], 'a.mp4', { type: 'video/mp4' })), 'video')
  assert.equal(inferUploadKind(new File(['x'], 'hero.glb', { type: 'model/gltf-binary' })), 'model3d')
})

test('a crop finishing after input replacement never overwrites the new selection', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ImageCropButton } = await import('../src/components/common/ImageCropButton')
  const originalImage = globalThis.Image, originalFetch = globalThis.fetch
  const originalContext = dom.window.HTMLCanvasElement.prototype.getContext
  const originalBlob = dom.window.HTMLCanvasElement.prototype.toBlob
  let finish: (response: Response) => void = () => {}
  let uploaded = false, replaced = false
  globalThis.Image = class { src = ''; naturalWidth = 100; naturalHeight = 80; decode = async () => {} } as unknown as typeof Image
  dom.window.HTMLCanvasElement.prototype.getContext = (() => ({ drawImage() {} })) as never
  dom.window.HTMLCanvasElement.prototype.toBlob = callback => callback(new Blob(['crop'], { type: 'image/png' }))
  globalThis.fetch = async () => { uploaded = true; return new Promise<Response>(resolve => { finish = resolve }) }
  const item = { name: 'original.png', type: 'image' as const, mode: null, size: 100, created_at: 1, url: '/api/v1/file/original.png' }
  try {
    const view = render(<ImageCropButton key={item.url} item={item} onReplace={() => { replaced = true }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Edit original.png' }))
    await screen.findByRole('dialog', { name: 'Crop image' })
    await waitFor(() => assert.equal((screen.getByRole('button', { name: 'Save crop' }) as HTMLButtonElement).disabled, false))
    fireEvent.click(screen.getByRole('button', { name: 'Save crop' }))
    await waitFor(() => assert.equal(uploaded, true))
    view.rerender(<ImageCropButton key="new" item={{ ...item, url: '/api/v1/file/new.png' }} onReplace={() => { replaced = true }} />)
    finish(Response.json({ filename: 'copy.png', url: '/api/v1/uploads/copy.png', path: '/uploads/copy.png' }))
    await new Promise(resolve => setTimeout(resolve, 0))
    assert.equal(replaced, false)
  } finally {
    cleanup(); globalThis.Image = originalImage; globalThis.fetch = originalFetch
    dom.window.HTMLCanvasElement.prototype.getContext = originalContext
    dom.window.HTMLCanvasElement.prototype.toBlob = originalBlob
  }
})

test('native file cancel does not change the field', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetInput } = await import('../src/features/asset-picker/AssetInput.tsx')
  const chosen: Array<string | null> = []
  try {
    render(
      <AssetInput
        label="Hero"
        placeholder="Choose"
        items={[]}
        onChoose={item => { chosen.push(item ? item.name : null) }}
      />,
    )
    fireEvent.change(screen.getByTestId('asset-input-file'), { target: { files: [] } })
    assert.deepEqual(chosen, [])
    assert.equal(screen.queryByTestId('asset-explorer'), null)
  } finally {
    cleanup()
  }
})

test('From HocusPocus opens the shared explorer and Remove clears', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetInput } = await import('../src/features/asset-picker/AssetInput.tsx')
  const chosen: Array<string | null> = []
  const current = {
    name: 'hero.png', type: 'image' as const, mode: null, size: 2, created_at: 1,
    url: '/api/v1/file/hero.png', thumbnail_url: '/api/v1/file/hero.png',
  }
  try {
    render(
      <AssetInput
        label="Hero"
        placeholder="Choose"
        items={[current]}
        value={current}
        optional
        onChoose={item => { chosen.push(item ? item.name : null) }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /From HocusPocus/ }))
    assert.ok(await screen.findByTestId('asset-explorer'))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    assert.deepEqual(chosen, [])
    fireEvent.click(screen.getByRole('button', { name: /Remove/ }))
    assert.deepEqual(chosen, [null])
  } finally {
    cleanup()
  }
})

test('local pick posts upload once', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetInput } = await import('../src/features/asset-picker/AssetInput.tsx')
  const originalFetch = globalThis.fetch
  const posts: string[] = []
  globalThis.fetch = (async (input, init) => {
    const url = typeof input === 'string' ? input : (input as Request).url || String(input)
    if ((init?.method || 'GET').toUpperCase() === 'POST') posts.push(url)
    return new Response(JSON.stringify({ filename: 'hero.png', url: '/api/v1/uploads/hero.png', path: 'uploads/hero.png' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch
  const chosen: Array<{ name: string; path?: string; asset_id?: string }> = []
  try {
    render(
      <AssetInput
        label="Hero"
        placeholder="Choose"
        items={[]}
        workspaceId="default"
        constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
        onChoose={item => { if (item) chosen.push({ name: item.name, path: item.path, asset_id: item.asset_id }) }}
      />,
    )
    fireEvent.change(screen.getByTestId('asset-input-file'), {
      target: { files: [new File(['x'], 'hero.png', { type: 'image/png' })] },
    })
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.equal(posts.length, 1)
    assert.equal(chosen.length, 1)
    assert.equal(chosen[0].name, 'hero.png')
    assert.equal(chosen[0].path, 'uploads/hero.png')
    assert.equal(chosen[0].asset_id, undefined)
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('incompatible drop does not upload', { concurrency: false }, async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetInput } = await import('../src/features/asset-picker/AssetInput.tsx')
  const originalFetch = globalThis.fetch
  let posts = 0
  globalThis.fetch = (async () => {
    posts += 1
    return new Response('{}', { status: 200 })
  }) as typeof fetch
  const chosen: string[] = []
  try {
    const { container } = render(
      <AssetInput
        label="Hero"
        placeholder="Choose"
        items={[]}
        constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
        onChoose={item => { if (item) chosen.push(item.name) }}
      />,
    )
    const audio = new File(['x'], 'voice.wav', { type: 'audio/wav' })
    fireEvent.drop(container.firstChild as Element, { dataTransfer: { files: [audio] } })
    await new Promise(resolve => setTimeout(resolve, 10))
    assert.equal(posts, 0)
    assert.deepEqual(chosen, [])
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('failed upload after the field closed does not apply a value', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AssetInput } = await import('../src/features/asset-picker/AssetInput.tsx')
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response('nope', { status: 500 })) as typeof fetch
  const chosen: Array<string | null> = []
  try {
    const view = render(
      <AssetInput
        label="Hero"
        placeholder="Choose"
        items={[]}
        onChoose={item => { chosen.push(item ? item.name : null) }}
      />,
    )
    const file = new File(['x'], 'late.png', { type: 'image/png' })
    fireEvent.change(screen.getByTestId('asset-input-file'), { target: { files: [file] } })
    view.unmount()
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.deepEqual(chosen, [])
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})
