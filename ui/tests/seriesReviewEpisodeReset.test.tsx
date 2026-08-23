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
    HTMLMediaElement: dom.window.HTMLMediaElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function episode(id: string, number: number) {
  const shotId = `shot-${number}`
  const attemptId = `attempt-${number}`
  const assetId = `asset-${number}`
  return {
    id,
    title: `Episode ${number}`,
    shots: [{
      id: shotId, sceneId: `scene-${number}`, order: number, durationSeconds: 5,
      framing: 'wide', camera: 'locked', action: `Action ${number}`, dialogueBeats: [],
      visibleCharacterIds: [], speakingCharacterIds: [], wardrobeByCharacterId: {},
      propIds: [], emotionalStateByCharacterId: {}, renderStrategy: 'direct',
      referencePolicy: { mode: 'automatic', manualIncludeAssetIds: [], manualExcludeAssetIds: [] },
      prompt: `Shot ${number}`, negativePrompt: '', approvedAttemptId: attemptId,
      attempts: [{
        id: attemptId, status: 'completed', prompt: `Prompt ${number}`, negativePrompt: '',
        model: 'minimax_h3', referenceManifest: {
          strategy: 'direct', selected: [], omitted: [], warnings: [], errors: [],
          firstFrameRole: 'none', capabilitySnapshot: {},
        },
        seed: number, settings: {}, startTimeSeconds: 0, endTimeSeconds: 5,
        createdAt: '2026-08-16T00:00:00Z', completedAt: '2026-08-16T00:00:05Z',
        elapsedMs: 5000, outputAssetIds: [assetId], retryCount: 0,
      }],
    }],
    proposedCanonDelta: {
      baseRevision: 1,
      sourceEpisodeId: id,
      add: [{ id: 'shared-delta', description: `Canon proposal ${number}` }],
      change: [],
      retire: [],
    },
  }
}

test('Series Review pauses and clears episode-owned state when the episode changes', { concurrency: false }, async t => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesReviewPanel } = await import('../src/features/series/SeriesReviewPanel.tsx')
  const first = episode('episode-1', 1)
  const second = episode('episode-2', 2)
  const asset = (number: number) => ({
    id: `asset-${number}`, workspaceId: 'default', kind: 'video', uri: `outputs/clip-${number}.mp4`,
    ownerType: 'attempt', ownerId: `attempt-${number}`, isDerivedThumbnail: false, metadata: {},
  })
  const series = {
    id: 'series-1', title: 'Series',
    assets: { 'asset-1': asset(1), 'asset-2': asset(2) },
    provider: { videoSettings: { resolution: '540p', orientation: 'landscape' } },
  }
  const originalFetch = globalThis.fetch
  const originalPlay = window.HTMLMediaElement.prototype.play
  const originalPause = window.HTMLMediaElement.prototype.pause
  let pauses = 0
  t.after(() => {
    globalThis.fetch = originalFetch
    Object.defineProperty(window.HTMLMediaElement.prototype, 'play', { configurable: true, value: originalPlay })
    Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', { configurable: true, value: originalPause })
    cleanup()
  })
  Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
    configurable: true, value: async () => undefined,
  })
  Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
    configurable: true, value: () => { pauses += 1 },
  })
  globalThis.fetch = async () => new Response(JSON.stringify({
    jobId: 'assembly-episode-1', workspace: 'default', seriesId: 'series-1', episodeId: 'episode-1',
    status: 'completed', stage: 'completed', current: 1, total: 1,
    message: 'Episode 1 assembly is ready', filename: 'episode-1.mp4',
  }), { headers: { 'content-type': 'application/json' } })
  const common = {
    workspace: 'default', series, job: null, setJob: () => undefined,
    reload: async () => undefined, startRender: async () => undefined,
    updateEpisode: () => undefined, saveNow: async () => null,
  }

  const view = render(<SeriesReviewPanel {...common} episode={first as never} series={series as never} />)
  fireEvent.click(screen.getByRole('button', { name: 'Play all' }))
  assert.ok(screen.getByRole('button', { name: 'Stop' }))
  fireEvent.click(screen.getByRole('button', { name: 'Join clips' }))
  await screen.findByText('Episode 1 assembly is ready')
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
  assert.ok(screen.getByText(/Edit source data · shot 1/))
  fireEvent.click(screen.getByRole('button', { name: /Finalizar y canon/ }))
  fireEvent.click(screen.getByRole('button', { name: 'accepted' }))
  assert.match(screen.getByRole('button', { name: 'accepted' }).className, /bg-violet/)

  view.rerender(<SeriesReviewPanel {...common} episode={second as never} series={series as never} />)

  await waitFor(() => assert.equal(screen.queryByRole('button', { name: 'Stop' }), null))
  assert.ok(pauses >= 1)
  assert.equal(screen.queryByText('Episode 1 assembly is ready'), null)
  assert.equal(screen.queryByText(/Edit source data/), null)
  assert.ok(screen.getAllByText('Action 2').length >= 1)
  assert.ok(screen.getByRole('button', { name: /Montaje ordenado/ }))

  fireEvent.click(screen.getByRole('button', { name: /Finalizar y canon/ }))
  assert.doesNotMatch(screen.getByRole('button', { name: 'accepted' }).className, /bg-violet/)
  assert.match(screen.getByRole('button', { name: 'pending' }).className, /bg-violet/)
})
