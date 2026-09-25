import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
const { ensureUiI18n } = await import('../src/i18n/index.ts')
await ensureUiI18n().changeLanguage('en')

test('image previews retain one local URL, open without replacing the source and return focus', async () => {
  const { LocalImagePreview } = await import('../src/components/common/ImagePreview.tsx')
  const originalCreate = URL.createObjectURL
  const originalRevoke = URL.revokeObjectURL
  const revoked: string[] = []
  let created = 0
  URL.createObjectURL = () => `blob:preview-${++created}`
  URL.revokeObjectURL = url => { revoked.push(url) }
  try {
    const file = new File(['sample'], 'sample.png', { type: 'image/png' })
    const view = render(<LocalImagePreview file={file} label="Source" />)
    view.rerender(<LocalImagePreview file={file} label="Source" />)
    assert.equal(created, 1)
    const button = screen.getByRole('button', { name: 'Enlarge sample.png' })
    button.focus()
    fireEvent.click(button)
    const dialog = await screen.findByRole('dialog', { name: 'Image details' })
    const img = dialog.querySelector('img')!
    Object.defineProperties(img, { naturalWidth: { value: 320 }, naturalHeight: { value: 180 } })
    fireEvent.load(img)
    assert.ok(screen.getByText('320 × 180'))
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => assert.equal(screen.queryByRole('dialog'), null))
    assert.equal(document.activeElement, button)
    assert.equal(created, 1)
    view.unmount()
    assert.deepEqual(revoked, ['blob:preview-1'])
  } finally { cleanup(); URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke }
})

test('gallery preview fetches metadata from the image workspace only when opened', async () => {
  const { FeedMediaBody } = await import('../src/components/MainContent/FeedMediaBody.tsx')
  const originalFetch = globalThis.fetch
  const requests: string[] = []
  globalThis.fetch = async input => { requests.push(String(input)); return new Response(JSON.stringify({ source: 'sidecar', params: { prompt: 'A green ceramic vase', seed: 7, model_type: 'qwen_image_21' } })) }
  try {
    const file = { name: 'vase.png', url: '/api/v1/file/vase.png', type: 'image' as const, mode: 'image' as const, size: 1024, created_at: 1, favorite: false }
    render(<FeedMediaBody file={file} workspace="art" isActive videoReady={false} videoRef={{ current: null }} onPlay={() => {}} onIntrinsicSize={() => {}} onImageLoad={() => {}}
      isScene={false} isComic={false} isModel3d={false} canPreviewModel3d={false} isRigged={false} riggedClips={[]} activeClip={null} setActiveClip={() => {}}
      retryImage={url => <img src={url} alt="Gallery image" />} />)
    assert.equal(requests.length, 0)
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge vase.png' }))
    await screen.findByText('A green ceramic vase')
    assert.deepEqual(requests, ['/api/v1/outputs/vase.png/metadata?workspace=art'])
    assert.ok(screen.getByText('All saved information'))
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('Activity reference thumbnails retain server identity, fall back and enlarge', async () => {
  const { ActivityReferenceImages } = await import('../src/features/activity/ActivityReferenceImages.tsx')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ source: 'none', params: null }))
  try {
    render(<ActivityReferenceImages task={{ id: 'task', status: 'running', metadata: { reference_images: [
      { name: 'ref.png', url: '/api/v1/uploads/ref.png', thumbnail_url: '/api/v1/outputs/thumbnail/ref.png?workspace=__uploads__' },
      { url: 'https://example.com/private.png' },
    ] } } as never} />)
    assert.equal(screen.getAllByRole('img').length, 1)
    const img = screen.getByRole('img', { name: 'Reference 1' })
    fireEvent.error(img)
    assert.equal(img.getAttribute('src'), '/api/v1/uploads/ref.png')
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge ref.png' }))
    const dialog = await screen.findByRole('dialog')
    assert.equal(dialog.querySelector('img')?.getAttribute('src'), '/api/v1/uploads/ref.png')
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('metadata source none has an explicit empty state without an empty JSON inspector', async () => {
  const { ImagePreview } = await import('../src/components/common/ImagePreview.tsx')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ source: 'none', params: null }))
  try {
    render(<ImagePreview image={{ name: 'imported.png', url: '/api/v1/uploads/imported.png' }}>Thumbnail</ImagePreview>)
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge imported.png' }))
    await screen.findByText('No generation metadata is available for this file.')
    assert.equal(screen.queryByText('All saved information'), null)
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('video preview retains URL workspace identity, metadata and explicit playback controls', async () => {
  const { ImagePreview } = await import('../src/components/common/ImagePreview.tsx')
  const originalFetch = globalThis.fetch
  const requests: string[] = []
  const literalPrompt = 'A "blue" bird\nKeep this line exactly.'
  globalThis.fetch = async input => {
    requests.push(String(input))
    return new Response(JSON.stringify({ source: 'sidecar', params: { prompt: literalPrompt, negative_prompt: 'No text', model_type: 'wan', seed: 0, num_inference_steps: 20, guidance_scale: 3, resolution: '1280x720' }, generation_time: 75, job_id: 'saved-job' }))
  }
  try {
    let opened = 0
    let currentTime = 4
    const url = '/api/v1/file/clip.mp4?workspace=original%20folder'
    render(<ImagePreview image={{ name: 'clip.mp4', url, workspace_id: 'selected-folder', type: 'video', thumbnail_url: '/poster.jpg' }} onOpen={() => { opened++ }}
      videoTime={currentTime} onVideoTimeChange={time => { currentTime = time }}>Video thumbnail</ImagePreview>)
    assert.equal(requests.length, 0)
    const button = screen.getByRole('button', { name: 'Open video clip.mp4' })
    button.focus()
    fireEvent.click(button)
    const dialog = await screen.findByRole('dialog', { name: 'Video details' })
    await screen.findByText('No text')
    assert.equal(opened, 1)
    assert.deepEqual(requests, ['/api/v1/outputs/clip.mp4/metadata?workspace=original%20folder'])
    const video = dialog.querySelector('video')!
    assert.ok(video)
    assert.equal(video.getAttribute('src'), url)
    assert.equal(video.getAttribute('poster'), '/poster.jpg')
    assert.equal(video.controls, true)
    assert.equal(video.playsInline, true)
    assert.equal(video.preload, 'metadata')
    assert.equal(video.autoplay, false)
    assert.equal(dialog.querySelector('img'), null)
    assert.equal(screen.getByRole('link', { name: 'Download video' }).getAttribute('href'), url)
    Object.defineProperties(video, { videoWidth: { value: 1280 }, videoHeight: { value: 720 }, duration: { value: 12 } })
    fireEvent.loadedMetadata(video)
    assert.equal(video.currentTime, 4)
    video.currentTime = 7
    fireEvent.timeUpdate(video)
    assert.equal(currentTime, 7)
    assert.ok(screen.getByText('1280 × 720'))
    assert.ok(screen.getByText('12s'))
    assert.ok(screen.getByText('1m 15s'))
    assert.ok(Array.from(dialog.querySelectorAll('dd')).some(value => value.textContent === literalPrompt))
    assert.ok(screen.getByText('saved-job'))
    const summary = dialog.querySelector('summary')!
    summary.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    assert.equal(document.activeElement?.getAttribute('aria-label'), 'Download video')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => assert.equal(screen.queryByRole('dialog'), null))
    assert.ok(document.activeElement === button)
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('HTTP metadata failures show a retry action and recover without reloading the media', async () => {
  const { ImagePreview } = await import('../src/components/common/ImagePreview.tsx')
  const originalFetch = globalThis.fetch
  const originalWarn = console.warn
  let requests = 0
  globalThis.fetch = async () => {
    requests++
    return requests <= 3 ? new Response('', { status: 503 }) : new Response(JSON.stringify({ source: 'sidecar', params: { prompt: 'Recovered prompt' } }))
  }
  console.warn = () => {}
  try {
    render(<ImagePreview image={{ name: 'retry.png', url: '/api/v1/file/retry.png?workspace=art' }}>Thumbnail</ImagePreview>)
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge retry.png' }))
    const dialog = await screen.findByRole('dialog')
    const img = dialog.querySelector('img')!
    const retry = await screen.findByRole('button', { name: 'Retry information' }, { timeout: 3000 })
    assert.equal(requests, 3)
    assert.equal(screen.queryByText('No generation metadata is available for this file.'), null)
    fireEvent.click(retry)
    await screen.findByText('Recovered prompt')
    assert.equal(requests, 4)
    assert.ok(dialog.querySelector('img') === img)
    assert.equal(screen.queryByRole('alert'), null)
  } finally { cleanup(); globalThis.fetch = originalFetch; console.warn = originalWarn }
})

test('media retry preserves the workspace and download URL after a failed load', async () => {
  const { ImagePreview } = await import('../src/components/common/ImagePreview.tsx')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ source: 'none', params: null }))
  try {
    const url = '/api/v1/file/retry.png?workspace=art#original'
    render(<ImagePreview image={{ name: 'retry.png', url }}>Thumbnail</ImagePreview>)
    fireEvent.click(screen.getByRole('button', { name: 'Enlarge retry.png' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.error(dialog.querySelector('img')!)
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    const src = new URL(dialog.querySelector('img')!.src)
    assert.equal(src.searchParams.get('workspace'), 'art')
    assert.equal(src.searchParams.get('preview_retry'), '1')
    assert.equal(src.hash, '#original')
    assert.equal(screen.getByRole('link', { name: 'Download image' }).getAttribute('href'), url)
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('server changes offer an update without replacing the working form', async () => {
  const { RuntimeUpdateNotice } = await import('../src/components/RuntimeUpdateNotice.tsx')
  const before = { instance_id: 'a', ui_build_id: 'first' }
  const after = { instance_id: 'b', ui_build_id: 'second' }
  try {
    const view = render(<><input aria-label="Draft" defaultValue="" /><RuntimeUpdateNotice identity={before} /></>)
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Keep this edit' } })
    view.rerender(<><input aria-label="Draft" defaultValue="" /><RuntimeUpdateNotice identity={after} /></>)
    assert.ok(screen.getByRole('button', { name: 'Reload now' }))
    assert.equal(input.value, 'Keep this edit')
    fireEvent.click(screen.getByRole('button', { name: 'Later' }))
    assert.equal(screen.queryByRole('status'), null)
    view.rerender(<><input aria-label="Draft" defaultValue="" /><RuntimeUpdateNotice identity={{ ...after, ui_build_id: 'missing' }} /></>)
    assert.equal(input.value, 'Keep this edit')
    assert.equal(screen.queryByRole('status'), null)
  } finally { cleanup() }
})
