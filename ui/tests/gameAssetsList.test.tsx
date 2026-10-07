import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game } from '../src/features/game-assets/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function sample(): Game {
  return {
    id: 'bosque', title: 'Bosque', revision: 2, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets: [
      { id: 'andar', kind: 'animation', name: 'Walk', description: 'walk', status: 'pending', tags: [], spec: { action: 'walk' }, dependsOn: ['heroe'], candidates: 1, locked: false, attempts: [], approvedAttemptId: null },
    ],
  }
}

test('the list dialog shows simulated problems and production confirms the estimate', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameListPasteDialog } = await import('../src/features/game-assets/GameListPasteDialog.tsx')
  const { GameProducePanel } = await import('../src/features/game-assets/GameProducePanel.tsx')
  const game = sample()
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [game], game, serverRevision: 2, dirty: false, error: null, notice: null,
    produceJob: { id: 'job-1', status: 'interrupted', message: 'Interrupted', steps: [{ assetId: 'andar', kind: 'animation', status: 'skipped', reason: 'waiting_dependency' }] },
    selectedIds: [],
  })
  setGameFetch(async () => new Response(JSON.stringify({
    items: [],
    problems: [{ line: 2, code: 'unknown_kind', message: 'Unknown asset kind' }],
    estimate: { minutes: 4.5, source: 'trial', byKind: { animation: 4.5 } },
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  try {
    render(<GameListPasteDialog onClose={() => undefined} />)
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    assert.ok(await screen.findByText('Line 2: Unknown asset kind'))
    assert.ok(screen.getByText(/About 4.5 min/))
    assert.ok(screen.getByText(/trial/))
    assert.equal((screen.getByRole('button', { name: 'Add to the list' }) as HTMLButtonElement).disabled, true)
    cleanup()
    render(<GameProducePanel />)
    assert.ok(screen.getByRole('button', { name: 'Resume' }))
    assert.ok(screen.getByText('Production was interrupted.'))
    assert.ok(screen.getByText('Waiting for an approved dependency'))
    fireEvent.click(screen.getByRole('button', { name: 'Produce pending' }))
    assert.ok(await screen.findByRole('dialog', { name: 'Start production' }))
    assert.ok(screen.getByText(/About 4.5 min/))
  } finally {
    cleanup()
    setGameFetch(null)
    useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, produceJob: null, selectedIds: [] })
  }
})
