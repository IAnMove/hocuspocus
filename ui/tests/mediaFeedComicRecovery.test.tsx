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
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
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

test('a gallery card exposes a Comic recovery failure without selecting the invalid project', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { MediaFeedItem } = await import('../src/components/MainContent/MediaFeedItem.tsx')
  const { createComicProject } = await import('../src/features/comics/model.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const previousConsoleError = console.error
  const originalProjectId = useComicStore.getState().project.id
  const invalidProject = createComicProject()
  invalidProject.provenance = {
    schema: 'hocuspocus.comic.provenance/v1',
    workspaceId: 'workspace-1',
    actor: 'user',
    createdAt: '2026-09-03T10:00:00.000Z',
    source: {
      kind: 'series_episode',
      seriesId: 'series-1',
      episodeId: 'episode-1',
      seriesRevision: 1,
      episodeUpdatedAt: '2026-09-03T10:00:00.000Z',
      productionIds: [],
      assetIds: [],
    },
    destination: {
      comicId: 'a-different-comic',
      outputAssetIds: [],
    },
  }

  ensureUiI18n().changeLanguage('en')
  useStore.setState({ activeWorkspace: 'workspace-1', browsingUploads: false })
  globalThis.fetch = async input => {
    if (String(input).includes('/api/v1/comics/')) {
      return new Response(JSON.stringify({ project: invalidProject }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`Unexpected fetch: ${String(input)}`)
  }
  console.error = () => undefined

  try {
    render(<MediaFeedItem
      file={{
        name: 'broken.comic.json',
        url: '/api/v1/comics/broken.comic.json',
        type: 'comic',
        mode: null,
        favorite: false,
        size: 1,
        created_at: 1,
      }}
      index={0}
      isActive={false}
      onVisible={() => undefined}
      onMeasured={() => undefined}
    />)

    fireEvent.click(screen.getByText('Saved comic'))
    const alert = await screen.findByRole('alert')
    assert.match(alert.textContent || '', /Could not open this comic/)
    assert.equal(useComicStore.getState().project.id, originalProjectId)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    console.error = previousConsoleError
  }
})
