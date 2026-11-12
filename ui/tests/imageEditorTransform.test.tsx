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

test('rotating and undoing in the image editor moves the selected area and revokes the temporary picture', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ImageCropButton } = await import('../src/components/common/ImageCropButton')
  const originalImage = globalThis.Image
  const originalContext = dom.window.HTMLCanvasElement.prototype.getContext
  const originalBlob = dom.window.HTMLCanvasElement.prototype.toBlob
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL
  const created: string[] = [], revoked: string[] = []
  // A picture loaded from a temporary address is the turned one: 80 wide, 100 high.
  globalThis.Image = class {
    src = ''; decode = async () => {}
    get naturalWidth() { return this.src.startsWith('blob:') ? 80 : 100 }
    get naturalHeight() { return this.src.startsWith('blob:') ? 100 : 80 }
  } as unknown as typeof Image
  dom.window.HTMLCanvasElement.prototype.getContext = (() => ({ drawImage() {}, translate() {}, rotate() {}, scale() {} })) as never
  dom.window.HTMLCanvasElement.prototype.toBlob = callback => callback(new Blob(['png'], { type: 'image/png' }))
  URL.createObjectURL = () => { const url = `blob:turned-${created.length}`; created.push(url); return url }
  URL.revokeObjectURL = url => { revoked.push(url) }
  const item = { name: 'original.png', type: 'image' as const, mode: null, size: 100, created_at: 1, url: '/api/v1/file/original.png' }
  const field = (name: string) => (screen.getByLabelText(name) as HTMLInputElement).value
  try {
    render(<ImageCropButton item={item} onReplace={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Edit original.png' }))
    await screen.findByRole('dialog', { name: 'Crop image' })
    await waitFor(() => assert.equal((screen.getByRole('button', { name: 'Save crop' }) as HTMLButtonElement).disabled, false))
    assert.equal(screen.getByRole('group', { name: 'Rotate and flip' }).querySelectorAll('button').length, 4)
    assert.equal(screen.queryByRole('button', { name: 'Undo rotate and flip' }), null)
    assert.deepEqual([field('Width (px)'), field('Height (px)')], ['100', '80'])

    fireEvent.click(screen.getByRole('button', { name: 'Rotate right' }))
    await waitFor(() => assert.deepEqual([field('Width (px)'), field('Height (px)')], ['80', '100']))
    assert.equal(created.length, 1)
    assert.equal((screen.getByRole('img', { name: 'original.png' }) as HTMLImageElement).src, 'blob:turned-0')

    fireEvent.click(screen.getByRole('button', { name: 'Undo rotate and flip' }))
    await waitFor(() => assert.deepEqual([field('Width (px)'), field('Height (px)')], ['100', '80']))
    assert.deepEqual(revoked, ['blob:turned-0'])
    assert.equal(screen.queryByRole('button', { name: 'Undo rotate and flip' }), null)

    fireEvent.click(screen.getByRole('button', { name: 'Flip vertically' }))
    await waitFor(() => assert.equal(created.length, 2))
    cleanup()
    assert.deepEqual(revoked, ['blob:turned-0', 'blob:turned-1'], 'closing the editor frees the temporary picture')
  } finally {
    cleanup(); globalThis.Image = originalImage
    dom.window.HTMLCanvasElement.prototype.getContext = originalContext
    dom.window.HTMLCanvasElement.prototype.toBlob = originalBlob
    URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke
  }
})
