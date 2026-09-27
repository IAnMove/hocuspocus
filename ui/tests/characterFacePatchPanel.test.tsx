import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit, type CharacterKit } from '../src/lib/characterKit.ts'
import type { CharacterFacePatchPanelProps } from '../src/features/characters/CharacterFacePatchPanel.tsx'
import type { prepareCharacterFacePatch } from '../src/lib/prepareCharacterFacePatch.ts'

type PreparedPatch = Awaited<ReturnType<typeof prepareCharacterFacePatch>>

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const base = (overrides: Partial<NonNullable<CharacterKit['base']>> = {}) => ({
  id: 'base-parent-id', name: 'Luma base', source: '/api/v1/file/luma-base.png', kind: 'image' as const,
  alphaStatus: 'opaque' as const, reviewState: 'approved' as const, ...overrides,
})
const makeKit = (overrides: Partial<CharacterKit> = {}): CharacterKit => ({ ...createCharacterKit('Luma'), base: base(), ...overrides })
const metadata = (poseSource = '/api/v1/file/luma-base.png') => ({
  version: 1 as const, poseSource, sourceWidth: 100, sourceHeight: 100, region: { x: 42, y: 42, size: 16 }, feather: .08,
  poseSha256: 'a'.repeat(64), variantSha256: 'b'.repeat(64), outputSha256: 'c'.repeat(64),
})
const anchor = { offsetX: 0, offsetY: -18, scale: .16, rotation: 0 }
const flush = () => new Promise(resolve => setTimeout(resolve, 0))
const fakeBlob = () => new Blob(['derived-patch'], { type: 'image/png' })

async function viewFor(overrides: Partial<CharacterFacePatchPanelProps> = {}) {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const prepare = overrides.prepare ?? (async (poseSource: string) => ({ blob: fakeBlob(), metadata: metadata(poseSource) }))
  const upload = overrides.upload ?? (async (file: File) => ({ filename: file.name, path: `/tmp/${file.name}`, url: `/api/v1/uploads/${file.name}` }))
  const props: CharacterFacePatchPanelProps = {
    kit: makeKit(), poseId: 'base', state: 'wide', anchor, workspace: 'default', onChange: () => undefined,
    ...overrides, prepare, upload,
  }
  const { CharacterFacePatchPanel } = await import('../src/features/characters/CharacterFacePatchPanel.tsx')
  const view = render(<CharacterFacePatchPanel {...props} />)
  return { ...view, screen, fireEvent, waitFor, cleanup, props }
}

function selectFile(view: Awaited<ReturnType<typeof viewFor>>, file = new File(['variant'], 'variant.png', { type: 'image/png' })) {
  view.fireEvent.change(view.screen.getByLabelText(/Aligned full-image variant/), { target: { files: [file] } })
}

test('prepares privately, then saves two uploads as a pending registered patch', { concurrency: false }, async () => {
  const uploads: File[] = []; let changed: CharacterKit | undefined
  const view = await viewFor({
    onChange: kit => { changed = kit },
    upload: async file => { uploads.push(file); return { filename: file.name, path: `/tmp/${file.name}`, url: `/api/v1/uploads/${file.name}` } },
  })
  try {
    assert.match((view.screen.getByLabelText(/Readonly reference prompt/) as HTMLTextAreaElement).value, /full-frame expression variant/)
    selectFile(view)
    await view.screen.findByText(/Patch prepared locally/)
    assert.equal(uploads.length, 0, 'preparation must not upload')
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Save pending patch' }))
    await view.waitFor(() => assert.equal(uploads.length, 2))
    await view.waitFor(() => assert.ok(changed))
    const patch = changed!.mouth.wide
    assert.ok(patch)
    assert.match(patch.id, /^face-patch-/)
    assert.notEqual(patch.id, 'base-parent-id')
    assert.equal(patch.reviewState, 'pending')
    assert.equal(patch.alphaStatus, 'transparent')
    assert.equal(patch.prompt, undefined, 'an imported variant must not claim the suggested prompt as provenance')
    assert.equal(patch.facePatch?.poseId, 'base')
    assert.equal(patch.facePatch?.variantSource, '/api/v1/uploads/variant.png')
    assert.equal(uploads[0].name, 'variant.png')
    assert.match(uploads[1].name, /^face-patch-.*\.png$/)
    assert.match(view.screen.getByRole('status').textContent || '', /Patch saved as pending/)
  } finally { view.cleanup() }
})

test('discards a late preparation after the pose changes and shows cancellation', { concurrency: false }, async () => {
  let resolvePrepare!: (value: PreparedPatch) => void
  let changed = 0
  const view = await viewFor({
    onChange: () => { changed += 1 },
    prepare: () => new Promise(resolve => { resolvePrepare = resolve }),
  })
  try {
    selectFile(view)
    const replacement = makeKit({ base: base({ source: '/api/v1/file/luma-base-v2.png' }) })
    const Component = (await import('../src/features/characters/CharacterFacePatchPanel.tsx')).CharacterFacePatchPanel
    view.rerender(<Component {...view.props} kit={replacement} />)
    resolvePrepare({ blob: fakeBlob(), metadata: metadata('/api/v1/file/luma-base.png') })
    await flush()
    assert.equal(changed, 0)
    assert.match(view.screen.getByRole('status').textContent || '', /Cancelled stale patch operation/)
    assert.equal(view.screen.getByRole('button', { name: 'Save pending patch' }).getAttribute('disabled'), '')
  } finally { view.cleanup() }
})

test('does not resurrect a revoked preparation after switching away and back', { concurrency: false }, async () => {
  let uploads = 0
  const view = await viewFor({
    upload: async file => { uploads += 1; return { filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` } },
  })
  const Component = (await import('../src/features/characters/CharacterFacePatchPanel.tsx')).CharacterFacePatchPanel
  const originalKit = view.props.kit
  const originalCreate = globalThis.URL.createObjectURL
  const originalRevoke = globalThis.URL.revokeObjectURL
  const created: string[] = []
  const revoked: string[] = []
  globalThis.URL.createObjectURL = () => {
    const url = `blob:face-patch-${created.length}`
    created.push(url)
    return url
  }
  globalThis.URL.revokeObjectURL = url => { revoked.push(url) }
  try {
    selectFile(view)
    await view.screen.findByText(/Patch prepared locally/)
    assert.equal(created.length, 1)
    const replacement = makeKit({ base: base({ source: '/api/v1/file/luma-base-v2.png' }) })
    view.rerender(<Component {...view.props} kit={replacement} />)
    view.rerender(<Component {...view.props} kit={originalKit} />)
    assert.equal(view.screen.queryByAltText(/Prepared wide mouth patch preview/), null)
    assert.equal(view.screen.getByRole('button', { name: 'Save pending patch' }).getAttribute('disabled'), '')
    assert.equal(uploads, 0)
    assert.deepEqual(revoked, created)
  } finally {
    globalThis.URL.createObjectURL = originalCreate
    globalThis.URL.revokeObjectURL = originalRevoke
    view.cleanup()
  }
})

test('stops saving when the parent disables the panel during upload', { concurrency: false }, async () => {
  let releaseFirst!: (value: { filename: string; path: string; url: string }) => void
  const firstUpload = new Promise<{ filename: string; path: string; url: string }>(resolve => { releaseFirst = resolve })
  let uploadCalls = 0
  let changed = 0
  const view = await viewFor({
    onChange: () => { changed += 1 },
    upload: async file => {
      uploadCalls += 1
      if (uploadCalls === 1) return firstUpload
      return { filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` }
    },
  })
  const Component = (await import('../src/features/characters/CharacterFacePatchPanel.tsx')).CharacterFacePatchPanel
  try {
    selectFile(view)
    await view.screen.findByText(/Patch prepared locally/)
    view.fireEvent.click(view.screen.getByRole('button', { name: 'Save pending patch' }))
    await view.waitFor(() => assert.equal(uploadCalls, 1))
    view.rerender(<Component {...view.props} disabled />)
    releaseFirst({ filename: 'variant.png', path: '/tmp/variant.png', url: '/api/v1/uploads/variant.png' })
    await flush()
    assert.equal(uploadCalls, 1)
    assert.equal(changed, 0)
    assert.match(view.screen.getByRole('status').textContent || '', /Cancelled stale patch operation/)
  } finally { view.cleanup() }
})

test('shows preparation errors and never uploads after a failed prepare', { concurrency: false }, async () => {
  let uploads = 0
  const view = await viewFor({
    prepare: async () => { throw new Error('synthetic prepare failed') },
    upload: async file => { uploads += 1; return { filename: file.name, path: file.name, url: `/api/v1/uploads/${file.name}` } },
  })
  try {
    selectFile(view)
    await view.screen.findByRole('alert')
    assert.match(view.screen.getByRole('alert').textContent || '', /synthetic prepare failed/)
    assert.equal(uploads, 0)
  } finally { view.cleanup() }
})

test('disables eyes, unapproved poses, and rotated anchors with explanations', { concurrency: false }, async () => {
  const eyes = await viewFor({ state: 'blink' })
  try {
    assert.match(eyes.screen.getByRole('alert').textContent || '', /only to mouth states.*eyes are handled separately/i)
    assert.equal((eyes.screen.getByLabelText(/Aligned full-image variant/) as HTMLInputElement).disabled, true)
  } finally { eyes.cleanup() }
  const pending = await viewFor({ kit: makeKit({ base: base({ reviewState: 'pending' }) }) })
  try { assert.match(pending.screen.getByRole('alert').textContent || '', /Approve this base pose/i) } finally { pending.cleanup() }
  const rotated = await viewFor({ anchor: { ...anchor, rotation: 4 } })
  try { assert.match(rotated.screen.getByRole('alert').textContent || '', /back to 0/i) } finally { rotated.cleanup() }
})
