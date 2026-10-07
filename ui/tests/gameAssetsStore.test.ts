import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { createGame, GameApiError, GameRevisionConflict, setGameFetch } from '../src/api/gameAssets.ts'
import { colorsFromImageData, isHexColor, newCharacterId, truncateId } from '../src/features/game-assets/styles.ts'
import { stopGamePolling, useGameAssetsStore } from '../src/features/game-assets/store.ts'
import { canResumeJob, pollDelay } from '../src/features/game-assets/storeModel.ts'
import type { Game, GameAsset } from '../src/features/game-assets/types.ts'

function sample(revision: number, title: string, assets: GameAsset[] = []): Game {
  return {
    id: 'bosque', title, revision, createdAt: '', updatedAt: '', genre: 'platformer', view: 'side', exports: [],
    assets,
    style: {
      revision: 1, approval: 'draft', approvedAt: null, preset: 'pixel-16', traits: 'flat', negative: 'photo',
      palette: ['#112233'], paletteMode: 'locked', light: 'top-left', screen: 'magenta', references: [],
      pixel: { enabled: true, spriteHeight: 48, tile: 16, colors: 16, outline: 'dark-1px', dither: 'none' },
      model3d: { maxTriangles: 3000, texture: 512, look: 'toon' },
      audio: { genre: 'chiptune', instruments: 'square', bpm: [90, 140], musicLufs: -16, sfxPeakDb: -1, sampleRate: 48000 },
    },
  }
}

function character(id: string, name = id): GameAsset {
  return { id, kind: 'character', name, description: '', status: 'pending', tags: [], spec: {}, dependsOn: [], candidates: 1, locked: false, attempts: [], approvedAttemptId: null }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

interface Call { method: string; url: string; body: Record<string, unknown> }

/** ``reply`` answers each request; every request is recorded with its parsed body. */
function serve(reply: (call: Call, index: number) => Response | Promise<Response>): Call[] {
  const calls: Call[] = []
  setGameFetch(async (input, init) => {
    const call = { method: String(init?.method || 'GET'), url: String(input), body: init?.body ? JSON.parse(String(init.body)) : {} }
    calls.push(call)
    return reply(call, calls.length - 1)
  })
  return calls
}

function start(game: Game): void {
  useGameAssetsStore.setState({
    workspace: 'lab', ready: true, games: [game], game, serverRevision: game.revision, unsaved: null, dirty: false, editSeq: 0,
    saving: false, error: null, problems: [], notice: null, produceJob: null, styleJob: null, selectedIds: [], presets: [],
  })
}

function reset(): void {
  stopGamePolling()
  setGameFetch(null)
  useGameAssetsStore.setState({ workspace: '', ready: false, game: null, games: [], unsaved: null, dirty: false, notice: null, error: null, problems: [], produceJob: null })
}

const conflict = () => json({ detail: { code: 'revision_conflict', message: 'revision conflict' } }, 409)

test('a revision conflict reloads the game, keeps the unsaved edit on top and saves it once more', async () => {
  start(sample(2, 'Local'))
  const calls = serve(call => {
    if (call.method === 'PUT' && call.body.base_revision === 2) return conflict()
    if (call.method === 'PUT') return json({ ...sample(5, String((call.body.patch as { title: string }).title)), style: { ...sample(4, '').style, traits: 'server traits' } })
    return json({ ...sample(4, 'Server'), style: { ...sample(4, '').style, traits: 'server traits' } })
  })
  try {
    useGameAssetsStore.getState().patchGame({ title: 'Mine' })
    const saved = await useGameAssetsStore.getState().saveNow()
    const state = useGameAssetsStore.getState()
    assert.equal(saved?.title, 'Mine')
    assert.equal(state.game?.style.traits, 'server traits')
    assert.equal(state.serverRevision, 5)
    assert.equal(state.notice, 'revision_conflict')
    assert.equal(state.saving, false)
    assert.equal(state.dirty, false)
    const puts = calls.filter(call => call.method === 'PUT')
    assert.deepEqual(puts.map(call => call.body.base_revision), [2, 4])
    assert.deepEqual(puts[1].body.patch, { title: 'Mine' })
  } finally {
    reset()
  }
})

test('a second conflict shows the server copy, keeps the notice and resets saving', async () => {
  start(sample(2, 'Local'))
  serve(call => call.method === 'PUT' ? conflict() : json(sample(6, 'Server')))
  try {
    useGameAssetsStore.getState().patchGame({ title: 'Mine' })
    assert.equal(await useGameAssetsStore.getState().saveNow(), null)
    const state = useGameAssetsStore.getState()
    assert.equal(state.game?.title, 'Server')
    assert.equal(state.notice, 'revision_conflict')
    assert.equal(state.saving, false)
    assert.equal(state.unsaved, null)
  } finally {
    reset()
  }
})

test('saves are serialized: an edit made during a save goes out next with the new revision', async () => {
  start(sample(2, 'Local'))
  let release: (() => void) | undefined
  const calls = serve(async call => {
    if (call.method !== 'PUT') return json(sample(2, 'Local'))
    const title = String((call.body.patch as { title: string }).title)
    if (call.body.base_revision === 2) await new Promise<void>(resolve => { release = resolve })
    return json(sample(Number(call.body.base_revision) + 1, title))
  })
  try {
    const store = useGameAssetsStore.getState()
    store.patchGame({ title: 'A' })
    const first = store.saveNow()
    await new Promise(resolve => setImmediate(resolve))
    store.patchGame({ title: 'B' })
    const second = useGameAssetsStore.getState().saveNow()
    assert.equal(first, second, 'a second save joins the one in flight')
    assert.equal(calls.filter(call => call.method === 'PUT').length, 1)
    release?.()
    const saved = await second
    const puts = calls.filter(call => call.method === 'PUT')
    assert.deepEqual(puts.map(call => [call.body.base_revision, (call.body.patch as { title: string }).title]), [[2, 'A'], [3, 'B']])
    assert.equal(saved?.title, 'B')
    assert.equal(useGameAssetsStore.getState().serverRevision, 4)
  } finally {
    reset()
  }
})

test('a failed save keeps the edit, resets saving and shows the translated error with its problems', async () => {
  start(sample(2, 'Local'))
  serve(() => json({ detail: { code: 'out_of_range', message: 'out_of_range', problems: [{ code: 'out_of_range', field: 'pixel.tile', value: 0 }] } }, 422))
  try {
    useGameAssetsStore.getState().patchGame({ style: { pixel: { tile: 0 } } })
    assert.equal(await useGameAssetsStore.getState().saveNow(), null)
    const state = useGameAssetsStore.getState()
    assert.equal(state.saving, false)
    assert.equal(state.dirty, true)
    assert.deepEqual(state.unsaved, { style: { pixel: { tile: 0 } } })
    assert.equal(state.error, 'A number is out of range.')
    assert.equal(state.problems[0].field, 'pixel.tile')
  } finally {
    reset()
  }
})

test('the client throws typed errors; only revision_conflict is a GameRevisionConflict', async () => {
  serve((_call, index) => [
    json({ detail: { code: 'game_exists', message: 'game bosque already exists' } }, 409),
    json({ detail: [{ loc: ['body', 'workspace'], msg: 'Field required', type: 'missing' }] }, 422),
    new Response('not json', { status: 500 }),
  ][index])
  try {
    const exists = await createGame('lab', { id: 'bosque' }).catch(error => error)
    assert.ok(exists instanceof GameApiError)
    assert.ok(!(exists instanceof GameRevisionConflict))
    assert.deepEqual([exists.status, exists.code, exists.serverMessage], [409, 'game_exists', 'game bosque already exists'])
    const invalid = await createGame('', {}).catch(error => error) as GameApiError
    assert.equal(invalid.code, 'invalid_request')
    assert.deepEqual(invalid.problems[0], { code: 'missing', message: 'Field required', field: 'body.workspace' })
    const broken = await createGame('lab', {}).catch(error => error) as GameApiError
    assert.deepEqual([broken.status, broken.code], [500, ''])
  } finally {
    reset()
  }
})

test('store actions catch server errors and translate the code', async () => {
  start(sample(2, 'Local'))
  serve(() => json({ detail: { code: 'already_running', message: 'This game is already being produced' } }, 409))
  try {
    assert.equal(await useGameAssetsStore.getState().startProduce({}), false)
    assert.equal(useGameAssetsStore.getState().error, 'This game is already being produced. Wait for the running job, or cancel it.')
    assert.equal(useGameAssetsStore.getState().notice, null)
    serve(() => json({ detail: { code: 'no_such_code', message: 'Server said no' } }, 400))
    assert.equal(await useGameAssetsStore.getState().duplicateGame(), false)
    assert.equal(useGameAssetsStore.getState().error, 'Server said no')
    serve(() => { throw new TypeError('Failed to fetch') })
    assert.equal(await useGameAssetsStore.getState().createGame(), false)
    assert.equal(useGameAssetsStore.getState().error, 'Could not create the game.')
  } finally {
    reset()
  }
})

test('a review action that hits a conflict reloads the game and shows the notice', async () => {
  start(sample(2, 'Local'))
  const calls = serve(call => call.url.includes('/approve') ? conflict() : json(sample(7, 'Server')))
  try {
    assert.equal(await useGameAssetsStore.getState().approveAttempt('heroe', 'a1'), false)
    const state = useGameAssetsStore.getState()
    assert.equal(state.notice, 'revision_conflict')
    assert.equal(state.serverRevision, 7)
    assert.equal(state.error, null)
    assert.equal(calls.filter(call => call.url.includes('/approve')).length, 1, 'approve is not retried on its own')
  } finally {
    reset()
  }
})

test('switching preset sends only the preset and the screen, then adopts the server style', async () => {
  start(sample(2, 'Local'))
  useGameAssetsStore.setState({ presets: [{ id: 'cartoon-flat', label: { es: 'Cartoon', en: 'Cartoon' }, traits: 'x', negative: 'y', palette: [], pixel: sample(1, '').style.pixel, screenDefault: 'auto', audio: { genre: 'pop', instruments: 'piano', bpm: [80, 120] } }] })
  const fromServer = { ...sample(3, 'Local'), style: { ...sample(3, '').style, preset: 'cartoon-flat', traits: 'flat cartoon', screen: 'auto' } }
  const calls = serve(() => json(fromServer))
  try {
    assert.equal(await useGameAssetsStore.getState().applyPreset('cartoon-flat'), true)
    assert.deepEqual(calls[0].body.patch, { style: { preset: 'cartoon-flat', screen: 'auto' } })
    assert.equal(useGameAssetsStore.getState().game?.style.traits, 'flat cartoon')
    assert.equal(useGameAssetsStore.getState().serverRevision, 3)
  } finally {
    reset()
  }
})

test('a new character keeps its display name and gets a free, short, non-reserved id', async () => {
  const game = sample(2, 'Local', [character('heroe-nandu')])
  start(game)
  const calls = serve(() => json(game))
  try {
    assert.equal(await useGameAssetsStore.getState().addCharacter('Héroe Ñandú'), true)
    const post = calls.find(call => call.url.endsWith('/assets/from-list'))
    assert.deepEqual(post?.body.items, [{ kind: 'character', id: 'heroe-nandu-2', name: 'Héroe Ñandú', description: 'Héroe Ñandú', options: ['jugador'] }])
    assert.equal(post?.body.check, false)
    assert.equal(newCharacterId('CON', []), 'con-personaje')
    const long = newCharacterId(`${'muy-largo-'.repeat(10)}fin`, [])
    assert.ok(long.length <= 64 && !long.endsWith('-'))
    assert.equal(truncateId('a'.repeat(70)), 'a'.repeat(64))
    const crowded = Array.from({ length: 12 }, (_, index) => character(index ? `${'b'.repeat(64 - 3)}-${index + 1}` : 'b'.repeat(64)))
    const free = newCharacterId('b'.repeat(80), crowded)
    assert.ok(free.length <= 64 && !crowded.some(item => item.id === free))
  } finally {
    reset()
  }
})

test('job polling backs off on errors, stops on demand and is cleared when the game changes', async () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  start(sample(2, 'Local'))
  const settle = async () => { for (let round = 0; round < 5; round += 1) await new Promise(resolve => setImmediate(resolve)) }
  const calls = serve(call => {
    if (call.url.endsWith('/produce')) return json({ jobId: 'job-1', gameId: 'bosque', status: 'running', steps: [] })
    if (call.url.includes('/produce/jobs/')) return json({ detail: 'busy' }, 503)
    return json(sample(2, 'Local'))
  })
  const polls = () => calls.filter(call => call.url.includes('/produce/jobs/')).length
  try {
    assert.equal(await useGameAssetsStore.getState().startProduce({}), true)
    mock.timers.tick(1000)
    await settle()
    assert.equal(polls(), 1)
    mock.timers.tick(1999)
    await settle()
    assert.equal(polls(), 1, 'the second poll waits 2 s after one error')
    mock.timers.tick(1)
    await settle()
    assert.equal(polls(), 2)
    stopGamePolling()
    mock.timers.tick(60000)
    await settle()
    assert.equal(polls(), 2, 'no poll after stop')
    serve(call => call.url.includes('/games/otro') ? json({ ...sample(1, 'Otro'), id: 'otro' }) : json({}))
    await useGameAssetsStore.getState().openGame('otro')
    assert.equal(useGameAssetsStore.getState().produceJob, null)
    assert.deepEqual([pollDelay(0), pollDelay(1), pollDelay(3), pollDelay(9)], [1000, 2000, 8000, 30000])
  } finally {
    mock.timers.reset()
    reset()
  }
})

test('resume is offered for cancelled, interrupted, failed and finished-with-waiting jobs', () => {
  const waiting = [{ assetId: 'andar', status: 'skipped', reason: 'waiting_dependency' }]
  assert.equal(canResumeJob({ id: 'j', status: 'cancelled' }), true)
  assert.equal(canResumeJob({ id: 'j', status: 'interrupted' }), true)
  assert.equal(canResumeJob({ id: 'j', status: 'failed' }), true)
  assert.equal(canResumeJob({ id: 'j', status: 'completed', steps: waiting }), true)
  assert.equal(canResumeJob({ id: 'j', status: 'completed', steps: [{ assetId: 'a', status: 'done' }] }), false)
  assert.equal(canResumeJob({ id: 'j', status: 'cancelling', steps: waiting }), false)
})

test('palette colors are hex and median cut keeps separated colors', () => {
  assert.equal(isHexColor('#112233'), true)
  assert.equal(isHexColor('#abc'), false)
  assert.equal(isHexColor('red'), false)
  const data = new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255])
  const colors = colorsFromImageData(data, 2).sort()
  assert.deepEqual(colors, ['#0000ff', '#ff0000'])
})
