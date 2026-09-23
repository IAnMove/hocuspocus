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

const ROW = { top: 240, height: 424, mediaHeight: 320 }

test('image rows keep the frame the layout reserved after a portrait image decodes', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')
  resizeObservers.length = 0

  try {
    render(<MediaFeedItem file={imageFile()} index={0} isActive={false} onVisible={() => undefined} {...ROW} />)

    const viewport = screen.getByTestId('media-feed-viewport')
    const card = viewport.closest('[data-feed-index]') as HTMLElement
    assert.equal(card.style.top, '240px')
    assert.equal(card.style.height, '424px')
    assert.equal(viewport.style.height, '320px')

    const img = viewport.querySelector('img')
    assert.ok(img)
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1080 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 1920 })
    fireEvent.load(img)
    assert.equal(viewport.style.height, '320px')
    assert.equal(card.style.height, '424px')
    // The row is sized by the layout, never by measuring itself.
    assert.equal(resizeObservers.length, 0)
  } finally {
    cleanup()
  }
})

test('video rows keep their frame after portrait thumbnails decode', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')

  try {
    render(<MediaFeedItem
      file={imageFile({
        name: 'portrait.mp4',
        url: '/api/v1/file/portrait.mp4',
        type: 'video',
        mode: 'video',
        thumbnail_url: '/api/v1/outputs/thumbnail/portrait.mp4?v=1',
      })}
      index={2}
      isActive={false}
      onVisible={() => undefined}
      {...ROW}
    />)

    const viewport = screen.getByTestId('media-feed-viewport')
    const img = viewport.querySelector('img')
    assert.ok(img)
    assert.equal(img.getAttribute('src'), '/api/v1/outputs/thumbnail/portrait.mp4?v=1&size=md')
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1080 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 1920 })
    fireEvent.load(img)
    assert.equal(viewport.style.height, '320px')
    assert.equal(viewport.querySelectorAll('video').length, 0)
  } finally {
    cleanup()
  }
})

test('scene cards without a preview keep the layout height', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

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
      {...ROW}
    />)

    const viewport = screen.getByTestId('media-feed-viewport')
    assert.equal(viewport.style.height, '320px')
    assert.match(viewport.textContent || '', /Saved scene/)
  } finally {
    cleanup()
  }
})

test('scrolling selection retains the lightweight thumbnail and mounted image', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')
  const file = imageFile({ thumbnail_url: '/api/v1/outputs/thumbnail/portrait.png?v=2&workspace=default' })
  const preview = '/api/v1/outputs/thumbnail/portrait.png?v=2&workspace=default&size=md'

  try {
    const view = render(<MediaFeedItem file={file} index={0} isActive={false} onVisible={() => undefined} {...ROW} />)

    const img = screen.getByRole('img', { name: file.name })
    assert.equal(img.getAttribute('src'), preview)

    view.rerender(<MediaFeedItem file={file} index={0} isActive onVisible={() => undefined} {...ROW} />)

    await waitFor(() => {
      assert.equal(screen.getByRole('img', { name: file.name }), img)
      assert.equal(img.getAttribute('src'), preview)
    })
  } finally {
    cleanup()
  }
})

test('the info bar keeps every text line whole inside its fixed height', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')

  ensureUiI18n().changeLanguage('en')

  try {
    render(<MediaFeedItem file={imageFile()} index={0} isActive={false} onVisible={() => undefined} {...ROW} />)
    const viewport = screen.getByTestId('media-feed-viewport')
    const bar = viewport.nextElementSibling as HTMLElement
    assert.match(bar.className, /h-\[100px\]/)
    const lines = [...bar.querySelectorAll<HTMLElement>('.leading-4 > div')]
    assert.ok(lines.length > 0)
    for (const line of lines) assert.match(line.className, /\bh-4\b/)
  } finally {
    cleanup()
  }
})
