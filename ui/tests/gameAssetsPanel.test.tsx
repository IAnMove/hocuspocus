import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
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
      revision: 1, approval: 'draft', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets: [
      { id: 'heroe', kind: 'character', name: 'Hero', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts: [], approvedAttemptId: null },
      { id: 'andar', kind: 'animation', name: 'Walk', description: '', status: 'pending', tags: [], spec: { character: 'heroe' }, dependsOn: ['heroe'], candidates: 1, locked: false, attempts: [], approvedAttemptId: null },
    ],
  }
}

test('the panel asks for style approval and shows who assets are waiting on', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameAssetsPanel } = await import('../src/features/game-assets/GameAssetsPanel.tsx')
  const { PaletteEditor } = await import('../src/features/game-assets/PaletteEditor.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const game = sample()
  useStore.setState({ activeWorkspace: 'lab' })
  useGameAssetsStore.setState({ workspace: 'lab', ready: true, games: [game], game, serverRevision: 2, dirty: false, section: 'setup', error: null, notice: null, presets: [] })
  try {
    render(<GameAssetsPanel />)
    assert.ok(screen.getByText('Approve the style before producing assets.'))
    assert.ok(screen.getByText('There are 1 assets waiting for you to approve Hero.'))
    const seen: string[][] = []
    render(<PaletteEditor colors={['#112233']} mode="locked" maxColors={8} onChange={colors => seen.push(colors)} onMode={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Hex'), { target: { value: 'red' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add color' }))
    assert.deepEqual(seen, [])
    assert.ok(screen.getByText('Use a color like #112233.'))
  } finally {
    cleanup()
    useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false })
  }
})
