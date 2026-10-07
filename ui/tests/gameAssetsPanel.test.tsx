import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAsset, GameAttempt } from '../src/features/game-assets/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function attempt(id: string, patch: Partial<GameAttempt> = {}): GameAttempt {
  return { id, status: 'ok', files: { preview: `game/bosque/${id}.png` }, ...patch }
}

function sample(id = 'bosque', assets?: GameAsset[]): Game {
  return {
    id, title: id === 'bosque' ? 'Bosque' : 'Cueva', revision: 2, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    style: {
      revision: 1, approval: 'draft', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets: assets ?? [
      { id: 'heroe', kind: 'character', name: 'Hero', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts: [], approvedAttemptId: null },
      { id: 'andar', kind: 'animation', name: 'Walk', description: '', status: 'pending', tags: [], spec: { character: 'heroe' }, dependsOn: ['heroe'], candidates: 1, locked: false, attempts: [], approvedAttemptId: null },
    ],
  }
}

function samples(): GameAsset[] {
  return [{
    id: 'style-sample-character', kind: 'character', name: 'Style sample', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 3, locked: false, approvedAttemptId: null,
    attempts: [attempt('s1-a1'), attempt('s1-a2', { decision: 'rejected', note: 'no' }), attempt('s1-a3', { status: 'failed', files: {} }), attempt('s1-a4')],
  }]
}

function start(game: Game, patch: Record<string, unknown> = {}) {
  useGameAssetsStore.setState({ workspace: 'lab', ready: true, games: [game], game, serverRevision: 2, dirty: false, unsaved: null, section: 'setup', error: null, problems: [], notice: null, presets: [], ...patch })
}

function reset() {
  stopGamePolling()
  setGameFetch(null)
  useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, unsaved: null, error: null, problems: [], section: 'setup' })
}

test('the panel asks for style approval, shows who assets are waiting on and marks the selected tab', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameAssetsPanel } = await import('../src/features/game-assets/GameAssetsPanel.tsx')
  const { PaletteEditor } = await import('../src/features/game-assets/PaletteEditor.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ activeWorkspace: 'lab' })
  start(sample(), { error: 'Could not save the game.', problems: [{ line: 0, code: 'too_many_assets', message: 'A game holds at most 500 assets' }] })
  try {
    render(<GameAssetsPanel />)
    assert.ok(screen.getByText('Approve the style before producing assets.'))
    assert.ok(screen.getByText('There are 1 assets waiting for you to approve Hero.'))
    assert.equal(screen.getByRole('alert').textContent, 'Could not save the game.A game holds at most 500 assets')
    const tab = screen.getByRole('tab', { name: 'Game' })
    assert.equal(tab.getAttribute('aria-selected'), 'true')
    assert.ok(tab.className.includes('font-medium'))
    fireEvent.click(screen.getByRole('tab', { name: 'Review' }))
    assert.equal(screen.getByRole('tab', { name: 'Review' }).getAttribute('aria-selected'), 'true')
    cleanup()
    const seen: string[][] = []
    render(<PaletteEditor colors={['#112233']} mode="locked" maxColors={8} onChange={colors => seen.push(colors)} onMode={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Hex'), { target: { value: 'red' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add color' }))
    assert.deepEqual(seen, [])
    assert.ok(screen.getByText('Use a color like #112233.'))
    cleanup()
    const many = Array.from({ length: 20 }, (_, index) => `#${index.toString(16).padStart(2, '0')}0000`)
    render(<PaletteEditor colors={many.slice(0, 4)} mode="locked" maxColors={4} onChange={() => undefined} onMode={() => undefined} />)
    assert.equal((screen.getByRole('button', { name: 'Add color' }) as HTMLButtonElement).disabled, true)
    cleanup()
    render(<PaletteEditor colors={many} mode="locked" maxColors={32} onChange={() => undefined} onMode={() => undefined} />)
    assert.equal(screen.getAllByRole('button', { name: /^Remove #/ }).length, 20, 'every swatch is shown')
  } finally {
    cleanup()
    reset()
  }
})

test('the library shows a loading state instead of the empty message', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { GameAssetsPanel } = await import('../src/features/game-assets/GameAssetsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ activeWorkspace: 'lab' })
  setGameFetch(() => new Promise<Response>(() => undefined))
  try {
    render(<GameAssetsPanel />)
    assert.ok(screen.getByText('Loading games…'))
    assert.equal(screen.queryByText('No game yet.'), null)
  } finally {
    cleanup()
    reset()
  }
})

test('style references offer one tile per usable candidate and reset when the game changes', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameStylePanel } = await import('../src/features/game-assets/GameStylePanel.tsx')
  const first = sample('bosque', samples())
  start(first)
  try {
    render(<GameStylePanel />)
    const images = [...document.querySelectorAll('img')].map(img => img.getAttribute('src'))
    assert.deepEqual(images, ['/api/v1/file/game/bosque/s1-a1.png?workspace=lab', '/api/v1/file/game/bosque/s1-a4.png?workspace=lab'])
    assert.equal(screen.queryByRole('button', { name: 'Use s1-a2 as reference' }), null, 'rejected attempts are not offered')
    assert.equal(screen.queryByRole('button', { name: 'Use s1-a3 as reference' }), null, 'failed attempts are not offered')
    fireEvent.click(screen.getByRole('button', { name: 'Use s1-a1 as reference' }))
    assert.equal(screen.getByRole('button', { name: 'Use s1-a1 as reference' }).getAttribute('aria-pressed'), 'true')
    const second = { ...sample('cueva', samples()), style: { ...sample().style, references: [{ assetId: 'style-sample-character', attemptId: 's1-a4' }] } }
    useGameAssetsStore.setState({ game: second })
    assert.equal((await screen.findByRole('button', { name: 'Use s1-a4 as reference' })).getAttribute('aria-pressed'), 'true')
    assert.equal(screen.getByRole('button', { name: 'Use s1-a1 as reference' }).getAttribute('aria-pressed'), 'false')
    assert.ok(screen.getByRole('option', { name: 'Dark, 1 px' }))
    assert.ok(screen.getByRole('option', { name: 'Top left' }))
  } finally {
    cleanup()
    reset()
  }
})

test('cleared number fields send nothing; the cast keeps the name until the server has the character', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameSetupPanel } = await import('../src/features/game-assets/GameSetupPanel.tsx')
  const { GameCastPanel } = await import('../src/features/game-assets/GameCastPanel.tsx')
  start(sample())
  let reply = () => new Response(JSON.stringify({ detail: { code: 'reserved_id', message: 'reserved_id' } }), { status: 422 })
  setGameFetch(async (input, init) => (init?.method === 'POST' ? reply() : new Response(JSON.stringify(sample()), { status: 200 })))
  try {
    render(<GameSetupPanel />)
    const tile = screen.getByLabelText('Tile') as HTMLInputElement
    fireEvent.change(tile, { target: { value: '' } })
    assert.equal(useGameAssetsStore.getState().unsaved, null, 'an empty field is not a 0')
    fireEvent.change(tile, { target: { value: '32' } })
    assert.deepEqual(useGameAssetsStore.getState().unsaved, { style: { pixel: { tile: 32 } } })
    cleanup()
    useGameAssetsStore.setState({ unsaved: null, dirty: false, game: sample() })
    render(<GameCastPanel />)
    const name = screen.getByLabelText('Name') as HTMLInputElement
    fireEvent.change(name, { target: { value: 'Con' } })
    fireEvent.click(screen.getByRole('button', { name: 'New character' }))
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.equal(name.value, 'Con', 'a failed create keeps the name')
    assert.equal(useGameAssetsStore.getState().error, 'That name is reserved by the system. Choose another one.')
    reply = () => new Response(JSON.stringify({ items: [], problems: [], estimate: {} }), { status: 200 })
    fireEvent.click(screen.getByRole('button', { name: 'New character' }))
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.equal(name.value, '')
    assert.ok(screen.getByText('Status: In review'))
  } finally {
    cleanup()
    reset()
  }
})
