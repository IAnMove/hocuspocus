import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

installDom()

test('Series Shots controls have programmatic names and selection state', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesShotsPanel } = await import('../src/features/series/SeriesShotsPanel.tsx')
  const shot = {
    id: 'shot-1', sceneId: 'scene-1', order: 1, durationSeconds: 10, framing: 'medium', camera: 'locked',
    action: 'A character enters', prompt: 'A character enters the workshop', negativePrompt: '', dialogueBeats: [],
    visibleCharacterIds: [], speakingCharacterIds: [], wardrobeByCharacterId: {}, propIds: [],
    emotionalStateByCharacterId: {}, renderStrategy: 'auto', referencePolicy: {
      mode: 'manual', manualIncludeAssetIds: [], manualExcludeAssetIds: [],
    }, attempts: [],
  }
  const episode = { id: 'episode-1', title: 'Episode 1', shots: [shot] }
  const series = {
    id: 'series-1', title: 'Series', bestEffortLipSyncAcknowledged: true,
    characters: [], locations: [], assets: {
      'asset-1': { id: 'asset-1', kind: 'image' },
    },
  }
  render(<SeriesShotsPanel
    workspace="default"
    series={series}
    episode={episode}
    updateEpisode={() => {}}
    replaceSeries={() => {}}
    saveNow={async () => ({})}
    onAcknowledgeLipSync={async () => {}}
    onRender={() => {}}
  />)

  const selectShot = screen.getByRole('button', { name: 'Select shot 1 for rendering' })
  assert.equal(selectShot.getAttribute('aria-pressed'), 'false')
  fireEvent.click(selectShot)
  assert.equal(selectShot.getAttribute('aria-pressed'), 'true')
  const selectAll = screen.getByRole('button', { name: 'Clear selection' })
  assert.equal(selectAll.getAttribute('aria-pressed'), 'true')
  assert.ok(screen.getByRole('combobox', { name: 'Requested clip for shot 1' }))
  assert.ok(screen.getByRole('combobox', { name: 'Render strategy for shot 1' }))
  assert.ok(screen.getByRole('textbox', { name: 'Prompt for shot 1' }))
  assert.ok(screen.getByRole('checkbox', { name: 'Include asset-1 in shot 1' }))
  assert.ok(screen.getByRole('checkbox', { name: 'Exclude asset-1 from shot 1' }))
  assert.ok(screen.getByLabelText('Composed start'))
  assert.ok(screen.getByLabelText('Composed end'))
  cleanup()
})
