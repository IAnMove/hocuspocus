import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setGameFetch } from '../src/api/gameAssets.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAttempt, GameWarning } from '../src/features/game-assets/types.ts'

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

function attempt(id: string, warnings: GameWarning[] = [], patch: Partial<GameAttempt> = {}): GameAttempt {
  return { id, status: 'ok', files: { preview: `${id}.png` }, warnings, metrics: { colors: 8 }, ...patch }
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
      {
        id: 'suelo', kind: 'tile', name: 'Ground', description: '', status: 'rejected', tags: [], spec: {}, dependsOn: [], candidates: 3, locked: false, approvedAttemptId: null,
        attempts: [
          attempt('s-a1', [], { decision: 'rejected', note: 'too dark' }),
          attempt('s-a2', [{ code: 'seam_visible', message: 'seam error 2.0 is above 1.5', file: 's-a2/tile.png' }, { code: 'mystery', message: 'Server text' }]),
          attempt('s-a3', [], { status: 'failed', files: {}, note: 'model crashed' }),
        ],
      },
      { id: 'cofre', kind: 'item', name: 'Chest', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 2, locked: false, attempts: [attempt('c-a1'), attempt('c-a2')], approvedAttemptId: null },
    ],
  }
}

function reset() {
  stopGamePolling()
  setGameFetch(null)
  useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], dirty: false, unsaved: null, produceJob: null, selectedIds: [], error: null, notice: null })
}

test('review lists open candidates, explains decisions and bulk-approves only single clean candidates', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent, within } = await import('@testing-library/react')
  const { GameReviewPanel } = await import('../src/features/game-assets/GameReviewPanel.tsx')
  const current = game()
  const calls: string[] = []
  const confirms: string[] = []
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [current], game: current, serverRevision: 3, dirty: false, unsaved: null,
    error: null, notice: null, produceJob: null, selectedIds: [], section: 'review',
  })
  setGameFetch(async (input, init) => {
    calls.push(`${init?.method || 'GET'} ${String(input)}`)
    if (String(init?.method || 'GET') === 'GET') return new Response(JSON.stringify(current), { status: 200 })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  })
  window.confirm = message => { confirms.push(String(message)); return true }
  try {
    render(<GameReviewPanel />)
    const ground = screen.getByRole('region', { name: 'Candidate s-a2' })
    assert.ok(within(ground).getByText('The tile seam is visible. (s-a2/tile.png)'))
    assert.ok(within(ground).getByText('Server text'))
    assert.ok(!document.body.textContent?.includes('[object Object]'))
    assert.ok(screen.getByText('Note: too dark'))
    assert.ok(screen.getAllByText(/Rejected/).length > 0)
    assert.equal((screen.getByRole('button', { name: 'Approve s-a3' }) as HTMLButtonElement).disabled, true, 'a failed attempt cannot be approved')
    assert.equal((screen.getByRole('button', { name: 'Reject ok-1' }) as HTMLButtonElement).disabled, true, 'reject needs a note')
    fireEvent.change(screen.getByLabelText('Note for the next prompt (ok-1)'), { target: { value: 'too bright' } })
    assert.equal((screen.getByRole('button', { name: 'Reject ok-1' }) as HTMLButtonElement).disabled, false)
    fireEvent.click(screen.getByRole('button', { name: 'Approve all without warnings' }))
    await screen.findByText('Hero')
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.deepEqual(confirms, ['Approve 1 assets that have no warnings?'])
    const approved = calls.filter(item => item.includes('/approve'))
    assert.deepEqual(approved, ['POST /api/v1/games/bosque/assets/heroe/approve'], 'the chest has two undecided candidates and is skipped')
  } finally {
    cleanup()
    reset()
  }
})

test('style-check warnings and the style score read as text in English and Spanish', { concurrency: false }, async () => {
  const { render, screen, cleanup, within } = await import('@testing-library/react')
  const { GameReviewPanel } = await import('../src/features/game-assets/GameReviewPanel.tsx')
  const { setUiLanguage } = await import('../src/i18n/index.ts')
  const current = game()
  current.assets = [{
    id: 'heroe', kind: 'character', name: 'Hero', description: '', status: 'review', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, approvedAttemptId: null,
    attempts: [attempt('h-a1', ['style_mismatch', 'style_check_unavailable', { code: 'style_check_failed', message: 'analyze timed out' }, 'duplicate_of:slime'], { metrics: { styleScore: 2 } })],
  }]
  useGameAssetsStore.setState({ workspace: 'lab', ready: true, games: [current], game: current, serverRevision: 3, error: null, notice: null, produceJob: null, selectedIds: [], section: 'review' })
  try {
    const view = render(<GameReviewPanel />)
    const card = screen.getByRole('region', { name: 'Candidate h-a1' })
    for (const text of [
      'The style does not match the references.', 'The style check could not run.', 'The style check failed.',
      'Looks like a duplicate of slime.', 'Style match (1–5): 2',
    ]) assert.ok(within(card).getByText(text), text)
    for (const raw of ['style_mismatch', 'style_check', 'styleScore', 'duplicate_of']) assert.ok(!card.textContent?.includes(raw), raw)
    view.unmount()
    await setUiLanguage('es')
    render(<GameReviewPanel />)
    const spanish = screen.getByRole('region', { name: 'Candidato h-a1' })
    for (const text of ['El estilo no encaja con las referencias.', 'No se pudo comprobar el estilo.', 'La comprobación de estilo falló.', 'Encaje con el estilo (1–5): 2']) {
      assert.ok(within(spanish).getByText(text), text)
    }
  } finally {
    await setUiLanguage('en')
    cleanup()
    reset()
  }
})

test('the sprite sheet steps frames on their duration', { concurrency: false }, async () => {
  const { render, cleanup, act } = await import('@testing-library/react')
  const { SpriteSheetPlayer } = await import('../src/features/game-assets/SpriteSheetPlayer.tsx')
  mock.timers.enable({ apis: ['setTimeout'] })
  try {
    render(<SpriteSheetPlayer imageUrl="" atlas={{ frames: { a: { frame: { x: 0, y: 0, w: 4, h: 4 }, duration: 100 }, b: { frame: { x: 4, y: 0, w: 4, h: 4 }, duration: 100 } } }} pixel />)
    assert.equal(document.querySelector('canvas')?.getAttribute('data-frame'), '0')
    await act(async () => { mock.timers.tick(100) })
    assert.equal(document.querySelector('canvas')?.getAttribute('data-frame'), '1')
  } finally {
    mock.timers.reset()
    cleanup()
  }
})

test('music loops with Web Audio at the file rate, with an inclusive loop end, and closes on unmount', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { MusicLoopPlayer } = await import('../src/features/game-assets/AudioLoopPlayer.tsx')
  const sources: Record<string, unknown>[] = []
  let closed = 0
  class FakeContext {
    state = 'running'
    currentTime = 0
    destination = {}
    async decodeAudioData() { return { sampleRate: 48000, duration: 2, length: 96000 } }
    createBufferSource() {
      const source: Record<string, unknown> = { connect() {}, disconnect() {}, stop() {}, start(...args: unknown[]) { source.started = args } }
      sources.push(source)
      return source
    }
    async resume() {}
    async close() { closed += 1; this.state = 'closed' }
  }
  const header = new DataView(new ArrayBuffer(44))
  ;[...'RIFF'].forEach((char, index) => header.setUint8(index, char.charCodeAt(0)))
  ;[...'WAVEfmt '].forEach((char, index) => header.setUint8(8 + index, char.charCodeAt(0)))
  header.setUint32(16, 16, true)
  header.setUint32(24, 44100, true)
  const realFetch = globalThis.fetch
  Object.assign(globalThis, { AudioContext: FakeContext, fetch: async () => new Response(header.buffer, { status: 200 }) })
  try {
    const view = render(<MusicLoopPlayer url="/api/v1/file/game/tema.wav?workspace=lab" loop={{ start: 0, end: 44099 }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Listen to the seam' }))
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.equal(sources.length, 1)
    assert.equal(sources[0].loop, true)
    assert.equal(sources[0].loopStart, 0)
    assert.equal(sources[0].loopEnd, 1, '(44099 + 1) / 44100, not / 48000')
    assert.deepEqual(sources[0].started, [0, 0])
    view.unmount()
    assert.equal(closed, 1)
  } finally {
    Object.assign(globalThis, { fetch: realFetch })
    delete (globalThis as { AudioContext?: unknown }).AudioContext
    cleanup()
  }
})
