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

test('a failed image tile retries its saved request and prevents duplicate clicks', async () => {
  const { render, fireEvent, cleanup, act } = await import('@testing-library/react')
  const { JobPlaceholder } = await import('../src/components/MainContent/MainContent.tsx')
  let retries = 0, dismissed = 0
  let release!: () => void
  const job = { id: 'failure', status: 'failed' as const, progress: 0, step: 0, totalSteps: 0,
    phase: '', message: 'Failed', outputFiles: [], error: 'Image decoder error',
    retry: () => { retries++; return new Promise<void>(resolve => { release = resolve }) } }
  try {
    const view = render(<JobPlaceholder job={job} onStop={() => undefined} onDismiss={() => { dismissed++ }} />)
    assert.match(view.container.textContent || '', /Image decoder error/)
    const button = view.getByRole('button', { name: /Retry|Reintentar/i })
    fireEvent.click(button)
    fireEvent.click(button)
    assert.equal(retries, 1)
    assert.equal(dismissed, 0)
    await act(async () => { release(); await Promise.resolve() })
    assert.equal(dismissed, 1)
  } finally { cleanup() }
})

test('a changed thumbnail recovers from a prior error without fetching the original', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { GalleryTile } = await import('../src/components/MainContent/GalleryTile.tsx')
  const props = { workspace: 'default', index: 0, active: false, cover: true, top: 0, left: 0,
    width: 160, height: 160, selecting: false, picked: false,
    onOpen: () => undefined, onOpenDetails: () => undefined, onPick: () => undefined, onLongPress: () => undefined }
  try {
    const view = render(<GalleryTile {...props} file={imageFile({ thumbnail_url: '/api/v1/outputs/thumbnail/portrait.png?v=1' })} />)
    fireEvent.error(view.container.querySelector('img')!)
    assert.equal(view.container.querySelector('img'), null)
    view.rerender(<GalleryTile {...props} file={imageFile({ thumbnail_url: '/api/v1/outputs/thumbnail/portrait.png?v=2' })} />)
    assert.match(view.container.querySelector('img')!.src, /thumbnail\/portrait.png\?v=2&size=sm/)
  } finally { cleanup() }
})

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
