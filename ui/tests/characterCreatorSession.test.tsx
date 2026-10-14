import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { characterStyle } from '../src/lib/characterStyles'
import { candidateCount, generateKeyedCandidates, type CandidateDependencies, type KeyedCandidate } from '../src/features/characters/characterCandidates'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const style = characterStyle('graphic-novel')!
const sleep = (ms: number) => new Promise(done => setTimeout(done, ms))

/** Pictures and keying that come from the test, and a log of what was asked and when. */
function fakes(log: string[] = [], hold?: Promise<void>): Partial<CandidateDependencies> {
  let seed = 0
  return {
    seed: () => ++seed,
    generate: async (_provider, _prompt, _model, _reference, _negative, options) => {
      log.push(`draw:${options?.seed}${options?.existingJobId ? `:resumed ${options.existingJobId}` : ''}`)
      if (!options?.existingJobId) options?.onJobSubmitted?.(`job-${options?.seed}`)
      if (hold) await hold
      return { source: `/api/v1/file/raw-${options?.seed}.png?workspace=cast` } as never
    },
    key: async details => {
      log.push(`key:${String(details.source).split('/').pop()?.split('.')[0]}`)
      return { file: 'k.png', url: `/api/v1/file/keyed-${String(details.source).split('/').pop()}`, sha256: 'x' }
    },
    check: async () => ({ ready: true, reasons: [], face: { box: [0, 0, 1, 1], confidence: 1 } }),
  }
}
const request = (extra: Partial<Parameters<typeof generateKeyedCandidates>[0]> = {}) => ({
  workspace: 'cast', style, kind: 'character' as const, description: 'Un conquistador español de 20 años.', model: 'qwen_image_21',
  signal: new AbortController().signal, onUpdate: () => {}, ...extra,
})

test('every picture is drawn before any background is removed, so the image model is not interrupted', async () => {
  const log: string[] = []
  const found = await generateKeyedCandidates(request(), fakes(log))
  assert.deepEqual(log, ['draw:1', 'draw:2', 'draw:3', 'key:raw-1', 'key:raw-2', 'key:raw-3'])
  assert.deepEqual(found.map(item => item.status), ['ready', 'ready', 'ready'])
})

test('once one is picked only that one has its background removed; the others stay as drawn', async () => {
  const log: string[] = []
  const found = await generateKeyedCandidates(request({ picked: () => 'candidate-2' }), fakes(log))
  assert.deepEqual(log.filter(line => line.startsWith('key')), ['key:raw-2'])
  assert.deepEqual(found.map(item => item.status), ['drawn', 'ready', 'drawn'])
  assert.ok(found[0].raw && !found[0].keyed, 'it can still be picked, and is keyed then')
})

test('one to three options can be asked for, and more or fewer are brought into range', async () => {
  for (const [asked, made] of [[1, 1], [2, 2], [3, 3], [9, 3], [0, 1], [undefined, 3]] as const) {
    const log: string[] = []
    const found = await generateKeyedCandidates(request({ count: asked }), fakes(log))
    assert.equal(found.length, made, `asked ${asked}`)
    assert.equal(log.filter(line => line.startsWith('draw')).length, made)
  }
  assert.equal(candidateCount(2.4), 2)
})

test('options from an earlier run are followed, not drawn again: a picture still drawing is followed by its job', async () => {
  const log: string[] = []
  const existing: KeyedCandidate[] = [
    { id: 'candidate-1', seed: 5, status: 'drawn', raw: '/api/v1/file/raw-5.png?workspace=cast', screen: 'green' },
    { id: 'candidate-2', seed: 6, status: 'generating', jobId: 'img-77', screen: 'green' },
  ]
  const found = await generateKeyedCandidates(request({ existing }), fakes(log))
  assert.deepEqual(log.filter(line => line.startsWith('draw')), ['draw:6:resumed img-77'])
  assert.deepEqual(found.map(item => item.status), ['ready', 'ready'])
})

function stubServer() {
  const calls: string[] = []
  const original = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${String(input)}`)
    return new Response(JSON.stringify({ outputs: [], total: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  return { calls, restore: () => { globalThis.fetch = original } }
}

async function sessions() {
  const module = await import('../src/features/characters/characterCreatorSession')
  module.forgetCreatorSessions(); localStorage.clear()
  return module
}

test('leaving the screen does not stop the run or cancel its jobs, and coming back shows where it got to', async t => {
  const { render, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { CharacterStyleCreator } = await import('../src/features/characters/CharacterStyleCreator')
  const { CharacterCreatorSession, registerCreatorSession } = await sessions()
  const server = stubServer(); t.after(() => { server.restore(); cleanup() })
  let release: () => void = () => {}
  const session = new CharacterCreatorSession('cast', fakes([], new Promise<void>(done => { release = done })))
  registerCreatorSession(session)

  const first = render(<CharacterStyleCreator workspace="cast" style={style} model="qwen_image_21" />)
  fireEvent.change(first.getByLabelText('Character name'), { target: { value: 'John' } })
  fireEvent.change(first.getByLabelText('Character description'), { target: { value: 'Un conquistador español de 20 años.' } })
  fireEvent.click(first.getByRole('button', { name: 'Create 3 options' }))
  await waitFor(() => assert.equal(session.snapshot().candidates.length, 3))
  first.unmount() // the person goes to another tab to look at the pictures

  release()
  await waitFor(() => assert.ok(session.snapshot().candidates.every(item => item.status === 'ready')))
  assert.equal(server.calls.filter(call => call.includes('/api/v1/cancel/')).length, 0, 'no job was cancelled by leaving')

  const back = render(<CharacterStyleCreator workspace="cast" style={style} model="qwen_image_21" />)
  assert.equal((back.getByLabelText('Character name') as HTMLInputElement).value, 'John')
  assert.match((back.getByLabelText('Character description') as HTMLTextAreaElement).value, /conquistador/)
  for (const number of [1, 2, 3]) assert.equal((back.getByRole('button', { name: `Option ${number}` }) as HTMLButtonElement).disabled, false)
})

test('the draft is kept in the browser: a reloaded page has the name, the options and the pick', async t => {
  const { CharacterCreatorSession } = await sessions()
  const server = stubServer(); t.after(server.restore)
  const session = new CharacterCreatorSession('cast', fakes())
  session.edit({ name: 'John', description: 'Un conquistador', count: 2 })
  await session.createOptions({ style, model: 'qwen_image_21' })
  session.pick('candidates', 'candidate-2')

  const reloaded = new CharacterCreatorSession('cast').snapshot()
  assert.equal(reloaded.name, 'John'); assert.equal(reloaded.count, 2)
  assert.deepEqual(reloaded.candidates.map(item => [item.id, item.status]), [['candidate-1', 'ready'], ['candidate-2', 'ready']])
  assert.equal(reloaded.picked, 'candidate-2')
  assert.equal(reloaded.busy, '', 'a run is not kept, only what it made')
  assert.equal(new CharacterCreatorSession('other').snapshot().name, '', 'each workspace has its own')
})

test('a reloaded page follows the picture that was still being drawn by its job, and draws again the one whose job it never learned', async t => {
  const { CharacterCreatorSession } = await sessions()
  const server = stubServer(); t.after(server.restore)
  localStorage.setItem('hocuspocus.characterCreator.v1:cast', JSON.stringify({ version: 1, draft: {
    styleId: 'graphic-novel', model: 'qwen_image_21', name: 'John', description: 'Un conquistador', count: 3, draftId: 'character-x',
    candidates: [
      { id: 'candidate-1', seed: 1, status: 'drawn', raw: '/api/v1/file/raw-1.png?workspace=cast', screen: 'green' },
      { id: 'candidate-2', seed: 2, status: 'generating', jobId: 'img-9', screen: 'green' },
      { id: 'candidate-3', seed: 3, status: 'generating', screen: 'green' },
    ], pose: '', poseCandidates: [] } }))
  const log: string[] = []
  const session = new CharacterCreatorSession('cast', fakes(log))
  assert.deepEqual(session.snapshot().candidates.map(item => item.status), ['drawn', 'generating', 'generating'])

  session.resume({ style, model: 'qwen_image_21' })
  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => assert.equal(session.snapshot().busy, ''))
  assert.deepEqual(log.filter(line => line.startsWith('draw')), ['draw:2:resumed img-9', 'draw:3'])
  assert.deepEqual(session.snapshot().candidates.map(item => item.status), ['ready', 'ready', 'ready'])
})

test('requests that fail because the page is being closed are not saved as failed pictures', async t => {
  const { CharacterCreatorSession } = await sessions()
  const { waitFor } = await import('@testing-library/react')
  const server = stubServer(); t.after(() => { server.restore(); window.dispatchEvent(new window.Event('pageshow')) })
  let fail: (reason: Error) => void = () => {}
  const session = new CharacterCreatorSession('cast', fakes([], new Promise<void>((_, reject) => { fail = reject })))
  session.edit({ name: 'John', description: 'Un conquistador', count: 2 })
  const running = session.createOptions({ style, model: 'qwen_image_21' })
  await waitFor(() => assert.equal(session.snapshot().candidates.length, 2))

  window.dispatchEvent(new window.Event('pagehide')) // a reload: every request in flight now fails
  fail(new TypeError('Failed to fetch')); await running
  assert.deepEqual(session.snapshot().candidates.map(item => item.status), ['failed', 'failed'], 'this page, about to go, shows them failed')
  const saved = JSON.parse(localStorage.getItem('hocuspocus.characterCreator.v1:cast') ?? '{}').draft.candidates as KeyedCandidate[]
  assert.deepEqual(saved.map(item => [item.status, item.jobId]), [['generating', 'job-1'], ['generating', 'job-2']], 'what is saved is what the next page follows')
})

test('picking a drawn option removes only its background; Cancel stops the jobs and keeps what was drawn', async t => {
  const { CharacterCreatorSession } = await sessions()
  const server = stubServer(); t.after(server.restore)
  const log: string[] = []
  localStorage.setItem('hocuspocus.characterCreator.v1:cast', JSON.stringify({ version: 1, draft: {
    styleId: 'graphic-novel', name: 'John', description: 'Un conquistador', count: 3, draftId: 'character-x', pose: '', poseCandidates: [],
    candidates: [1, 2, 3].map(number => ({ id: `candidate-${number}`, seed: number, status: 'drawn', raw: `/api/v1/file/raw-${number}.png?workspace=cast`, screen: 'green' })) } }))
  const session = new CharacterCreatorSession('cast', fakes(log))
  session.pick('candidates', 'candidate-3')
  const { waitFor } = await import('@testing-library/react')
  await waitFor(() => assert.equal(session.snapshot().candidates[2].status, 'ready'))
  assert.deepEqual(log, ['key:raw-3'])
  assert.deepEqual(session.snapshot().candidates.map(item => item.status), ['drawn', 'drawn', 'ready'])

  let release: () => void = () => {}
  const running = new CharacterCreatorSession('busy', fakes([], new Promise<void>(done => { release = done })))
  running.edit({ name: 'Ana', description: 'Una marinera' })
  const done = running.createOptions({ style, model: 'qwen_image_21' })
  await waitFor(() => assert.equal(running.snapshot().candidates.length, 3))
  running.cancel()
  assert.deepEqual(server.calls.filter(call => call.includes('/api/v1/cancel/')).sort(),
    ['POST /api/v1/cancel/job-1', 'POST /api/v1/cancel/job-2', 'POST /api/v1/cancel/job-3'])
  assert.deepEqual(running.snapshot().candidates.map(item => item.error), ['cancelled', 'cancelled', 'cancelled'])
  assert.equal(running.snapshot().busy, '')
  release(); await done
  running.reset()
  assert.deepEqual(running.snapshot().candidates, [])
  assert.equal(running.snapshot().name, '', 'a new character: the name and the description are cleared')
  assert.equal(running.snapshot().count, 3)
})

test('with no style the image, the name and the saved mark are kept for the next visit, and Start over begins another character', async t => {
  const { CharacterCreatorSession } = await sessions()
  const requests: string[] = []
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET'
    requests.push(`${method} ${url}`)
    const body = init?.body ? JSON.parse(String(init.body)) as { kit?: { id: string } } : undefined
    const reply = url.includes('/character-kits/library') ? { version: 1, revision: 4, activeKitId: null, kits: {} }
      : method === 'PATCH' ? { version: 1, revision: 5, kits: { [body!.kit!.id]: body!.kit } } : { outputs: [], total: 0 }
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const session = new CharacterCreatorSession('cast', fakes())
  session.editFree({ name: 'Ana', description: 'Una marinera pelirroja' })
  await session.generateFree({ model: 'qwen_image_21' })
  assert.match(session.snapshot().free.draft?.base?.source ?? '', /^\/api\/v1\/file\/raw-/)
  assert.equal(session.snapshot().message, 'imageCreator.review')
  await session.saveFree()
  assert.equal(session.snapshot().free.saved, true)
  assert.ok(requests.some(call => call.startsWith('PATCH ')), 'it was saved in the library')

  const next = new CharacterCreatorSession('cast').snapshot().free
  assert.deepEqual([next.name, next.saved, next.draft?.base?.source], ['Ana', true, session.snapshot().free.draft?.base?.source])
  assert.equal(new CharacterCreatorSession('cast').snapshot().styleId, '', 'the free mode is the one it was left in')

  session.resetFree()
  assert.deepEqual(session.snapshot().free, { name: '', description: '', saved: false })
  session.setStyle('graphic-novel'); session.edit({ name: 'John' })
  session.resetFree()
  assert.equal(session.snapshot().styleId, 'graphic-novel', 'starting over the free character does not change the style')
})

test('the options to make are chosen from one to three', async t => {
  const { render, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { CharacterStyleCreator } = await import('../src/features/characters/CharacterStyleCreator')
  const { CharacterCreatorSession, registerCreatorSession } = await sessions()
  const server = stubServer(); t.after(() => { server.restore(); cleanup() })
  const log: string[] = []
  registerCreatorSession(new CharacterCreatorSession('cast', fakes(log)))
  const view = render(<CharacterStyleCreator workspace="cast" style={style} model="qwen_image_21" />)
  fireEvent.change(view.getByLabelText('Character name'), { target: { value: 'John' } })
  fireEvent.change(view.getByLabelText('Character description'), { target: { value: 'Un conquistador' } })
  const group = view.getByRole('group', { name: 'Options' })
  assert.equal(group.querySelectorAll('button').length, 3)
  assert.equal(view.getByRole('button', { name: '3' }).getAttribute('aria-pressed'), 'true', 'three by default')
  fireEvent.click(view.getByRole('button', { name: '1' }))
  fireEvent.click(view.getByRole('button', { name: 'Create 1 option' }))
  await waitFor(() => assert.equal((view.getByRole('button', { name: 'Option 1' }) as HTMLButtonElement).disabled, false))
  assert.equal(view.queryByRole('button', { name: 'Option 2' }), null)
  assert.equal(log.filter(line => line.startsWith('draw')).length, 1)
})

/** A pointer event of the given kind: jsdom has no PointerEvent, and React reads pointerType from the event. */
function pointer(target: Element, type: string, pointerType: string, position = { clientX: 5, clientY: 5 }) {
  const event = new dom.window.Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, { pointerType: { value: pointerType }, ...Object.fromEntries(Object.entries(position).map(([key, value]) => [key, { value }])) })
  return target.dispatchEvent(event)
}

test('an option opens large when the mouse rests on it, and when it is pressed and held on a touch screen', async t => {
  const { render, cleanup, waitFor, act } = await import('@testing-library/react')
  const { CandidateGrid } = await import('../src/features/characters/CandidateGrid')
  t.after(cleanup)
  const picked: string[] = []
  const candidates: KeyedCandidate[] = [{ id: 'candidate-1', seed: 1, status: 'drawn', raw: '/api/v1/file/raw-1.png?workspace=cast' },
    { id: 'candidate-2', seed: 2, status: 'ready', raw: '/api/v1/file/raw-2.png?workspace=cast', keyed: '/api/v1/file/keyed-2.png?workspace=cast' }]
  const view = render(<CandidateGrid candidates={candidates} locked={false} onPick={item => picked.push(item.id)} />)
  const peek = () => document.querySelector('[data-testid="candidate-peek"] img')?.getAttribute('src') ?? null
  const first = view.getByRole('button', { name: 'Option 1' }), second = view.getByRole('button', { name: 'Option 2' })

  act(() => { pointer(first, 'pointerover', 'mouse') })
  await waitFor(() => assert.equal(peek(), '/api/v1/file/raw-1.png?workspace=cast'))
  act(() => { pointer(first, 'pointerout', 'mouse') })
  await waitFor(() => assert.equal(peek(), null))
  act(() => { pointer(second, 'pointerover', 'mouse') })
  await waitFor(() => assert.equal(peek(), '/api/v1/file/keyed-2.png?workspace=cast'), { timeout: 2000 })
  act(() => { pointer(second, 'pointerout', 'mouse') })

  // Touch: nothing at first, large after a long press, and the tap that ends it does not pick the option.
  act(() => { pointer(first, 'pointerdown', 'touch') })
  assert.equal(peek(), null)
  await waitFor(() => assert.equal(peek(), '/api/v1/file/raw-1.png?workspace=cast'), { timeout: 2000 })
  act(() => { pointer(first, 'pointerup', 'touch') })
  assert.equal(peek(), null, 'it closes when the finger lifts')
  act(() => { first.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })) })
  assert.deepEqual(picked, [], 'the long press did not pick')
  act(() => { first.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })) })
  assert.deepEqual(picked, ['candidate-1'], 'a plain tap after it does')

  // A quick tap, or one that slides away, shows nothing.
  act(() => { pointer(second, 'pointerdown', 'touch'); pointer(second, 'pointermove', 'touch', { clientX: 80, clientY: 5 }) })
  await sleep(600)
  assert.equal(peek(), null)
})
