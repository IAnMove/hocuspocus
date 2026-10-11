import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { World3DLibraryCard } from '../src/api/world3dWorkspace'
import type { RoomMold } from '../src/features/scene3d/roomSet'
import type { Scene3DDocument } from '../src/features/scene3d/types'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    React,
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLCanvasElement: dom.window.HTMLCanvasElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
    getComputedStyle: dom.window.getComputedStyle,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test.afterEach(() => { window.localStorage.clear() })

const CAMERAS = ['two_shot', 'ots_a', 'ots_b', 'wide', 'close_1', 'close_2', 'entrance']
const KITCHEN: World3DLibraryCard = {
  id: 'stage-cocina', titleEs: 'Cocina', titleEn: 'Kitchen', kind: 'stage', setting: 'interior', place: 'cocina', cameras: CAMERAS,
  lineEs: 'Cocina: interior con mostrador; 2 marcas, de pie, con entrada; plano general desde two_shot.',
  lineEn: 'Kitchen: interior with a counter; 2 marks, standing, with an entrance; wide shot from two_shot.',
  subjects: 2, props: 0, shot: 'wide', distance: 3.5, duration: 6, format: 'landscape',
}
const SQUARE: World3DLibraryCard = {
  ...KITCHEN, id: 'stage-plaza', titleEs: 'Plaza', titleEn: 'Square', setting: 'exterior', place: 'plaza', props: 2, distance: 4.1,
  lineEs: 'Plaza: exterior con fuente; 4 marcas, de pie, con entrada; plano general desde two_shot.',
  lineEn: 'Square: exterior with a fountain; 4 marks, standing, with an entrance; wide shot from two_shot.',
}

function mold(name: string): RoomMold {
  const authored = JSON.parse(readFileSync(new URL(`../../app/shared/set_molds/${name}.json`, import.meta.url), 'utf8')) as RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
  return { ...authored, dimensions: authored.sizes.medium, size: 'medium' }
}

/** What world3d.templates.get returns for a stage: two-shot staged in the mold with its default skin. */
async function stageDocument(name = 'cocina'): Promise<Scene3DDocument> {
  const { stageRoomSet } = await import('../src/features/scene3d/roomSet')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const room = mold(name)
  const staged = stageRoomSet(applyScene3DTemplate('two-shot'), { mold: room, skin: structuredClone(room.defaultSkin), camera: 'two_shot' })
  return { ...staged, templateId: `stage-${name}` as Scene3DDocument['templateId'] }
}

type Call = { operation: string; input: Record<string, unknown> }

function mockServer(reply: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = []
  const original = globalThis.fetch
  globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
    assert.equal(String(url), '/api/v1/world3d/templates/commands')
    const body = JSON.parse(String(init?.body))
    const call = { operation: body.operation, input: body.input }
    calls.push(call)
    return reply(call)
  }) as typeof fetch
  return { calls, restore: () => { globalThis.fetch = original } }
}

const ok = (result: unknown) => new Response(JSON.stringify({ version: 1, status: 'completed', result }), { status: 200 })

async function stageServer(cards = [KITCHEN, SQUARE]) {
  const document = await stageDocument()
  return mockServer(call => call.operation === 'world3d.templates.list'
    ? ok({ templates: cards, total: cards.length, partial: false, unknown_words: [] })
    : ok({ card: cards.find(card => card.id === call.input.template_id), document, objects: [] }))
}

async function openLibrary(overrides: Record<string, unknown> = {}) {
  const { render } = await import('@testing-library/react')
  const { Scene3DShotLibraryDialog } = await import('../src/features/scene3d/Scene3DShotLibrary')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const calls = { templates: [] as string[], packs: [] as { id: string; document: Scene3DDocument }[], closed: 0 }
  render(<Scene3DShotLibraryDialog document={applyScene3DTemplate('two-shot')} applyDisabled={false} editingLocked={false} keepAssets onKeepAssets={() => {}}
    workspace="studio" onTemplate={id => calls.templates.push(id)} onUserTemplate={pack => calls.packs.push({ id: pack.id, document: pack.document })}
    onClose={() => { calls.closed++ }} {...overrides} />)
  return calls
}

test('the Stages chip lists the server stage cards with their line, marks, cameras and shape, and nothing else', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  const server = await stageServer()
  try {
    await openLibrary()
    assert.deepEqual(server.calls, [], 'the other shelves never ask for stages')
    fireEvent.click(screen.getByRole('button', { name: 'Stages' }))
    const kitchen = await screen.findByTestId('world3d-stage-stage-cocina')
    assert.deepEqual(server.calls, [{ operation: 'world3d.templates.list', input: { workspace: 'studio', kind: 'stage', limit: 50 } }])
    const text = kitchen.textContent ?? ''
    for (const part of ['Kitchen', 'Interior', 'interior with a counter', '2 marks', '7 cameras']) assert.ok(text.includes(part), part)
    const square = screen.getByTestId('world3d-stage-stage-plaza').textContent ?? ''
    for (const part of ['Square', 'Exterior', '4 marks']) assert.ok(square.includes(part), part)
    assert.equal(document.querySelectorAll('[data-testid^="world3d-template-two-shot"]').length, 0)
    assert.equal(screen.queryByTestId('world3d-template-sea-deck'), null, 'built-in shots stay on their shelves')
    assert.ok(screen.getByTestId('world3d-template-thumb-stage-cocina'), 'every stage card has a live thumbnail canvas')
    assert.ok(server.calls.every(call => call.operation === 'world3d.templates.list'), 'without a renderer no stage document is fetched for a thumb')
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search templates' }), { target: { value: 'fountain' } })
    assert.equal(screen.queryByTestId('world3d-stage-stage-cocina'), null)
    assert.ok(screen.getByTestId('world3d-stage-stage-plaza'))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search templates' }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Action' }))
    assert.equal(screen.queryByTestId('world3d-stages'), null)
    assert.ok(screen.getByTestId('world3d-template-sea-deck'))
  } finally {
    server.restore()
    cleanup()
  }
})

test('opening a stage loads its document with the room and uses it like a personal template', async () => {
  const { screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const server = await stageServer()
  try {
    const calls = await openLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'Stages' }))
    fireEvent.click(await screen.findByTestId('world3d-stage-stage-cocina'))
    await waitFor(() => assert.match(screen.getByTestId('world3d-shot-preview').textContent ?? '', /Kitchen/))
    assert.deepEqual(server.calls.at(-1), { operation: 'world3d.templates.get', input: { workspace: 'studio', template_id: 'stage-cocina' } })
    const preview = screen.getByTestId('world3d-shot-preview').textContent ?? ''
    assert.ok(preview.includes('Over the shoulder A') && preview.includes('Entrance'), 'the preview names the room cameras')
    assert.equal(screen.getByTestId('world3d-stage-stage-cocina').getAttribute('aria-pressed'), 'true')
    assert.deepEqual(calls.packs, [], 'picking does not replace the scene')
    fireEvent.click(screen.getByTestId('world3d-use-shot'))
    assert.equal(calls.packs.length, 1)
    assert.equal(calls.closed, 1)
    const [{ id, document }] = calls.packs
    assert.equal(id, 'stage-cocina')
    assert.equal(document.templateId, 'stage-cocina')
    assert.equal(document.room?.mold.id, 'cocina')
    assert.equal(document.room?.camera, 'two_shot')
    assert.equal(document.camera.family, 'fixed')
    assert.deepEqual(document.slots.map(slot => slot.slot), ['subject_1', 'subject_2'], 'both subjects wait for a character')
  } finally {
    server.restore()
    cleanup()
  }
})

test('a stage mounts into the editor with its room and is titled as a stage', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { packFromStage } = await import('../src/features/scene3d/templateLibraryModel')
  const { remountUserTemplate } = await import('../src/features/scene3d/userTemplates')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const { Scene3DShotLibraryCard } = await import('../src/features/scene3d/Scene3DShotLibraryCard')
  const previous = { ...applyScene3DTemplate('two-shot'), width: 1920, height: 1080 }
  previous.slots = previous.slots.map(slot => slot.id === 'subject_1' ? { ...slot, sourceUrl: '/api/v1/file/hero.glb?workspace=studio' } : slot)
  const mounted = remountUserTemplate(packFromStage(KITCHEN, await stageDocument(), 'es'), previous, true)
  assert.equal(mounted.room?.mold.id, 'cocina')
  assert.equal(mounted.width, 1920)
  assert.equal(mounted.slots.find(slot => slot.id === 'subject_1')?.sourceUrl, '/api/v1/file/hero.glb?workspace=studio', 'the bound character steps onto the mark')
  const props = { applyDisabled: false, editingLocked: false, keepAssets: true, onKeepAssets: () => {}, onTemplate: () => {}, onUserTemplate: () => {} }
  try {
    render(<Scene3DShotLibraryCard document={mounted} userTemplateId="stage-cocina" {...props} />)
    assert.ok(screen.getByText('Cocina'), 'the card it was opened from names the shot')
    cleanup()
    render(<Scene3DShotLibraryCard document={{ ...mounted, templateId: 'stage-faro' as Scene3DDocument['templateId'] }} {...props} />)
    assert.ok(screen.getByText('Stage · faro'), 'a reopened stage is not called a workspace template')
  } finally {
    cleanup()
  }
})

test('the room camera picker switches the camera to the named room camera', async () => {
  const { render, screen, fireEvent, cleanup, within } = await import('@testing-library/react')
  const { Scene3DRoomCameraPicker } = await import('../src/features/scene3d/Scene3DRoomCameraPicker')
  const { withRoomCamera } = await import('../src/features/scene3d/roomCamera')
  const staged = await stageDocument()
  const seen = [staged]
  const latest = () => seen[seen.length - 1]
  const record = (next: Scene3DDocument) => { seen.push(next); return next }
  function Harness() {
    const [doc, setDoc] = React.useState(staged)
    return <>
      <button type="button" onClick={() => setDoc(value => record({ ...value, camera: { ...value.camera, family: 'orbit' } }))}>orbit</button>
      <Scene3DRoomCameraPicker document={doc} disabled={false} onChange={id => setDoc(value => record(withRoomCamera(value, id)))} />
    </>
  }
  try {
    render(<Harness />)
    const select = screen.getByTestId('world3d-room-camera') as HTMLSelectElement
    assert.equal(select.value, 'two_shot')
    assert.deepEqual(within(select).getAllByRole('option').map(option => option.textContent),
      ['Two-shot', 'Over the shoulder A', 'Over the shoulder B', 'Wide', 'Close-up 1', 'Close-up 2', 'Entrance'])
    fireEvent.change(select, { target: { value: 'ots_a' } })
    const ots = staged.room!.mold.cameras.find(camera => camera.id === 'ots_a')!
    assert.deepEqual(latest().camera, { family: 'fixed', eye: ots.position, look: ots.lookAt, fov: ots.fov })
    assert.equal(latest().room?.camera, 'ots_a')
    assert.equal((screen.getByTestId('world3d-room-camera') as HTMLSelectElement).value, 'ots_a')
    fireEvent.click(screen.getByRole('button', { name: 'orbit' }))
    assert.equal((screen.getByTestId('world3d-room-camera') as HTMLSelectElement).value, '', 'another family is no room camera')
    assert.ok(screen.getByRole('option', { name: 'Custom' }))
    fireEvent.change(screen.getByTestId('world3d-room-camera'), { target: { value: 'close_2' } })
    assert.equal(latest().camera.family, 'fixed')
    assert.equal(latest().room?.camera, 'close_2')
  } finally {
    cleanup()
  }
})

test('room cameras keep shake windows, follow a portrait frame and leave a room-less shot alone', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { activeRoomCamera, withRoomCamera } = await import('../src/features/scene3d/roomCamera')
  const { Scene3DRoomCameraPicker } = await import('../src/features/scene3d/Scene3DRoomCameraPicker')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const staged = await stageDocument()
  const shake = [{ start: 1, end: 2, amplitude: 0.05, frequency: 12 }]
  assert.deepEqual(withRoomCamera({ ...staged, camera: { ...staged.camera, shake } }, 'wide').camera.shake, shake)
  const portrait = withRoomCamera({ ...staged, width: 1080, height: 1920 }, 'close_1')
  assert.equal(portrait.camera.frameFormat, 'portrait')
  assert.equal(activeRoomCamera(portrait), 'close_1')
  assert.equal(withRoomCamera(staged, 'balcony'), staged, 'an unknown camera changes nothing')
  const plain = applyScene3DTemplate('two-shot')
  assert.equal(withRoomCamera(plain, 'ots_a'), plain)
  assert.equal(activeRoomCamera(plain), '')
  try {
    const { container } = render(<Scene3DRoomCameraPicker document={plain} disabled={false} onChange={() => {}} />)
    assert.equal(container.innerHTML, '', 'no room, no picker')
  } finally {
    cleanup()
  }
})

test('the Stages shelf says why it is empty: no workspace, the server down, or no stages', async () => {
  const { screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  let down = true
  const server = mockServer(() => {
    if (down) throw new TypeError('Failed to fetch')
    return ok({ templates: [], total: 0 })
  })
  try {
    await openLibrary({ workspace: undefined })
    fireEvent.click(screen.getByRole('button', { name: 'Stages' }))
    assert.match(screen.getByTestId('world3d-stages-no-workspace').textContent ?? '', /Open a workspace/)
    assert.deepEqual(server.calls, [])
    cleanup()
    await openLibrary()
    assert.ok(screen.getByTestId('world3d-stages'), 'the library reopens on the Stages shelf')
    assert.match((await screen.findByRole('alert')).textContent ?? '', /Could not load the stages: Failed to fetch/)
    down = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => assert.match(screen.getByRole('status').textContent ?? '', /no stages/))
    assert.equal(screen.queryByRole('alert'), null)
    assert.equal(server.calls.length, 2)
  } finally {
    server.restore()
    cleanup()
  }
})

test('a stage the server cannot open reports it and keeps the current pick', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  const server = mockServer(call => call.operation === 'world3d.templates.list'
    ? ok({ templates: [KITCHEN, SQUARE], total: 2 })
    : call.input.template_id === 'stage-plaza'
      ? new Response(JSON.stringify({ detail: { code: 'unknown_template', message: 'unknown_template:stage-plaza' } }), { status: 404 })
      : ok({ card: KITCHEN, document: { version: 1 } }))
  try {
    // Documents are remembered per workspace, so this one has never opened the kitchen.
    const calls = await openLibrary({ workspace: 'broken-stages' })
    fireEvent.click(screen.getByRole('button', { name: 'Stages' }))
    fireEvent.click(await screen.findByTestId('world3d-stage-stage-plaza'))
    assert.match((await screen.findByRole('alert')).textContent ?? '', /Could not open the stage: unknown_template:stage-plaza/)
    fireEvent.click(screen.getByTestId('world3d-stage-stage-cocina'))
    assert.match((await screen.findByRole('alert')).textContent ?? '', /not a valid Video 3D document with a room/)
    for (const id of ['stage-plaza', 'stage-cocina']) assert.equal(screen.getByTestId(`world3d-stage-${id}`).getAttribute('aria-pressed'), 'false')
    fireEvent.click(screen.getByTestId('world3d-use-shot'))
    assert.deepEqual(calls.packs, [])
    assert.deepEqual(calls.templates, ['two-shot'], 'Use still applies the shot that was picked before')
  } finally {
    server.restore()
    cleanup()
  }
})

test('a stage document is fetched once per workspace, and a failed request is tried again', async () => {
  const { loadStageDocument } = await import('../src/features/scene3d/stageShelf')
  const document = await stageDocument('plaza')
  let fail = true
  const server = mockServer(() => fail ? new Response('{}', { status: 503 }) : ok({ card: SQUARE, document }))
  try {
    await assert.rejects(loadStageDocument('cache-test', 'stage-plaza'))
    fail = false
    const [first, second] = await Promise.all([loadStageDocument('cache-test', 'stage-plaza'), loadStageDocument('cache-test', 'stage-plaza')])
    assert.equal(first, second)
    assert.equal(first.room?.mold.kind, 'exterior')
    assert.equal(server.calls.length, 2)
    await loadStageDocument('other-workspace', 'stage-plaza')
    assert.equal(server.calls.length, 3)
  } finally {
    server.restore()
  }
})

test('a stage thumbnail is the same schematic document view the built-in thumbnails use', async () => {
  const { previewSceneDocument } = await import('../src/features/scene3d/templateCatalog')
  const staged = await stageDocument()
  const withMedia = { ...staged, slots: staged.slots.map(slot => ({ ...slot, appearance: { start: 1 } })) as Scene3DDocument['slots'] }
  const preview = previewSceneDocument(withMedia)
  assert.equal(preview.room, staged.room, 'the room stays, so the thumb draws it')
  assert.ok(preview.slots.every(slot => slot.appearance === undefined && slot.speech === undefined && slot.screen === undefined))
})

test('stage thumbs that take turns on the shared renderer keep their rooms instead of rebuilding them', async () => {
  const { Scene } = await import('three')
  const { attachPreviewRoom } = await import('../src/features/scene3d/templatePreview')
  const pack: Parameters<typeof attachPreviewRoom>[0] = { scene: new Scene(), room: undefined, roomKey: undefined }
  const kitchen = (await stageDocument('cocina')).room!, square = (await stageDocument('plaza')).room!
  attachPreviewRoom(pack, kitchen)
  const first = pack.room
  assert.ok(first && pack.scene.children.includes(first.root))
  attachPreviewRoom(pack, square)
  assert.ok(pack.room && pack.room !== first)
  assert.ok(!pack.scene.children.includes(first.root), 'one room in the scene at a time')
  attachPreviewRoom(pack, kitchen)
  assert.equal(pack.room, first, 'the kitchen comes back without new meshes')
  assert.equal(pack.roomKey, JSON.stringify(kitchen), 'paintWorld sees the same key and keeps the room')
  attachPreviewRoom(pack, undefined)
  assert.equal(pack.room, undefined)
  assert.equal(pack.scene.children.length, 0, 'a shot without a room shows none')
})
