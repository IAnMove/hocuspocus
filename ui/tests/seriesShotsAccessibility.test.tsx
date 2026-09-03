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
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  const { SeriesShotsPanel } = await import('../src/features/series/SeriesShotsPanel.tsx')
  const t = ensureUiI18n().getFixedT('en', 'seriesLab')
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

  const selectShot = screen.getByRole('button', { name: t('shots.selectAria', { order: 1 }) })
  assert.equal(selectShot.getAttribute('aria-pressed'), 'false')
  fireEvent.click(selectShot)
  assert.equal(selectShot.getAttribute('aria-pressed'), 'true')
  const selectAll = screen.getByRole('button', { name: t('shots.clearSelection') })
  assert.equal(selectAll.getAttribute('aria-pressed'), 'true')
  assert.ok(screen.getByRole('combobox', { name: t('duration.shotAria', { order: 1 }) }))
  assert.ok(screen.getByRole('combobox', { name: t('shots.strategyAria', { order: 1 }) }))
  assert.ok(screen.getByRole('textbox', { name: t('shots.promptAria', { order: 1 }) }))
  assert.ok(screen.getByRole('checkbox', { name: t('shots.includeAria', { id: 'asset-1', order: 1 }) }))
  assert.ok(screen.getByRole('checkbox', { name: t('shots.excludeAria', { id: 'asset-1', order: 1 }) }))
  assert.ok(screen.getByLabelText(t('shots.composedStart')))
  assert.ok(screen.getByLabelText(t('shots.composedEnd')))
  cleanup()
})
