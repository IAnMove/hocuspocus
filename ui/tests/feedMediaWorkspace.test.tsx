import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
  class ObserverStub {
    observe() {}
    disconnect() {}
  }
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLAnchorElement: dom.window.HTMLAnchorElement,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: ObserverStub,
    IntersectionObserver: ObserverStub,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
}

installDom()

const model = {
  name: 'head.glb',
  url: '/api/v1/file/head.glb',
  type: 'model3d' as const,
  mode: 'image' as const,
  favorite: false,
  size: 1,
  created_at: 1,
}

const video = {
  name: 'sunset.mp4',
  url: '/api/v1/file/sunset.mp4',
  type: 'video' as const,
  mode: 'video' as const,
  favorite: false,
  size: 1,
  created_at: 1,
}

test('3D preview and download pin the listed workspace', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { FeedMediaBody } = await import('../src/components/MainContent/FeedMediaBody.tsx')
  const noop = () => undefined
  try {
    const view = render(
      <FeedMediaBody
        file={model}
        workspace="film"
        isActive
        previewUrl={null}
        videoReady={false}
        videoRef={{ current: null }}
        onPlay={noop}
        onOpenDetails={noop}
        isScene={false}
        isComic={false}
        isModel3d
        canPreviewModel3d
        isRigged={false}
        riggedClips={[]}
        activeClip={null}
        setActiveClip={noop}
        retryImage={() => null}
      />,
    )
    const preview = view.container.querySelector('model-viewer')
    const download = view.container.querySelector('a[download]')
    assert.equal(preview?.getAttribute('src'), '/api/v1/file/head.glb?workspace=film')
    assert.equal(download?.getAttribute('href'), '/api/v1/file/head.glb?workspace=film')
  } finally {
    cleanup()
  }
})

test('gallery download pins the listed workspace instead of the server active folder', { concurrency: false }, async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { OutputActionBar } = await import('../src/components/MainContent/OutputActionBar.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n().changeLanguage('en')
  useStore.setState({ activeWorkspace: 'film', browsingUploads: false })
  const hrefs: string[] = []
  const createElement = document.createElement.bind(document)
  document.createElement = ((tag: string) => {
    const node = createElement(tag)
    if (tag === 'a') {
      Object.defineProperty(node, 'click', {
        configurable: true,
        value: () => { hrefs.push((node as HTMLAnchorElement).href) },
      })
    }
    return node
  }) as typeof document.createElement
  try {
    const view = render(<OutputActionBar file={video} index={0} params={{}} />)
    fireEvent.click(view.getByTitle('Download'))
    assert.deepEqual(hrefs.map(href => new URL(href, 'http://gallery.test').pathname + new URL(href, 'http://gallery.test').search), [
      '/api/v1/file/sunset.mp4?workspace=film',
    ])
  } finally {
    document.createElement = createElement
    cleanup()
  }
})
