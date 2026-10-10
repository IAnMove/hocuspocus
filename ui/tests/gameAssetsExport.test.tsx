import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAsset, GameExportRecord } from '../src/features/game-assets/types.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

function asset(id: string, kind: string, status: string): GameAsset {
  const attempts = status === 'approved' ? [{ id: `${id}-a`, status: 'ok', files: { main: `${id}.png` } }] : []
  return { id, kind, name: id, description: '', status, tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts, approvedAttemptId: attempts[0]?.id || null }
}

function sample(id: string, exports: GameExportRecord[] = []): Game {
  return {
    id, title: id, revision: 4, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports,
    assets: [asset('heroe', 'character', 'approved'), asset('suelo', 'tile', 'approved'), asset('slime', 'character', 'review')],
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

interface Call { method: string; url: string; body: Record<string, unknown> }

function serve(reply: (call: Call) => Response): Call[] {
  const calls: Call[] = []
  setGameFetch(async (input, init) => {
    const call = { method: String(init?.method || 'GET'), url: String(input), body: init?.body ? JSON.parse(String(init.body)) : {} }
    calls.push(call)
    return reply(call)
  })
  return calls
}

function start(game: Game, workspace = 'lab one'): void {
  useGameAssetsStore.setState({
    workspace, ready: true, games: [game], game, serverRevision: game.revision, unsaved: null, dirty: false, saving: false,
    error: null, problems: [], notice: null, produceJob: null, styleJob: null, selectedIds: [], exportResult: null, exporting: false, section: 'export',
  })
}

function reset(): void {
  stopGamePolling()
  setGameFetch(null)
  useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], unsaved: null, dirty: false, error: null, problems: [], exportResult: null, exporting: false })
}

async function harness() {
  const { ErrorNotice } = await import('../src/features/game-assets/gameUi.tsx')
  const { GameExportPanel } = await import('../src/features/game-assets/GameExportPanel.tsx')
  // The panel's errors show in the game notices, as in GameAssetsPanel.
  return function Harness() {
    const error = useGameAssetsStore(state => state.error)
    return <><ErrorNotice error={error} /><GameExportPanel /></>
  }
}

test('nothing to export is a translated alert, not a thrown error', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent, act } = await import('@testing-library/react')
  const Harness = await harness()
  const rejections: unknown[] = []
  const onRejection = (reason: unknown) => rejections.push(reason)
  process.on('unhandledRejection', onRejection)
  start(sample('bosque'))
  serve(() => json({ detail: { code: 'nothing_to_export', message: 'no approved asset has a file to export' } }, 409))
  try {
    render(<Harness />)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Export' })) })
    assert.equal(screen.getByRole('alert').textContent, 'Nothing to export: approve at least one asset whose files exist.')
    assert.equal(useGameAssetsStore.getState().notice, null, 'a 409 that is not a revision conflict does not reload as a conflict')
    assert.equal(useGameAssetsStore.getState().exportResult, null)
    assert.equal((screen.getByRole('button', { name: 'Export' }) as HTMLButtonElement).disabled, false)
    assert.deepEqual(rejections, [])
  } finally {
    process.off('unhandledRejection', onRejection)
    cleanup()
    reset()
  }
})

test('an export saves pending edits first, lists what it lost and refreshes the history with encoded links', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent, act, within } = await import('@testing-library/react')
  const Harness = await harness()
  const file = 'game-exports/mi juego#1-r5.zip'
  const record = { id: 'e2', revision: 5, file, createdAt: '2026-10-07T10:00:00Z', counts: { character: 1, total: 1 } }
  const older = { id: 'e1', revision: 4, file: 'game-exports/mi-juego-r4.zip', createdAt: '2026-10-06T10:00:00Z', counts: { total: 2 } }
  start(sample('mi juego', [older]))
  const calls = serve(call => {
    if (call.method === 'PUT') return json({ ...sample('mi juego', [older]), revision: 5, title: 'Renamed' })
    if (call.method === 'POST') {
      return json({
        file, url: '/api/v1/file/game-exports/mi%20juego%231-r5.zip?workspace=lab%20one', counts: { character: 1, total: 1 },
        missing: [
          { id: 'slime', kind: 'character', status: 'review' },
          { id: 'suelo', kind: 'tile', status: 'approved', problem: 'files_missing', files: ['suelo.png'] },
        ],
      })
    }
    return json({ ...sample('mi juego', [older, record]), revision: 5, title: 'Renamed' })
  })
  try {
    render(<Harness />)
    act(() => { useGameAssetsStore.getState().patchGame({ title: 'Renamed' }) })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Export' })) })
    assert.deepEqual(calls.map(call => call.method), ['PUT', 'POST', 'GET'], 'the pack is written from the saved revision')
    assert.equal(calls[1].url, '/api/v1/games/mi%20juego/export')
    const summary = screen.getByRole('status')
    assert.ok(within(summary).getByText('Approved but not fully packed'))
    assert.ok(within(summary).getByText('Tile suelo: some files are missing (suelo.png)'))
    assert.ok(within(summary).getByText('Character: 1 · Total: 1'))
    const links = screen.getAllByRole('link', { name: 'mi juego#1-r5.zip' })
    assert.ok(links.length >= 2, 'the new pack is in the summary and in the refreshed history')
    for (const link of links) assert.equal(link.getAttribute('href'), '/api/v1/file/game-exports/mi%20juego%231-r5.zip?workspace=lab%20one')
    const history = screen.getByText('Export history').parentElement as HTMLElement
    const rows = within(history).getAllByRole('listitem').map(item => item.textContent || '')
    assert.ok(rows[0].includes('Revision 5') && rows[1].includes('Revision 4'), 'newest first')
    assert.ok(screen.getByText('Approved: 2'))
    assert.ok(screen.getByText('Not approved: 1'))
    assert.ok(!document.body.textContent?.includes('[object Object]'))
  } finally {
    cleanup()
    reset()
  }
})

test('the last export belongs to its game: opening another game hides it', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent, act } = await import('@testing-library/react')
  const Harness = await harness()
  start(sample('bosque'))
  serve(call => {
    if (call.method === 'POST') return json({ file: 'game-exports/bosque-r4.zip', url: '', counts: { total: 2 }, missing: [] })
    if (call.url.includes('/games/cueva')) return json(sample('cueva'))
    return json(sample('bosque'))
  })
  try {
    render(<Harness />)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Export' })) })
    assert.ok(screen.getByRole('status'))
    await act(async () => { await useGameAssetsStore.getState().openGame('cueva') })
    assert.equal(screen.queryByRole('status'), null)
    assert.equal(screen.queryByText('bosque-r4.zip'), null)
  } finally {
    cleanup()
    reset()
  }
})
