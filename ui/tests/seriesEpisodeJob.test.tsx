import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function episode(id: string, title: string) {
  return {
    id,
    seasonId: 'season-1',
    number: id === 'episode-1' ? 1 : 2,
    title,
    premise: `${title} premise`,
    logline: '',
    targetDurationSeconds: 30,
    status: 'draft' as const,
    canonRevisionAtCreation: 1,
    canonSnapshot: { revision: 1 },
    outline: { beats: [] },
    script: [],
    shots: [],
    proposedCanonDelta: { baseRevision: 1, sourceEpisodeId: id, add: [], change: [], retire: [] },
    productionIds: [],
    createdAt: '2026-08-16T00:00:00Z',
    updatedAt: '2026-08-16T00:00:00Z',
  }
}

const series = {
  id: 'series-1',
  title: 'Series',
  provider: {
    writingProvider: 'maestro' as const,
    writingModel: 'model',
    writingBaseUrl: '',
  },
  locations: [],
  characters: [],
}

test('does not show or apply a late E1 proposal after switching to E2', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { SeriesEpisodePanel } = await import('../src/features/series/SeriesEpisodePanel.tsx')
  const t = ensureUiI18n().getFixedT('en', 'seriesLab')
  const originalFetch = globalThis.fetch
  let resolveStart!: (response: Response) => void
  const startResponse = new Promise<Response>(resolve => { resolveStart = resolve })
  let applyRequests = 0
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname.endsWith('/plan/start')) {
      assert.match(url.pathname, /episodes\/episode-1\/plan\/start$/)
      return startResponse
    }
    if (url.pathname.includes('/apply')) {
      applyRequests += 1
      return new Response('{}', { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url.pathname} ${init?.method || 'GET'}`)
  }

  const first = episode('episode-1', 'Episode One')
  const second = episode('episode-2', 'Episode Two')
  const props = (current: typeof first) => ({
    workspace: 'default', series, episode: current,
    updateEpisode: () => {}, saveNow: async () => {}, reload: async () => {},
  })
  const view = render(<SeriesEpisodePanel {...props(first)} />)
  fireEvent.click(screen.getByRole('button', { name: t('episode.generateOutline') }))
  view.rerender(<SeriesEpisodePanel {...props(second)} />)

  resolveStart(new Response(JSON.stringify({
    jobId: 'job-e1', episodeId: 'episode-1', seriesId: 'series-1', workspace: 'default',
    status: 'completed', stage: 'complete', current: 1, total: 1,
    message: 'E1 proposal complete', episodeResult: first,
  }), { headers: { 'content-type': 'application/json' } }))

  await waitFor(() => assert.equal(screen.queryByText('E1 proposal complete'), null))
  assert.equal(screen.queryByText('completed'), null)
  assert.equal(applyRequests, 0)
  cleanup()
  globalThis.fetch = originalFetch
})
