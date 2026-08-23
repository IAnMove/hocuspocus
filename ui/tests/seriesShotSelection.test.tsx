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
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function makeEpisode(approved: boolean) {
  return {
    id: 'episode-1',
    title: 'Episode 1',
    shots: [{
      id: 'shot-1', sceneId: 'scene-1', order: 1, durationSeconds: 5,
      framing: 'wide', camera: 'locked', action: 'Action', dialogueBeats: [],
      visibleCharacterIds: [], speakingCharacterIds: [], wardrobeByCharacterId: {},
      propIds: [], emotionalStateByCharacterId: {}, renderStrategy: 'direct',
      referencePolicy: { mode: 'automatic', manualIncludeAssetIds: [], manualExcludeAssetIds: [] },
      prompt: 'Shot prompt', negativePrompt: '',
      approvedAttemptId: approved ? 'attempt-1' : undefined,
      attempts: approved ? [{ id: 'attempt-1', status: 'completed', model: 'minimax_h3', seed: 1, elapsedMs: 1000 }] : [],
    }],
  }
}

test('approving a selected Series shot removes it from selection and bulk count', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesShotsPanel } = await import('../src/features/series/SeriesShotsPanel.tsx')
  const series = {
    id: 'series-1', characters: [], locations: [], assets: {}, bestEffortLipSyncAcknowledged: false,
  }
  const props = {
    workspace: 'default', series: series as never,
    updateEpisode: () => undefined, replaceSeries: () => undefined,
    saveNow: async () => undefined, onAcknowledgeLipSync: async () => undefined,
    onRender: () => undefined,
  }
  try {
    const view = render(<SeriesShotsPanel {...props} episode={makeEpisode(false) as never} />)
    const select = screen.getByRole('button', { name: 'Select shot 1 for rendering' })
    fireEvent.click(select)
    assert.equal(select.getAttribute('aria-pressed'), 'true')
    assert.equal((screen.getByRole('button', { name: 'Render selected (1)' }) as HTMLButtonElement).disabled, false)

    view.rerender(<SeriesShotsPanel {...props} episode={makeEpisode(true) as never} />)
    const approved = await screen.findByRole('button', { name: 'Shot 1 is approved' })
    assert.equal((approved as HTMLButtonElement).disabled, true)
    assert.equal(approved.getAttribute('aria-pressed'), 'false')
    assert.equal((screen.getByRole('button', { name: 'Render selected (0)' }) as HTMLButtonElement).disabled, true)

    view.rerender(<SeriesShotsPanel {...props} episode={makeEpisode(false) as never} />)
    await waitFor(() => assert.equal(
      screen.getByRole('button', { name: 'Select shot 1 for rendering' }).getAttribute('aria-pressed'),
      'false',
    ))
  } finally {
    cleanup()
  }
})
