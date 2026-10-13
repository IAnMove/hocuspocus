import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit, emptyCharacterKitLibrary } from '../src/lib/characterKit.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver, ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const base = { id: 'ana-base', name: 'Ana', source: '/api/v1/file/ana.png?workspace=w', kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const }
const walk = {
  sheet: { source: '/api/v1/file/ana-walk-sheet-1.png?workspace=w', width: 1480, height: 640, count: 4, columns: 4, rows: 1, cell: { width: 370, height: 640 } },
  frames: [{ id: 'contact', source: '/api/v1/file/c.png' }, { id: 'passing', source: '/api/v1/file/p.png' }], fps: 4, loop: 'loop' as const, facing: 'right' as const, reviewState: 'pending' as const,
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The server the panel talks to: the kit library, and the animation jobs (a request to make one adds a job that the test moves along). */
function server(state: { library: unknown; jobs?: Array<Record<string, unknown>>; posts?: Array<{ url: string; body: Record<string, unknown> }> }) {
  state.jobs ??= []
  state.posts ??= []
  const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/animations/make')) {
      const body = JSON.parse(String(init?.body))
      state.posts!.push({ url, body })
      const job = { jobId: `anim-${state.posts!.length}`, workspace: body.workspace, kitId: body.kitId, animationId: body.animation, title: body.animation, model: body.model ?? 'qwen_image_21',
        status: 'running', stage: 'poses', createdAt: 100 + state.posts!.length, updatedAt: 100, remake: body.pose ?? null, ...(body.custom ? { custom: body.custom } : {}),
        takes: [{ id: 'one', status: 'generating', seed: 1 }, { id: 'two', status: 'waiting', seed: 2 }] }
      state.jobs!.unshift(job)
      return json({ job })
    }
    if (url.includes('/animations/jobs')) return json({ jobs: state.jobs })
    return json(state.library)
  }) as typeof fetch
  return { fetch, state }
}

test('the Characters tab lists the animations of a saved character, plays a made one and shows what the card needs', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  const mine = { sheet: walk.sheet, frames: [{ id: 'pose-1', source: '/api/v1/file/g.png', prompt: 'Anime expression: a wink', label: 'a wink' }], fps: 3, loop: 'once' as const, facing: 'front' as const, reviewState: 'pending' as const, title: 'Mi guiño', view: 'bust' }
  const kit = { ...createCharacterKit('Ana'), id: 'ana', base, animations: { walk, 'mi-guino': mine } }
  const library = { ...emptyCharacterKitLibrary(), revision: 3, activeId: 'ana', kits: { ana: kit } }
  const original = globalThis.fetch
  globalThis.fetch = server({ library }).fetch
  useStore.setState({ models: [{ model_type: 'qwen_image_21', name: 'Qwen Image 2.1', family: 'qwen', architecture: 'qwen_image', is_downloaded: true }] as never })
  try {
    render(<CharacterAnimationsPanel workspace="w" />)
    await waitFor(() => assert.ok(screen.getByTestId('animation-walk')))
    assert.ok(screen.getByTestId('animation-angry') && screen.getByTestId('animation-wave'), 'gestures and anime expressions are listed')
    const card = screen.getByTestId('animation-walk')
    assert.match(card.textContent!, /Por revisar|To review/)
    assert.ok(card.querySelector('[data-testid="animation-player"]'), 'a made animation is played from its sheet')
    assert.match(card.textContent!, /walk-cycle-sheet/)
    assert.match(card.textContent!, /frames 4, columns 4, facing right, step 0\.5/)
    const angry = screen.getByTestId('animation-angry')
    assert.match(angry.textContent!, /Sin hacer|Not made/)
    assert.equal((angry.querySelector('button') as HTMLButtonElement).disabled, false, 'it can be made: the character has a picture and a model is installed')
    fireEvent.click(card.querySelectorAll('button')[0])
    // The author's own animation: the kit keeps one, and the form to describe another is there, ready only with a name and a pose.
    assert.match(screen.getByTestId('animation-mi-guino').textContent!, /Mi guiño/)
    const form = screen.getByTestId('custom-animation-form')
    const create = form.querySelector('button[type="submit"]') as HTMLButtonElement
    assert.equal(create.disabled, true)
    fireEvent.change(form.querySelector('input') as HTMLInputElement, { target: { value: 'Otra' } })
    fireEvent.change(form.querySelector('textarea') as HTMLTextAreaElement, { target: { value: 'Anime expression: a yawn\n\nAnime expression: a big yawn' } })
    assert.equal(create.disabled, false)
    assert.match(create.textContent!, /2 poses/)
    fireEvent.change(form.querySelector('textarea') as HTMLTextAreaElement, { target: { value: Array.from({ length: 7 }, (_, index) => `pose ${index}`).join('\n') } })
    assert.equal(create.disabled, true, 'seven poses are too many')
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('with no saved character the panel says what to do first', async () => {
  const { render, screen, cleanup, waitFor } = await import('@testing-library/react')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  const original = globalThis.fetch
  globalThis.fetch = server({ library: emptyCharacterKitLibrary() }).fetch
  try {
    render(<CharacterAnimationsPanel workspace="empty" />)
    await waitFor(() => assert.match(document.body.textContent!, /Primero crea y guarda un personaje|Create and save a character first/))
    assert.equal(screen.queryByTestId('animation-walk'), null)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

const kitOf = (animations: Record<string, unknown> = {}) => {
  const kit = { ...createCharacterKit('Ana'), id: 'ana', base, animations }
  return { ...emptyCharacterKitLibrary(), revision: 3, activeId: 'ana', kits: { ana: kit } }
}
const withModel = async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ models: [{ model_type: 'qwen_image_21', name: 'Qwen Image 2.1', family: 'qwen', architecture: 'qwen_image', is_downloaded: true }] as never })
}

test('Crear starts the server job, shows its poses as they are made and, when it ends, the made animation is read from the character', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  await withModel()
  const made = { ...walk, reviewState: 'pending' as const }
  const api = server({ library: kitOf() })
  const original = globalThis.fetch
  globalThis.fetch = api.fetch
  try {
    render(<CharacterAnimationsPanel workspace="w" />)
    await waitFor(() => assert.ok(screen.getByTestId('animation-angry')))
    fireEvent.click(screen.getByTestId('animation-angry').querySelector('button') as HTMLButtonElement)
    await waitFor(() => assert.ok(screen.getByTestId('animation-angry').querySelector('[data-testid="animation-progress"]')))
    assert.deepEqual(api.state.posts![0].body, { workspace: 'w', kitId: 'ana', animation: 'angry', model: 'qwen_image_21' }, 'the panel only asks: the server makes the poses')
    assert.match(screen.getByTestId('animation-angry').textContent!, /generando|generating/)
    // The server finishes the job and saves the animation on the character.
    api.state.jobs![0] = { ...api.state.jobs![0], status: 'completed', takes: [{ id: 'one', status: 'ready', seed: 1 }, { id: 'two', status: 'ready', seed: 2 }] }
    api.state.library = kitOf({ angry: made })
    await waitFor(() => assert.ok(screen.getByTestId('animation-angry').querySelector('[data-testid="animation-player"]')), { timeout: 6000 })
    assert.match(screen.getByTestId('animation-angry').textContent!, /Por revisar|To review/, 'it waits for a person: nothing approves it')
    assert.equal(screen.queryByTestId('animation-progress'), null)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('a job still running when the page loads is shown and blocks new ones, and a failed one says so and keeps the poses it made', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  await withModel()
  const job = (id: string, animation: string, status: string, extra: Record<string, unknown> = {}) => ({ jobId: id, workspace: 'w', kitId: 'ana', animationId: animation, title: animation, model: 'qwen_image_21',
    status, stage: 'poses', createdAt: 50, updatedAt: 60, takes: [{ id: 'one', status: 'ready', seed: 1, keyed: '/api/v1/file/one.png' }, { id: 'two', status: status === 'failed' ? 'failed' : 'generating', seed: 2, error: 'insufficient VRAM' }], ...extra })
  const api = server({ library: kitOf(), jobs: [job('anim-a', 'wave', 'running'), job('anim-b', 'angry', 'failed', { error: 'insufficient VRAM' })] })
  const original = globalThis.fetch
  globalThis.fetch = api.fetch
  try {
    render(<CharacterAnimationsPanel workspace="w" />)
    await waitFor(() => assert.ok(screen.getByTestId('animation-wave').querySelector('[data-testid="animation-progress"]')))
    assert.match(screen.getByTestId('animation-wave').textContent!, /Cancelar|Cancel/)
    const failed = screen.getByTestId('animation-angry')
    assert.match(failed.textContent!, /insufficient VRAM/)
    assert.match(failed.textContent!, /se conservan|are kept/, 'the poses already made stay')
    assert.equal((failed.querySelector('button') as HTMLButtonElement).disabled, true, 'one animation is made at a time')
    assert.equal(screen.getByTestId('animation-wave').querySelector('button')?.disabled, true)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('an animation described by the author is asked for with their words and stays on screen, from the job, until it is on the character', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  await withModel()
  const api = server({ library: kitOf() })
  const original = globalThis.fetch
  globalThis.fetch = api.fetch
  try {
    render(<CharacterAnimationsPanel workspace="w" />)
    await waitFor(() => assert.ok(screen.getByTestId('custom-animation-form')))
    const form = screen.getByTestId('custom-animation-form')
    fireEvent.change(form.querySelector('input') as HTMLInputElement, { target: { value: 'Sonrisa pícara' } })
    fireEvent.change(form.querySelector('textarea') as HTMLTextAreaElement, { target: { value: 'una sonrisa torcida\nla misma con un guiño' } })
    fireEvent.click(form.querySelector('button[type="submit"]') as HTMLButtonElement)
    await waitFor(() => assert.equal(api.state.posts!.length, 1))
    assert.deepEqual(api.state.posts![0].body, { workspace: 'w', kitId: 'ana', animation: 'sonrisa-picara', model: 'qwen_image_21',
      custom: { title: 'Sonrisa pícara', view: 'bust', poses: ['una sonrisa torcida', 'la misma con un guiño'] } })
    await waitFor(() => assert.ok(screen.getByTestId('animation-sonrisa-picara').querySelector('[data-testid="animation-progress"]')))
    assert.match(screen.getByTestId('animation-sonrisa-picara').textContent!, /Sonrisa pícara/)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('an animation started elsewhere (the Wizard, an MCP tool) shows up while the panel is idle, and one that ended between two looks is read from the character', async () => {
  const { renderHook, waitFor, cleanup } = await import('@testing-library/react')
  const { useCharacterAnimations } = await import('../src/features/characters/useCharacterAnimations.ts')
  const api = server({ library: kitOf() })
  const original = globalThis.fetch
  globalThis.fetch = api.fetch
  let reloads = 0
  try {
    const { result } = renderHook(() => useCharacterAnimations('w', 'ana', () => { reloads += 1 }, 15, 15))
    await waitFor(() => assert.deepEqual(result.current.runs, {}))
    const job = (id: string, animation: string, status: string, createdAt: number) => ({ jobId: id, workspace: 'w', kitId: 'ana', animationId: animation, title: animation, model: 'qwen_image_21', status, stage: 'poses', createdAt, updatedAt: createdAt, takes: [] })
    api.state.jobs!.unshift(job('mcp-1', 'wave', 'running', Date.now() / 1000))
    await waitFor(() => assert.equal(result.current.runs.wave?.status, 'running'), { timeout: 3000 })
    assert.equal(result.current.busy, true)
    api.state.jobs![0] = job('mcp-1', 'wave', 'completed', Date.now() / 1000)
    await waitFor(() => assert.equal(result.current.saved, 'wave'), { timeout: 3000 })
    assert.equal(reloads, 1, 'the made animation is read from the character once')
    assert.equal(result.current.busy, false)
    api.state.jobs!.unshift(job('mcp-2', 'nod', 'completed', Date.now() / 1000))
    await waitFor(() => assert.equal(result.current.saved, 'nod'), { timeout: 3000 })
    assert.equal(reloads, 2)
    // what was finished before the panel opened is just there: nothing to read again.
    assert.equal(result.current.runs.nod, undefined)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})
