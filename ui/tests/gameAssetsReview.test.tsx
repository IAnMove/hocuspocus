import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAttempt } from '../src/features/game-assets/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
    Image: dom.window.Image, HTMLImageElement: dom.window.HTMLImageElement,
    HTMLCanvasElement: dom.window.HTMLCanvasElement,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function attempt(id: string, warnings: string[] = []): GameAttempt {
  return { id, status: 'ok', files: { preview: `${id}.png` }, warnings, metrics: { colors: 8 } }
}

function game(): Game {
  return {
    id: 'bosque', title: 'Bosque', revision: 3, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets: [
      { id: 'heroe', kind: 'character', name: 'Hero', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts: [attempt('ok-1')], approvedAttemptId: null },
      { id: 'slime', kind: 'character', name: 'Slime', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts: [attempt('bad-1', ['loop_seam'])], approvedAttemptId: null },
    ],
  }
}

test('review rejects an empty note and bulk-approves only the clean asset', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameReviewPanel } = await import('../src/features/game-assets/GameReviewPanel.tsx')
  const { SpriteSheetPlayer } = await import('../src/features/game-assets/SpriteSheetPlayer.tsx')
  const current = game()
  const calls: string[] = []
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [current], game: current, serverRevision: 3, dirty: false,
    error: null, notice: null, produceJob: null, selectedIds: [], section: 'review',
  })
  setGameFetch(async (input, init) => {
    const url = String(input)
    calls.push(`${init?.method || 'GET'} ${url}`)
    if (String(init?.method) === 'GET') return new Response(JSON.stringify(current), { status: 200 })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  })
  window.confirm = () => true
  try {
    render(<GameReviewPanel />)
    const reject = screen.getAllByRole('button', { name: 'Reject' })[0] as HTMLButtonElement
    assert.equal(reject.disabled, true)
    fireEvent.click(screen.getByRole('button', { name: 'Approve all without warnings' }))
    await screen.findByText('No warnings')
    const approved = calls.filter(item => item.includes('/approve'))
    assert.equal(approved.length, 1)
    assert.ok(approved[0].includes('/assets/heroe/approve'))
    cleanup()

    const { act } = await import('@testing-library/react')
    mock.timers.enable({ apis: ['setTimeout'] })
    render(<SpriteSheetPlayer imageUrl="" atlas={{ frames: { a: { frame: { x: 0, y: 0, w: 4, h: 4 }, duration: 100 }, b: { frame: { x: 4, y: 0, w: 4, h: 4 }, duration: 100 } } }} pixel />)
    assert.equal(document.querySelector('canvas')?.getAttribute('data-frame'), '0')
    await act(async () => { mock.timers.tick(100) })
    assert.equal(document.querySelector('canvas')?.getAttribute('data-frame'), '1')
  } finally {
    mock.timers.reset()
    cleanup()
    setGameFetch(null)
    useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, produceJob: null, selectedIds: [] })
  }
})
