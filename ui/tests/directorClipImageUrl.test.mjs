import assert from 'node:assert/strict'
import test from 'node:test'
import React, { createElement } from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/',
})
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: dom.window.navigator,
})
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { cleanup, render, waitFor } = await import('@testing-library/react')
const { useDirectorClipImageUrl } = await import('../src/lib/directorClipImageUrl.ts')

function Preview({ image }) {
  const url = useDirectorClipImageUrl(image)
  return createElement('output', { 'data-testid': 'preview-url' }, url || '')
}

function image(overrides = {}) {
  return {
    clipIndex: 0,
    prompt: '',
    file: null,
    filename: 'clip.png',
    ...overrides,
  }
}

test('filename-only recovery uses the backend URL without creating an object URL', async () => {
  const originalCreateObjectURL = URL.createObjectURL
  let createCalls = 0
  URL.createObjectURL = () => {
    createCalls += 1
    return 'blob:unexpected'
  }

  try {
    const view = render(createElement(Preview, { image: image({ filename: 'recovered.png' }) }))
    await waitFor(() => assert.equal(
      view.getByTestId('preview-url').textContent,
      '/api/v1/file/recovered.png',
    ))
    assert.equal(createCalls, 0)
  } finally {
    cleanup()
    URL.createObjectURL = originalCreateObjectURL
  }
})

test('File previews create and revoke object URLs on replacement and unmount', async () => {
  const originalCreateObjectURL = URL.createObjectURL
  const originalRevokeObjectURL = URL.revokeObjectURL
  const created = []
  const revoked = []
  URL.createObjectURL = file => {
    const url = `blob:${file.name}:${created.length}`
    created.push(url)
    return url
  }
  URL.revokeObjectURL = url => revoked.push(url)

  try {
    const first = new File(['one'], 'one.png', { type: 'image/png' })
    const second = new File(['two'], 'two.png', { type: 'image/png' })
    const view = render(createElement(Preview, { image: image({ file: first }) }))
    await waitFor(() => assert.equal(view.getByTestId('preview-url').textContent, 'blob:one.png:0'))
    assert.deepEqual(created, ['blob:one.png:0'])

    view.rerender(createElement(Preview, { image: image({ file: second }) }))
    await waitFor(() => assert.equal(view.getByTestId('preview-url').textContent, 'blob:two.png:1'))
    assert.deepEqual(revoked, ['blob:one.png:0'])

    view.unmount()
    assert.deepEqual(revoked, ['blob:one.png:0', 'blob:two.png:1'])
  } finally {
    cleanup()
    URL.createObjectURL = originalCreateObjectURL
    URL.revokeObjectURL = originalRevokeObjectURL
  }
})
