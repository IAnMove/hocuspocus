import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAsset, ProduceJob } from '../src/features/game-assets/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function asset(patch: Partial<GameAsset>): GameAsset {
  return { id: 'andar', kind: 'animation', name: 'Walk', description: 'walk', status: 'pending', tags: [], spec: { action: 'walk' }, dependsOn: ['heroe'], candidates: 1, locked: false, attempts: [], approvedAttemptId: null, ...patch }
}

function sample(assets: GameAsset[] = [asset({})]): Game {
  return {
    id: 'bosque', title: 'Bosque', revision: 2, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
    assets,
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function start(game: Game, produceJob: ProduceJob | null = null) {
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [game], game, serverRevision: 2, dirty: false, unsaved: null, error: null, problems: [], notice: null,
    produceJob, selectedIds: [],
  })
}

function reset() {
  stopGamePolling()
  setGameFetch(null)
  useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, unsaved: null, produceJob: null, selectedIds: [], error: null, problems: [] })
}

const report = { items: [], problems: [{ line: 2, code: 'unknown_kind', message: 'Unknown asset kind' }], estimate: { minutes: 4.5, source: 'trial', byKind: { animation: 4.5 } } }

test('the list dialog shows problems with lines and production confirms the estimate with its candidates', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameListPasteDialog } = await import('../src/features/game-assets/GameListPasteDialog.tsx')
  const { GameProducePanel } = await import('../src/features/game-assets/GameProducePanel.tsx')
  start(sample([asset({ candidates: 3 })]), { id: 'job-1', status: 'interrupted', message: 'Interrupted', steps: [{ assetId: 'andar', kind: 'animation', status: 'skipped', reason: 'waiting_dependency' }] })
  const bodies: Record<string, unknown>[] = []
  setGameFetch(async (_input, init) => {
    bodies.push(JSON.parse(String(init?.body || '{}')))
    return json(report)
  })
  try {
    render(<GameListPasteDialog onClose={() => undefined} />)
    const textarea = screen.getByLabelText('Asset list') as HTMLTextAreaElement
    assert.equal(textarea.value, '', 'the example is a placeholder')
    assert.ok(textarea.placeholder.startsWith('personaje heroe'))
    assert.equal((screen.getByRole('button', { name: 'Check' }) as HTMLButtonElement).disabled, true)
    fireEvent.change(textarea, { target: { value: 'monstruo x: y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    assert.ok(await screen.findByText('Line 2: Unknown asset kind'))
    assert.ok(screen.getByText(/About 4.5 min/))
    assert.ok(screen.getByText('Animation: 4.5 min'))
    assert.equal((screen.getByRole('button', { name: 'Add to the list' }) as HTMLButtonElement).disabled, true)
    cleanup()
    render(<GameProducePanel />)
    assert.ok(screen.getByRole('button', { name: 'Resume' }))
    assert.ok(screen.getByText('Production was interrupted.'))
    assert.ok(screen.getByText('Waiting for an approved dependency'))
    assert.ok(screen.getByText(/0 \/ 1 · 1 waiting/), 'a waiting step is not counted as done')
    fireEvent.click(screen.getByRole('button', { name: 'Produce pending' }))
    assert.ok(await screen.findByRole('dialog', { name: 'Start production' }))
    assert.ok(screen.getByText(/About 4.5 min/))
    assert.equal((bodies.at(-1)?.items as { candidates: number }[])[0].candidates, 3)
  } finally {
    cleanup()
    reset()
  }
})

test('replace sends the flag with the check, resets the check when toggled and confirms what it removes', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameListPasteDialog } = await import('../src/features/game-assets/GameListPasteDialog.tsx')
  start(sample([asset({ id: 'heroe', kind: 'character', name: 'Hero', status: 'approved' }), asset({ id: 'slime', kind: 'character', name: 'Slime', locked: true }), asset({ id: 'moneda', kind: 'item', name: 'Coin' })]))
  const bodies: Record<string, unknown>[] = []
  setGameFetch(async (_input, init) => {
    bodies.push(JSON.parse(String(init?.body || '{}')))
    return json({ items: [{ id: 'moneda', kind: 'item' }], problems: [], estimate: { minutes: 1, source: 'defaults', byKind: {} } })
  })
  const confirms: string[] = []
  window.confirm = message => { confirms.push(String(message)); return false }
  try {
    render(<GameListPasteDialog onClose={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Asset list'), { target: { value: 'objeto moneda: moneda de oro' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    assert.ok(await screen.findByText('No problems.'))
    assert.equal(bodies[0].replace, false)
    fireEvent.click(screen.getByRole('checkbox'))
    assert.equal(screen.queryByText('No problems.'), null, 'toggling replace needs a new check')
    assert.equal((screen.getByRole('button', { name: 'Replace the list' }) as HTMLButtonElement).disabled, true)
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('No problems.')
    assert.deepEqual([bodies[1].replace, bodies[1].check], [true, true])
    fireEvent.click(screen.getByRole('button', { name: 'Replace the list' }))
    assert.deepEqual(confirms, ['2 assets will be removed.\nApproved or locked among them: Hero, Slime'])
    assert.equal(bodies.length, 2, 'a declined replace sends nothing')
  } finally {
    cleanup()
    reset()
  }
})

test('editing a CSV list keeps the CSV format and a failed add shows whole-list problems without line 0', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameListPasteDialog } = await import('../src/features/game-assets/GameListPasteDialog.tsx')
  start(sample())
  const bodies: Record<string, unknown>[] = []
  setGameFetch(async (_input, init) => {
    const body = JSON.parse(String(init?.body || '{}'))
    bodies.push(body)
    if (body.check) return json({ items: [{ id: 'a', kind: 'item' }], problems: [], estimate: { minutes: 1, source: 'defaults', byKind: {} } })
    return json({ detail: { code: 'invalid_list', message: 'The list has problems', problems: [{ line: 0, code: 'too_many_assets', message: 'A game holds at most 500 assets' }] } }, 422)
  })
  let closed = false
  try {
    render(<GameListPasteDialog onClose={() => { closed = true }} />)
    fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'csv' } })
    fireEvent.change(screen.getByLabelText('Asset list'), { target: { value: 'kind,id\nitem,a' } })
    fireEvent.change(screen.getByLabelText('Asset list'), { target: { value: 'kind,id\nitem,a\n' } })
    assert.equal((screen.getByLabelText('Format') as HTMLSelectElement).value, 'csv')
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('No problems.')
    assert.equal(bodies[0].csv, 'kind,id\nitem,a\n')
    assert.equal(bodies[0].text, undefined)
    fireEvent.click(screen.getByRole('button', { name: 'Add to the list' }))
    assert.ok(await screen.findByText('A game holds at most 500 assets'))
    assert.ok(screen.getByText('The list has problems.'))
    assert.ok(!document.body.textContent?.includes('Line 0'))
    assert.equal(closed, false, 'the dialog stays open with the text')
    fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'json' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    assert.ok(await screen.findByText('The JSON must be a list of assets.'))
  } finally {
    cleanup()
    reset()
  }
})

test('produce is blocked while a job runs, cancel hides while cancelling, finished jobs with waiting steps resume', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { GameProducePanel } = await import('../src/features/game-assets/GameProducePanel.tsx')
  start(sample(), { id: 'job-1', status: 'running', steps: [{ assetId: 'andar', kind: 'animation', status: 'running' }] })
  try {
    const view = render(<GameProducePanel />)
    assert.equal((screen.getByRole('button', { name: 'Produce pending' }) as HTMLButtonElement).disabled, true)
    assert.ok(screen.getByText(/A production is running for this game/))
    assert.ok(screen.getByRole('button', { name: 'Cancel' }))
    assert.equal(screen.queryByRole('button', { name: 'Resume' }), null)
    useGameAssetsStore.setState({ produceJob: { id: 'job-1', status: 'cancelling', steps: [] } })
    view.rerender(<GameProducePanel />)
    assert.equal(screen.queryByRole('button', { name: 'Cancel' }), null)
    assert.equal((screen.getByRole('button', { name: 'Cancelling…' }) as HTMLButtonElement).disabled, true)
    useGameAssetsStore.setState({ produceJob: { id: 'job-1', status: 'completed', steps: [{ assetId: 'andar', kind: 'animation', status: 'skipped', reason: 'waiting_dependency' }] } })
    view.rerender(<GameProducePanel />)
    assert.equal((screen.getByRole('button', { name: 'Produce pending' }) as HTMLButtonElement).disabled, false)
    assert.ok(screen.getByRole('button', { name: 'Resume' }))
    assert.ok(screen.getByText(/finished with assets still waiting/))
  } finally {
    cleanup()
    reset()
  }
})

test('a list row refreshes its draft when the asset changes and shows its save error', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { GameListPanel } = await import('../src/features/game-assets/GameListPanel.tsx')
  start(sample())
  setGameFetch(async () => json({ detail: { code: 'reserved_id', message: 'reserved_id' } }, 422))
  try {
    render(<GameListPanel />)
    const name = screen.getByLabelText('Name andar') as HTMLInputElement
    fireEvent.change(name, { target: { value: 'Typed' } })
    assert.equal(name.value, 'Typed')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    assert.ok(await screen.findByText('That name is reserved by the system. Choose another one.'))
    assert.equal((screen.getByLabelText('Name andar') as HTMLInputElement).value, 'Typed', 'a failed save keeps the draft')
    useGameAssetsStore.setState({ game: sample([asset({ name: 'From server' })]) })
    assert.equal(await screen.findByDisplayValue('From server'), screen.getByLabelText('Name andar'))
    assert.ok(screen.getAllByText('Animation').length > 0)
    assert.ok(screen.getAllByText('Pending').length > 0)
  } finally {
    cleanup()
    reset()
  }
})
