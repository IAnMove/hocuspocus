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
