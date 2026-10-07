import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { playtestScene, type PlayScene } from '../src/features/game-assets/playtestScene.ts'
import { PlaytestRuntime, type MusicPlayer, type SoundPlayer } from '../src/features/game-assets/playtestRuntime.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import type { Game, GameAsset, GameAttempt } from '../src/features/game-assets/types.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  HTMLCanvasElement: dom.window.HTMLCanvasElement,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

/** Every image is a loaded 60×60 picture. */
class FakeImage {
  src = ''
  complete = true
  naturalWidth = 60
  naturalHeight = 60
  removeAttribute(name: string) { if (name === 'src') this.src = '' }
}
Object.assign(globalThis, { Image: FakeImage })

interface Call { name: string; args: unknown[] }

function fakeContext(): { ctx: CanvasRenderingContext2D; calls: Call[] } {
  const calls: Call[] = []
  const state: Record<string | symbol, unknown> = {}
  const ctx = new Proxy(state, {
    get: (target, prop) => (prop in target ? target[prop] : (...args: unknown[]) => { calls.push({ name: String(prop), args }) }),
    set: (target, prop, value) => { target[prop] = value; return true },
  })
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls }
}

function frameQueue() {
  let next = 1
  const queue = new Map<number, FrameRequestCallback>()
  const cancelled: number[] = []
  return {
    queue, cancelled,
    request: (callback: FrameRequestCallback) => { const id = next; next += 1; queue.set(id, callback); return id },
    cancel: (id: number) => { cancelled.push(id); queue.delete(id) },
    run(now: number) { const pending = [...queue.values()]; queue.clear(); for (const callback of pending) callback(now) },
  }
}

function fakeMusic() {
  const log: string[] = []
  const made: { url: string; loop: unknown }[] = []
  const create = (url: string, loop: { start: number; end: number } | null): MusicPlayer => {
    made.push({ url, loop })
    return {
      play: async () => { log.push('play') }, stop: () => log.push('stop'), suspend: () => log.push('suspend'),
      resume: () => log.push('resume'), close: () => log.push('close'),
    }
  }
  return { log, made, create }
}

function fakeSounds() {
  const made: { url: string; paused: boolean }[] = []
  const create = (url: string): SoundPlayer => {
    const row = { url, paused: false }
    made.push(row)
    return { play: async () => undefined, pause: () => { row.paused = true }, addEventListener: () => undefined }
  }
  return { made, create }
}

function attempt(id: string, files: Record<string, string>, patch: Partial<GameAttempt> = {}): GameAttempt {
  return { id, status: 'ok', files, ...patch }
}

function asset(partial: Partial<GameAsset> & Pick<GameAsset, 'id' | 'kind'>): GameAsset {
  const attempts = partial.attempts || [attempt(`${partial.id}-a`, { main: `${partial.id}/main.png` })]
  return {
    name: partial.id, description: '', status: 'approved', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false,
    approvedAttemptId: attempts[0]?.id || null, ...partial, attempts,
  }
}

function game(assets: GameAsset[]): Game {
  return {
    id: 'bosque', title: 'Bosque', revision: 1, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [], assets,
    style: {
      revision: 1, approval: 'approved', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
  }
}

function walkAtlas(mirror: boolean) {
  return {
    frames: { walk_0: { frame: { x: 0, y: 0, w: 20, h: 30 }, duration: 100 }, walk_1: { frame: { x: 20, y: 0, w: 20, h: 30 }, duration: 100 } },
    meta: { frameTags: [{ name: 'walk', from: 0, to: 1 }], pivot: { x: 10, y: 29 }, mirror, loop: { walk: true } },
  }
}

function heroGame(): Game {
  return game([
    asset({ id: 'hero', kind: 'character', spec: { role: 'player' } }),
    asset({ id: 'walk', kind: 'animation', spec: { character: 'hero', action: 'walk', loop: true }, attempts: [attempt('w', { sheet: 'walk/sheet.png', main: 'walk/sheet.png', atlas: 'walk/sheet.json' })] }),
    asset({ id: 'theme', kind: 'music', attempts: [attempt('m', { wav: 'theme/take 1.wav', ogg: 'theme/take.ogg' }, { metrics: { loopStart: 4800, loopEnd: 95999 } })] }),
    asset({ id: 'salto', kind: 'sfx', spec: { trigger: 'jump' }, attempts: [attempt('s', { 0: 'jump/0.wav', 1: 'jump/1.wav' })] }),
  ])
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

function runtimeFor(scene: PlayScene, atlas: unknown) {
  const { ctx, calls } = fakeContext()
  const frames = frameQueue()
  const music = fakeMusic()
  const sounds = fakeSounds()
  const runtime = new PlaytestRuntime(ctx, 'lab one', {
    requestFrame: frames.request, cancelFrame: frames.cancel, fetchJson: async () => atlas, createMusic: music.create, createSound: sounds.create,
  })
  runtime.setScene(scene)
  runtime.start()
  return { runtime, calls, frames, music, sounds }
}

test('music waits for a gesture, loops the WAV between its sample points and everything stops on dispose', async () => {
  const { runtime, calls, frames, music, sounds } = runtimeFor(playtestScene(heroGame()), walkAtlas(true))
  frames.run(16)
  assert.equal(music.made.length, 0, 'no AudioContext before a key or click')
  assert.equal(runtime.key('a', true), false)
  assert.equal(runtime.key(' ', true), true)
  assert.deepEqual(music.made, [{ url: '/api/v1/file/theme/take%201.wav?workspace=lab%20one', loop: { start: 4800, end: 95999 } }])
  assert.deepEqual(music.log, ['play'])
  frames.run(32)
  assert.deepEqual(sounds.made.map(item => item.url), ['/api/v1/file/jump/0.wav?workspace=lab%20one'])
  runtime.setHidden(true)
  assert.equal(runtime.keys.jump, false, 'a hidden tab releases held keys')
  assert.deepEqual(music.log.slice(-1), ['suspend'])
  runtime.setHidden(false)
  runtime.dispose()
  assert.equal(frames.queue.size, 0, 'no frame stays scheduled')
  assert.ok(frames.cancelled.length === 1)
  assert.deepEqual(music.log.slice(-2), ['resume', 'close'])
  assert.ok(sounds.made.every(item => item.paused))
  const painted = calls.length
  frames.run(48)
  await flush()
  assert.equal(calls.length, painted, 'nothing paints after dispose')
  runtime.unlockAudio()
  assert.equal(music.made.length, 1)
})

test('muted play makes no sound; sound effect variants take turns', () => {
  const { runtime, frames, sounds } = runtimeFor(playtestScene(heroGame()), walkAtlas(true))
  runtime.setMuted(true)
  runtime.key(' ', true)
  frames.run(16)
  assert.equal(sounds.made.length, 0)
  runtime.setMuted(false)
  for (let now = 32; now < 5000 && sounds.made.length < 2; now += 16) frames.run(now) // holding Space bounces
  assert.deepEqual(sounds.made.slice(0, 2).map(item => item.url.split('?')[0]), ['/api/v1/file/jump/0.wav', '/api/v1/file/jump/1.wav'])
  runtime.dispose()
})

async function walkLeft(mirror: boolean) {
  const { runtime, calls, frames } = runtimeFor(playtestScene(heroGame()), walkAtlas(mirror))
  runtime.setMuted(true)
  runtime.key('ArrowLeft', true)
  frames.run(16)
  await flush() // the atlas arrives
  calls.length = 0
  frames.run(32)
  const x = Math.round((runtime as unknown as { body: { x: number } }).body.x)
  runtime.dispose()
  return { calls, x }
}

test('facing left mirrors the walk only when its sheet allows it, around the pivot', async () => {
  const { calls: mirrored, x } = await walkLeft(true)
  const scale = mirrored.findIndex(call => call.name === 'scale')
  assert.deepEqual(mirrored[scale]?.args, [-1, 1])
  const translate = mirrored[scale - 1]
  const draw = mirrored[scale + 1]
  assert.equal(translate?.name, 'translate')
  assert.deepEqual(draw?.args.slice(1, 5), [0, 0, 20, 30], 'one 20×30 cell of the sheet, not the whole sheet')
  // translate(left + w, top): the pivot column (10) of a 20 px frame lands on left + 20 - 1 - 10.
  const [right, top] = translate.args as number[]
  assert.equal(top, 299 - 29, 'the feet row sits on the ground')
  assert.equal(right - 1 - 10, x, 'the pivot column stays on the hero position')

  const { calls: kept, x: keptX } = await walkLeft(false)
  assert.ok(!kept.some(call => call.name === 'scale'), 'meta.mirror false: no flipped sprite')
  const frame = kept.find(call => call.name === 'drawImage' && call.args.length === 9)
  assert.deepEqual(frame?.args.slice(5, 7), [keptX - 10, 299 - 29])
})

test('a refreshed copy of the same scene keeps the hero where it is', () => {
  const { runtime, frames } = runtimeFor(playtestScene(heroGame()), walkAtlas(true))
  runtime.setMuted(true)
  runtime.key('ArrowRight', true)
  for (let now = 16; now <= 640; now += 16) frames.run(now)
  const before = (runtime as unknown as { body: { x: number } }).body.x
  assert.ok(before > 120)
  runtime.setScene(JSON.parse(JSON.stringify(playtestScene(heroGame()))) as PlayScene)
  frames.run(656)
  assert.ok((runtime as unknown as { body: { x: number } }).body.x >= before)
  runtime.dispose()
})

function start(current: Game) {
  useGameAssetsStore.setState({ workspace: 'lab', ready: true, games: [current], game: current, serverRevision: 1, error: null, problems: [], notice: null, section: 'play' })
}

test('the playtest canvas is labelled, takes keys only while focused and leaves nothing running after unmount', { concurrency: false }, async () => {
  const { render, screen, cleanup, fireEvent, act } = await import('@testing-library/react')
  const { GamePlaytest } = await import('../src/features/game-assets/GamePlaytest.tsx')
  const frames = frameQueue()
  const { ctx } = fakeContext()
  let contexts = 0
  Object.assign(globalThis, { requestAnimationFrame: frames.request, cancelAnimationFrame: frames.cancel })
  dom.window.HTMLCanvasElement.prototype.getContext = (() => { contexts += 1; return ctx }) as never
  const removed: string[] = []
  const remove = document.removeEventListener.bind(document)
  document.removeEventListener = ((type: string, listener: EventListener) => { removed.push(type); remove(type, listener) }) as typeof document.removeEventListener
  const rejections: unknown[] = []
  const onRejection = (reason: unknown) => rejections.push(reason)
  process.on('unhandledRejection', onRejection)
  start(heroGame())
  try {
    const view = render(<><textarea aria-label="Notes" /><GamePlaytest /></>)
    const canvas = screen.getByRole('application', { name: 'Side-view playtest' })
    const help = document.getElementById(canvas.getAttribute('aria-describedby') || '')
    assert.ok(help?.textContent?.includes('Arrows move'))
    assert.equal(canvas.getAttribute('tabindex'), '0')
    assert.ok(screen.getByText('Hero animation: idle'))
    assert.ok(!document.body.textContent?.includes('sfx:'))
    assert.equal(screen.getByRole('button', { name: 'Mute' }).getAttribute('aria-pressed'), 'false')
    assert.equal(fireEvent.keyDown(screen.getByLabelText('Notes'), { key: ' ' }), true, 'Space still types in other fields')
    assert.equal(fireEvent.keyDown(canvas, { key: 'Tab' }), true)
    assert.equal(fireEvent.keyDown(canvas, { key: 'ArrowRight' }), false, 'the game keeps the arrow from scrolling the page')
    await act(async () => { await flush() })
    // No Web Audio in this test: the music failure is shown, not thrown.
    assert.ok(screen.getByRole('alert').textContent?.includes('Could not play this audio.'))
    assert.equal(frames.queue.size, 1)
    act(() => { useGameAssetsStore.setState({ game: JSON.parse(JSON.stringify(heroGame())) as Game }) })
    assert.equal(contexts, 1, 'a refresh with the same media does not restart the game')
    view.unmount()
    assert.equal(frames.queue.size, 0, 'no animation frame after unmount')
    assert.ok(removed.includes('visibilitychange'))
    await flush()
    assert.deepEqual(rejections, [])
  } finally {
    process.off('unhandledRejection', onRejection)
    document.removeEventListener = remove as typeof document.removeEventListener
    cleanup()
    stopGamePolling()
    useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], section: 'setup' })
  }
})
