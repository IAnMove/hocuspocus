import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
  const resizeObservers: Array<(entries: unknown[]) => void> = []
  class ResizeObserverStub {
    callback: (entries: unknown[]) => void
    constructor(callback: (entries: unknown[]) => void) {
      this.callback = callback
      resizeObservers.push(callback)
    }
    observe() {}
    disconnect() {}
  }
  class ObserverStub {
    observe() {}
    disconnect() {}
  }
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: ResizeObserverStub,
    IntersectionObserver: ObserverStub,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
  return { resizeObservers }
}

const { resizeObservers } = installDom()

function imageFile(overrides: Record<string, unknown> = {}) {
  return {
    name: 'portrait.png',
    url: '/api/v1/file/portrait.png',
    type: 'image' as const,
    mode: 'image' as const,
    favorite: false,
    size: 1,
    created_at: 1,
    thumbnail_url: '/api/v1/file/portrait.png?thumb=1',
    ...overrides,
  }
}

test('still cards keep a reserved viewport while the image is unloaded', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')
  const { MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO } = await import('../src/components/MainContent/mediaFeedSizing.ts')

  ensureUiI18n().changeLanguage('en')

  try {
    render(<MediaFeedItem
      file={imageFile()}
      index={0}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    const viewport = screen.getByTestId('media-feed-viewport')
    assert.equal(Number(viewport.style.aspectRatio), MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO)

    const img = viewport.querySelector('img')
    assert.ok(img)
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1080 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 1920 })
    fireEvent.load(img)
    assert.equal(Number(viewport.style.aspectRatio), 1080 / 1920)
  } finally {
    cleanup()
  }
})

test('video cards use the clip aspect instead of a 16:9 letterbox', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')
  const { MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO } = await import('../src/components/MainContent/mediaFeedSizing.ts')

  ensureUiI18n().changeLanguage('en')

  try {
    render(<MediaFeedItem
      file={imageFile({
        name: 'portrait.mp4',
        url: '/api/v1/file/portrait.mp4',
        type: 'video',
        mode: 'video',
        thumbnail_url: '/api/v1/file/portrait.mp4?thumb=1',
      })}
      index={2}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    const viewport = screen.getByTestId('media-feed-viewport')
    assert.equal(Number(viewport.style.aspectRatio), MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO)
    assert.equal(viewport.className.includes('aspect-video'), false)

    const img = viewport.querySelector('img')
    assert.ok(img)
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1080 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 1920 })
    fireEvent.load(img)
    assert.equal(Number(viewport.style.aspectRatio), 1080 / 1920)
  } finally {
    cleanup()
  }
})

test('scene cards without a preview still reserve 16:9', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')
  const { MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO } = await import('../src/components/MainContent/mediaFeedSizing.ts')

  ensureUiI18n().changeLanguage('en')

  try {
    render(<MediaFeedItem
      file={{
        name: 'saved.scene.json',
        url: '/api/v1/file/saved.scene.json',
        type: 'scene',
        mode: null,
        favorite: false,
        size: 1,
        created_at: 1,
      }}
      index={1}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    const viewport = screen.getByTestId('media-feed-viewport')
    assert.equal(Number(viewport.style.aspectRatio), MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO)
    assert.match(viewport.textContent || '', /Saved scene/)
  } finally {
    cleanup()
  }
})

test('switching from thumbnail to full URL keeps the still image mounted', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')
  const file = imageFile()

  try {
    const view = render(<MediaFeedItem
      file={file}
      index={0}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    const img = screen.getByRole('img', { name: file.name })
    assert.equal(img.getAttribute('src'), file.thumbnail_url)

    view.rerender(<MediaFeedItem
      file={file}
      index={0}
      isActive
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    await waitFor(() => {
      assert.equal(screen.getByRole('img', { name: file.name }), img)
      assert.equal(img.getAttribute('src'), file.url)
    })
  } finally {
    cleanup()
  }
})

test('onMeasured ignores the info-bar-only collapse', { concurrency: false }, async () => {
  resizeObservers.length = 0
  const { render, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')
  const measured: number[] = []

  try {
    render(<MediaFeedItem
      file={imageFile()}
      index={0}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={(_index, height) => { measured.push(height) }}
    />)

    assert.ok(resizeObservers.length > 0)
    const notify = resizeObservers[resizeObservers.length - 1]
    notify([{ borderBoxSize: [{ blockSize: 48 }], contentRect: { height: 48 } }])
    notify([{ borderBoxSize: [{ blockSize: 420 }], contentRect: { height: 420 } }])
    assert.deepEqual(measured, [420])
  } finally {
    cleanup()
  }
})
