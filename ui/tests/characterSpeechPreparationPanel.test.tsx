import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit.ts'

const dom = new JSDOM('<!doctype html><html lang="en"><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  File: dom.window.File,
  Blob: dom.window.Blob,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const presetRequests: Array<{ url: string; method: string }> = []
const originalFetch = globalThis.fetch
globalThis.fetch = async (input, init) => {
  const url = String(input)
  const method = String(init?.method ?? 'GET').toUpperCase()
  presetRequests.push({ url, method })
  if (method !== 'GET' || !url.endsWith('/character-kit-presets/mouths/manifest.json')) {
    throw new Error(`Unexpected network request: ${method} ${url}`)
  }
  return {
    ok: true,
    json: async () => ({ packs: [{
      id: 'manual-pack',
      label: 'Manual pack',
      states: {
        closed: { file: 'closed.png' },
        small: { file: 'small.png' },
        wide: { file: 'wide.png' },
        round: { file: 'round.png' },
      },
    }] }),
  } as Response
}

test.after(() => { globalThis.fetch = originalFetch })
test.beforeEach(async () => {
  const { clearSpeechDraft } = await import('../src/lib/characterSpeechDraft.ts')
  for (const workspace of ['default', 'workspace-a', 'workspace-b']) clearSpeechDraft(workspace)
})

const asset = (id: string, reviewState: 'pending' | 'approved' | 'rejected' = 'approved', source = `/${id}.png`, kind: 'image' | 'overlay' = 'overlay') => ({
  id,
  name: id,
  source,
  kind,
  alphaStatus: kind === 'image' ? 'opaque' as const : 'transparent' as const,
  reviewState,
})

function kit(id: string, name: string, baseReviewState: 'pending' | 'approved' | 'rejected' = 'approved') {
  const next = createCharacterKit(name)
  return {
    ...next,
    id,
    base: asset(`${id}-base`, baseReviewState, `/${id}-base.png`, 'image'),
    anchors: { base: { mouth: { offsetX: 0, offsetY: -18, scale: .05, rotation: 0 } } },
  }
}

function library(revision: number, ...kits: ReturnType<typeof kit>[]) {
  return {
    version: 1 as const,
    revision,
    activeId: kits[0]?.id ?? '',
    kits: Object.fromEntries(kits.map(current => [current.id, current])),
  }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (cause: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

async function viewFor(options: {
  workspace?: string
  initialKitId?: string
  services: {
    load: (workspace: string) => Promise<ReturnType<typeof library>>
    save: (workspace: string, current: ReturnType<typeof library>, draft: ReturnType<typeof kit>) => Promise<ReturnType<typeof library>>
    upload: (file: File) => Promise<{ filename: string; path: string; url: string }>
  }
}) {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterSpeechPreparation } = await import('../src/features/characters/CharacterSpeechPreparation.tsx')
  presetRequests.length = 0
  const view = render(<CharacterSpeechPreparation workspace={options.workspace ?? 'default'} services={options.services} initialKitId={options.initialKitId} />)
  return { ...view, screen, fireEvent, waitFor, cleanup, Component: CharacterSpeechPreparation }
}

function assertOnlyPresetGets() {
  assert.ok(presetRequests.length > 0, 'the real Face Rig child should load its preset manifest')
  assert.ok(presetRequests.every(request => request.method === 'GET'
    && request.url.endsWith('/character-kit-presets/mouths/manifest.json')))
}

test('a character shortcut opens its exact kit without replacing another workshop recovery draft', async () => {
  const { writeSpeechDraft, readSpeechDraft } = await import('../src/lib/characterSpeechDraft')
  const first = kit('first', 'First'), second = kit('second', 'Second')
  writeSpeechDraft('default', { baseRevision: 2, kit: first })
  const view = await viewFor({ initialKitId: second.id, services: {
    load: async () => library(3, first, second),
    save: async () => { throw new Error('Opening configuration must not save') },
    upload: async () => { throw new Error('Opening configuration must not upload') },
  } })
  try {
    const selected = await view.screen.findByRole('combobox', { name: 'Saved character' }) as HTMLSelectElement
    await view.waitFor(() => assert.equal(selected.value, second.id))
    assert.equal(selected.disabled, true)
    assert.equal(view.screen.queryByRole('button', { name: 'Upload base and create draft' }), null)
    assert.equal(readSpeechDraft('default')?.kit.id, first.id)
  } finally { view.cleanup() }
})

test('loads and selects saved kits without upload or model POST, while manual packs and import remain available', { concurrency: false }, async () => {
  const first = kit('kit-a', 'Same name')
  const second = kit('kit-b', 'Same name')
  const saved = library(7, first, second)
  const uploads: File[] = []
  const services = {
    load: async () => saved,
    save: async () => { throw new Error('save should not run') },
    upload: async (file: File) => { uploads.push(file); return { filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` } },
  }
  const view = await viewFor({ services })
  try {
    await view.screen.findAllByRole('option', { name: 'Same name' })
    await view.screen.findByRole('button', { name: 'Use pack' })
    const characterSelect = view.screen.getByRole('combobox', { name: 'Saved character' }) as HTMLSelectElement
    assert.equal(characterSelect.value, first.id)
    view.fireEvent.change(characterSelect, { target: { value: second.id } })
    await view.waitFor(() => assert.equal(characterSelect.value, second.id))

    assert.equal(uploads.length, 0)
    assertOnlyPresetGets()
    for (const name of [/Regenerate body \(stays pending\)/, /Generate \/ replace Open/, /Generate the missing ones/, /Speak 3 s/]) {
      assert.equal((view.screen.getByRole('button', { name })).disabled, true, `${name} should be disabled in the manual workshop`)
    }
    assert.equal((view.screen.getByRole('button', { name: 'Use pack' }) as HTMLButtonElement).disabled, false)
    assert.equal((view.screen.getByRole('button', { name: 'Upload base and create draft' }) as HTMLButtonElement).disabled, true)
  } finally { view.cleanup() }
})

test('does not upload a chosen base file until explicit import, then approves and saves the pending base with workspace revision', { concurrency: false }, async () => {
  const existing = kit('existing', 'Existing')
  const initial = library(11, existing)
  const uploads: File[] = []
  const saves: Array<{ workspace: string; current: ReturnType<typeof library>; draft: ReturnType<typeof kit> }> = []
  const services = {
    load: async () => initial,
    save: async (workspace: string, current: ReturnType<typeof library>, draft: ReturnType<typeof kit>) => {
      saves.push({ workspace, current, draft })
      return { ...current, revision: current.revision + 1, activeId: draft.id, kits: { ...current.kits, [draft.id]: draft } }
    },
    upload: async (file: File) => {
      uploads.push(file)
      return { filename: file.name, path: `/tmp/${file.name}`, url: `/api/v1/uploads/${file.name}` }
    },
  }
  const view = await viewFor({ workspace: 'workspace-a', services })
  try {
    await view.screen.findByRole('option', { name: 'Existing' })
    const nameInput = view.screen.getByLabelText('New character name') as HTMLInputElement
    const fileInput = view.screen.getByLabelText('Base image') as HTMLInputElement
    const importButton = view.screen.getByRole('button', { name: 'Upload base and create draft' }) as HTMLButtonElement
    const baseFile = new File(['base'], 'new-base.png', { type: 'image/png' })

    view.fireEvent.change(fileInput, { target: { files: [baseFile] } })
    assert.equal(uploads.length, 0, 'choosing a file must not upload it')
    view.fireEvent.change(nameInput, { target: { value: 'Imported hero' } })
    await view.waitFor(() => assert.equal(importButton.disabled, false))
    view.fireEvent.click(importButton)
    await view.waitFor(() => assert.equal(uploads.length, 1))
    assert.equal(uploads[0], baseFile)
    await view.screen.findByText(/Base uploaded\. Review it in the preview/)

    const approveButton = view.screen.getByRole('button', { name: 'I have reviewed this base image' }) as HTMLButtonElement
    assert.equal(approveButton.disabled, false)
    view.fireEvent.click(approveButton)
    await view.waitFor(() => assert.equal(approveButton.disabled, true))

    const saveButton = view.screen.getByRole('button', { name: 'Save speech character' }) as HTMLButtonElement
    assert.equal(saveButton.disabled, false)
    view.fireEvent.click(saveButton)
    await view.waitFor(() => assert.equal(saves.length, 1))
    assert.equal(saves[0].workspace, 'workspace-a')
    assert.equal(saves[0].current.revision, 11, 'the save receives the current library revision as its baseRevision source')
    assert.equal(saves[0].draft.base?.source, '/api/v1/uploads/new-base.png')
    assert.equal(saves[0].draft.base?.reviewState, 'approved')
    await view.screen.findByText(/Character saved to this workspace/)
    assertOnlyPresetGets()
  } finally { view.cleanup() }
})

test('retains a draft after save failure, performs no automatic retry, and discards it only after explicit reload', { concurrency: false }, async () => {
  const pending = kit('pending', 'Pending hero', 'pending')
  const initial = library(13, pending)
  let loadCalls = 0
  let saveCalls = 0
  const services = {
    load: async () => { loadCalls += 1; return initial },
    save: async () => { saveCalls += 1; throw new Error('synthetic save failure') },
    upload: async (file: File) => ({ filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }),
  }
  const view = await viewFor({ services })
  try {
    await view.screen.findByRole('option', { name: 'Pending hero' })
    const approveButton = view.screen.getByRole('button', { name: 'I have reviewed this base image' }) as HTMLButtonElement
    view.fireEvent.click(approveButton)
    await view.waitFor(() => assert.equal(approveButton.disabled, true))
    const saveButton = view.screen.getByRole('button', { name: 'Save speech character' }) as HTMLButtonElement
    view.fireEvent.click(saveButton)
    await view.screen.findByText(/synthetic save failure/)
    assert.equal(saveCalls, 1)
    await new Promise(resolve => setTimeout(resolve, 10))
    assert.equal(saveCalls, 1, 'a failed save must not retry automatically')
    assert.equal(approveButton.disabled, true, 'the approved local draft must remain visible after failure')

    const reloadButton = view.screen.getByRole('button', { name: 'Discard draft and reload library' }) as HTMLButtonElement
    assert.equal(loadCalls, 1)
    view.fireEvent.click(reloadButton)
    await view.waitFor(() => assert.equal(loadCalls, 2))
    await view.waitFor(() => assert.equal(approveButton.disabled, false))
    assert.equal((view.screen.getByRole('button', { name: 'Save speech character' }) as HTMLButtonElement).disabled, true)
    // Face Rig may still show a valid pending-pose alert after reload. Check
    // the save error specifically, and compare primitives: formatting a failed
    // HTMLElement-vs-null assertion can exhaust memory on React's DOM graph.
    await view.waitFor(() => assert.equal(view.screen.queryByText(/synthetic save failure/) === null, true, 'reload should clear the save error'))
  } finally { view.cleanup() }
})

test('ignores a late load from the previous workspace after the keyed owner changes', { concurrency: false }, async () => {
  const loadA = deferred<ReturnType<typeof library>>()
  const loadB = deferred<ReturnType<typeof library>>()
  const first = kit('workspace-a-kit', 'Workspace A')
  const second = kit('workspace-b-kit', 'Workspace B')
  const calls: string[] = []
  const services = {
    load: (workspace: string) => { calls.push(workspace); return workspace === 'workspace-a' ? loadA.promise : loadB.promise },
    save: async () => library(1),
    upload: async (file: File) => ({ filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }),
  }
  const view = await viewFor({ workspace: 'workspace-a', services })
  try {
    await view.waitFor(() => assert.deepEqual(calls, ['workspace-a']))
    view.rerender(<view.Component workspace="workspace-b" services={services} />)
    await view.waitFor(() => assert.deepEqual(calls, ['workspace-a', 'workspace-b']))
    loadA.resolve(library(2, first))
    await flush()
    assert.equal(view.screen.queryByRole('option', { name: 'Workspace A' }) === null, true)
    loadB.resolve(library(3, second))
    await view.screen.findByRole('option', { name: 'Workspace B' })
    assert.equal((view.screen.getByRole('combobox', { name: 'Saved character' }) as HTMLSelectElement).value, second.id)
  } finally { view.cleanup() }
})

test('ignores a late upload from the previous workspace after the keyed owner changes', { concurrency: false }, async () => {
  const first = kit('workspace-a-kit', 'Workspace A')
  const second = kit('workspace-b-kit', 'Workspace B')
  const upload = deferred<{ filename: string; path: string; url: string }>()
  let uploadCalls = 0
  const services = {
    load: async (workspace: string) => workspace === 'workspace-a' ? library(1, first) : library(2, second),
    save: async () => library(1),
    upload: async () => { uploadCalls += 1; return upload.promise },
  }
  const view = await viewFor({ workspace: 'workspace-a', services })
  try {
    await view.screen.findByRole('option', { name: 'Workspace A' })
    view.fireEvent.change(view.screen.getByLabelText('New character name'), { target: { value: 'Late import' } })
    view.fireEvent.change(view.screen.getByLabelText('Base image'), { target: { files: [new File(['a'], 'late.png', { type: 'image/png' })] } })
    const importButton = view.screen.getByRole('button', { name: 'Upload base and create draft' }) as HTMLButtonElement
    await view.waitFor(() => assert.equal(importButton.disabled, false))
    view.fireEvent.click(importButton)
    await view.waitFor(() => assert.equal(uploadCalls, 1))

    view.rerender(<view.Component workspace="workspace-b" services={services} />)
    await view.screen.findByRole('option', { name: 'Workspace B' })
    upload.resolve({ filename: 'late.png', path: '/tmp/late.png', url: '/api/v1/uploads/late.png' })
    await flush()
    assert.equal((view.screen.getByRole('combobox', { name: 'Saved character' }) as HTMLSelectElement).value, second.id)
    assert.equal(view.screen.queryByText(/Base uploaded\. Review it in the preview/) === null, true)
  } finally { view.cleanup() }
})

test('ignores a late save from the previous workspace after the keyed owner changes', { concurrency: false }, async () => {
  const first = kit('workspace-a-kit', 'Workspace A', 'pending')
  const second = kit('workspace-b-kit', 'Workspace B')
  const saved = deferred<ReturnType<typeof library>>()
  let saveCalls = 0
  const services = {
    load: async (workspace: string) => workspace === 'workspace-a' ? library(4, first) : library(5, second),
    save: async () => { saveCalls += 1; return saved.promise },
    upload: async (file: File) => ({ filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }),
  }
  const view = await viewFor({ workspace: 'workspace-a', services })
  try {
    await view.screen.findByRole('option', { name: 'Workspace A' })
    const approveButton = view.screen.getByRole('button', { name: 'I have reviewed this base image' }) as HTMLButtonElement
    view.fireEvent.click(approveButton)
    await view.waitFor(() => assert.equal(approveButton.disabled, true))
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Save speech character' }))
    await view.waitFor(() => assert.equal(saveCalls, 1))

    view.rerender(<view.Component workspace="workspace-b" services={services} />)
    await view.screen.findByRole('option', { name: 'Workspace B' })
    saved.resolve(library(6, { ...first, base: { ...first.base!, reviewState: 'approved' } }))
    await flush()
    assert.equal((view.screen.getByRole('combobox', { name: 'Saved character' }) as HTMLSelectElement).value, second.id)
    assert.equal(view.screen.queryByText(/Character saved to this workspace/) === null, true)
  } finally { view.cleanup() }
})

test('gives imported kits with the same name unique ids', { concurrency: false }, async () => {
  const existing = kit('existing', 'Existing')
  const initial = library(20, existing)
  const savedKits: ReturnType<typeof kit>[] = []
  const uploads: File[] = []
  const services = {
    load: async () => initial,
    save: async (workspace: string, current: ReturnType<typeof library>, draft: ReturnType<typeof kit>) => {
      savedKits.push(draft)
      return { ...current, revision: current.revision + 1, activeId: draft.id, kits: { ...current.kits, [draft.id]: draft } }
    },
    upload: async (file: File) => {
      uploads.push(file)
      return { filename: file.name, path: `/tmp/${file.name}`, url: `/api/v1/uploads/${file.name}` }
    },
  }
  const originalGetRandomValues = globalThis.crypto.getRandomValues
  let randomValue = 0
  globalThis.crypto.getRandomValues = <T extends ArrayBufferView | null>(array: T): T => {
    if (array && 'length' in array) {
      const bytes = array as unknown as { length: number; [index: number]: number }
      bytes[bytes.length - 1] = ++randomValue
    }
    return array
  }
  const view = await viewFor({ services })
  try {
    await view.screen.findByRole('option', { name: 'Existing' })
    const nameInput = view.screen.getByLabelText('New character name') as HTMLInputElement
    const fileInput = view.screen.getByLabelText('Base image') as HTMLInputElement
    const importButton = view.screen.getByRole('button', { name: 'Upload base and create draft' }) as HTMLButtonElement
    const approveButtonName = 'I have reviewed this base image'
    const saveButtonName = 'Save speech character'

    const importAndSave = async (file: File) => {
      view.fireEvent.change(nameInput, { target: { value: 'Shared character' } })
      view.fireEvent.change(fileInput, { target: { files: [file] } })
      await view.waitFor(() => assert.equal(importButton.disabled, false))
      view.fireEvent.click(importButton)
      await view.waitFor(() => assert.equal(uploads.length, savedKits.length + 1))
      const approveButton = view.screen.getByRole('button', { name: approveButtonName }) as HTMLButtonElement
      view.fireEvent.click(approveButton)
      await view.waitFor(() => assert.equal(approveButton.disabled, true))
      view.fireEvent.click(view.screen.getByRole('button', { name: saveButtonName }))
      await view.waitFor(() => assert.equal(savedKits.length, uploads.length))
    }

    await importAndSave(new File(['first'], 'first.png', { type: 'image/png' }))
    await importAndSave(new File(['second'], 'second.png', { type: 'image/png' }))
    assert.equal(savedKits.length, 2)
    assert.equal(savedKits[0].name, 'Shared character')
    assert.equal(savedKits[1].name, 'Shared character')
    assert.notEqual(savedKits[0].id, savedKits[1].id)
  } finally {
    globalThis.crypto.getRandomValues = originalGetRandomValues
    view.cleanup()
  }
})

test('recovers a draft after navigation without rebasing its original save revision', { concurrency: false }, async () => {
  const first = kit('persistent-a', 'Recovery hero', 'pending')
  const second = kit('persistent-b', 'Other workspace')
  let revision = 8
  const saves: number[] = []
  const services = {
    load: async (workspace: string) => workspace === 'workspace-a' ? library(revision, first) : library(1, second),
    save: async (_workspace: string, current: ReturnType<typeof library>) => {
      saves.push(current.revision)
      throw new Error('revision conflict')
    },
    upload: async (file: File) => ({ filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }),
  }
  const view = await viewFor({ workspace: 'workspace-a', services })
  try {
    await view.screen.findByRole('option', { name: 'Recovery hero' })
    view.fireEvent.click(view.screen.getByRole('button', { name: 'I have reviewed this base image' }))
    await view.screen.findByText(/Unsaved changes/)
    view.rerender(<view.Component workspace="workspace-b" services={services} />)
    await view.screen.findByRole('option', { name: 'Other workspace' })
    assert.equal(view.screen.queryByText(/Unsaved changes/) === null, true)
    revision = 9 // another editor saved while this workspace was closed
    view.rerender(<view.Component workspace="workspace-a" services={services} />)
    await view.screen.findByRole('option', { name: 'Recovery hero' })
    await view.screen.findByText(/Unsaved changes/)
    assert.equal((view.screen.getByRole('button', { name: 'I have reviewed this base image' }) as HTMLButtonElement).disabled, true)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Save speech character' }))
    await view.screen.findByRole('alert')
    assert.deepEqual(saves, [8], 'restore must not silently adopt revision 9')
    await view.screen.findByText(/Unsaved changes/)
  } finally { view.cleanup() }
})

test('recovers on full component remount and clears recovery only after a successful save', { concurrency: false }, async () => {
  const first = kit('persistent', 'Remount hero', 'pending')
  let current = library(4, first)
  const services = {
    load: async () => current,
    save: async (_workspace: string, previous: ReturnType<typeof library>, draft: ReturnType<typeof kit>) => {
      current = { ...previous, revision: previous.revision + 1, kits: { [draft.id]: draft } }
      return current
    },
    upload: async (file: File) => ({ filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }),
  }
  const before = await viewFor({ services })
  await before.screen.findByRole('option', { name: 'Remount hero' })
  before.fireEvent.click(before.screen.getByRole('button', { name: 'I have reviewed this base image' }))
  await before.screen.findByText(/Unsaved changes/)
  before.cleanup()
  const after = await viewFor({ services })
  try {
    await after.screen.findByText(/Unsaved changes/)
    after.fireEvent.click(after.screen.getByRole('button', { name: 'Save speech character' }))
    await after.screen.findByText(/Character saved to this workspace/)
    const { readSpeechDraft } = await import('../src/lib/characterSpeechDraft.ts')
    assert.equal(readSpeechDraft('default'), null)
  } finally { after.cleanup() }
})
