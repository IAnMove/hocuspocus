import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import {
  clearSpeechDraft,
  readSpeechDraft,
  speechDraftStorageKey,
  writeSpeechDraft,
} from '../src/lib/characterSpeechDraft.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
})

test('character-specific speech drafts preserve other characters and the general workshop draft', () => {
  const first = createCharacterKit('First'), second = createCharacterKit('Second')
  writeSpeechDraft('scoped-voices', { baseRevision: 2, kit: first })
  writeSpeechDraft('scoped-voices', { baseRevision: 3, kit: first }, first.id)
  writeSpeechDraft('scoped-voices', { baseRevision: 4, kit: second }, second.id)
  assert.equal(readSpeechDraft('scoped-voices')?.baseRevision, 2)
  assert.equal(readSpeechDraft('scoped-voices', first.id)?.baseRevision, 3)
  assert.equal(readSpeechDraft('scoped-voices', second.id)?.baseRevision, 4)
  clearSpeechDraft('scoped-voices', first.id)
  assert.equal(readSpeechDraft('scoped-voices', first.id), null)
  assert.equal(readSpeechDraft('scoped-voices', second.id)?.kit.id, second.id)
  assert.equal(readSpeechDraft('scoped-voices')?.kit.id, first.id)
  assert.throws(() => writeSpeechDraft('scoped-voices', { baseRevision: 4, kit: first }, second.id), /another character/)
})

const asset = (id, reviewState = 'pending', source = `/${id}.png`, kind = 'overlay') => ({
  id,
  name: id,
  source,
  kind,
  alphaStatus: kind === 'image' ? 'opaque' : 'transparent',
  reviewState,
})

const patchMetadata = {
  version: 1,
  poseId: 'base',
  poseSource: 'base.png',
  variantSource: 'variant.png',
  sourceWidth: 32,
  sourceHeight: 32,
  region: { x: 12, y: 12, size: 8 },
  feather: 0.08,
  poseSha256: 'a'.repeat(64),
  variantSha256: 'b'.repeat(64),
  outputSha256: 'c'.repeat(64),
}

function sampleKit() {
  const kit = createCharacterKit('Luma')
  kit.base = asset('luma-base', 'approved', '/base.png', 'image')
  kit.identityReference = { ...kit.base, id: 'luma-identity' }
  kit.mouth = {
    closed: asset('closed', 'approved', '/closed.png'),
    small: asset('small', 'pending', '/small.png'),
    wide: { ...asset('wide', 'rejected'), facePatch: patchMetadata },
  }
  kit.eyes = { open: asset('eyes-open', 'approved') }
  kit.poses = { side: asset('side', 'approved', '/side.png', 'image') }
  kit.anchors = {
    base: {
      mouth: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 },
      mouthStates: {
        closed: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 },
      },
    },
  }
  return kit
}

function resetStorage() {
  dom.window.sessionStorage.clear()
  for (const workspace of ['default', 'workspace-a', 'workspace-b', 'malformed', 'blob', 'oversized', 'quota']) {
    clearSpeechDraft(workspace)
  }
}

test('round-trips a workspace draft with its CAS revision, approvals, and face patch metadata unchanged', { concurrency: false }, () => {
  resetStorage()
  const kit = sampleKit()
  const draft = { baseRevision: 41, kit }

  writeSpeechDraft('workspace-a', draft)

  assert.deepEqual(readSpeechDraft('workspace-a'), draft)
  assert.equal(readSpeechDraft('workspace-a').kit.base.reviewState, 'approved')
  assert.equal(readSpeechDraft('workspace-a').kit.mouth.small.reviewState, 'pending')
  assert.equal(readSpeechDraft('workspace-a').kit.mouth.wide.reviewState, 'rejected')
  assert.deepEqual(readSpeechDraft('workspace-a').kit.mouth.wide.facePatch, patchMetadata)
})

test('namespaces drafts by encoded workspace and clear removes only the requested draft', { concurrency: false }, () => {
  resetStorage()
  const kitA = sampleKit()
  const kitB = { ...sampleKit(), id: 'luma-b', name: 'Luma B' }

  writeSpeechDraft('team/a', { baseRevision: 3, kit: kitA })
  writeSpeechDraft('team b', { baseRevision: 8, kit: kitB })

  assert.notEqual(speechDraftStorageKey('team/a'), speechDraftStorageKey('team b'))
  assert.equal(readSpeechDraft('team/a').kit.id, kitA.id)
  assert.equal(readSpeechDraft('team b').kit.id, kitB.id)
  clearSpeechDraft('team/a')
  assert.equal(readSpeechDraft('team/a'), null)
  assert.equal(readSpeechDraft('team b').baseRevision, 8)
})

test('clears malformed, mismatched-workspace, invalid-face-patch, and transient-source payloads', { concurrency: false }, () => {
  resetStorage()
  const key = speechDraftStorageKey('malformed')
  dom.window.sessionStorage.setItem(key, '{not-json')
  assert.equal(readSpeechDraft('malformed'), null)
  assert.equal(dom.window.sessionStorage.getItem(key), null)

  dom.window.sessionStorage.setItem(key, JSON.stringify({
    version: 1,
    workspace: 'other-workspace',
    baseRevision: 1,
    kit: sampleKit(),
  }))
  assert.equal(readSpeechDraft('malformed'), null)
  assert.equal(dom.window.sessionStorage.getItem(key), null)

  const invalidPatchKit = sampleKit()
  invalidPatchKit.mouth.wide.facePatch = { ...patchMetadata, poseSha256: 'invalid' }
  dom.window.sessionStorage.setItem(key, JSON.stringify({
    version: 1,
    workspace: 'malformed',
    baseRevision: 1,
    kit: invalidPatchKit,
  }))
  assert.equal(readSpeechDraft('malformed'), null)
  assert.equal(dom.window.sessionStorage.getItem(key), null)

  const blobKit = sampleKit()
  blobKit.base.source = 'blob:temporary-base'
  assert.throws(
    () => writeSpeechDraft('blob', { baseRevision: 2, kit: blobKit }),
    /persistent|blob|data/i,
  )
  assert.equal(readSpeechDraft('blob'), null)
})

test('rejects a serialized draft over the recovery bound before writing it', { concurrency: false }, () => {
  resetStorage()
  const oversized = sampleKit()
  oversized.provenance = [{ note: 'x'.repeat(2 * 1024 * 1024) }]

  assert.throws(
    () => writeSpeechDraft('oversized', { baseRevision: 5, kit: oversized }),
    /too large|2 MiB/i,
  )
  assert.equal(readSpeechDraft('oversized'), null)
  assert.equal(dom.window.sessionStorage.getItem(speechDraftStorageKey('oversized')), null)
})

test('rejects malformed draft shapes and invalid revisions while clearing the prior recovery draft', { concurrency: false }, () => {
  resetStorage()
  const kit = sampleKit()
  writeSpeechDraft('default', { baseRevision: 9, kit })

  assert.throws(() => writeSpeechDraft('default', { baseRevision: -1, kit }), /revision/i)
  assert.throws(() => writeSpeechDraft('default', { baseRevision: 10, kit: { ...kit, style: 'unknown' } }), /style/i)
  assert.equal(readSpeechDraft('default'), null)
})

test('clears a prior recovery draft when a newer serialized edit exceeds the size bound', { concurrency: false }, () => {
  resetStorage()
  const kit = sampleKit()
  writeSpeechDraft('oversized', { baseRevision: 4, kit })
  const oversized = { ...kit, provenance: [{ note: 'x'.repeat(2 * 1024 * 1024) }] }

  assert.throws(
    () => writeSpeechDraft('oversized', { baseRevision: 5, kit: oversized }),
    /too large|2 MiB/i,
  )
  assert.equal(readSpeechDraft('oversized'), null)
})

test('returns the replacement draft from the safe fallback when browser storage rejects a write', { concurrency: false }, () => {
  resetStorage()
  const previous = sampleKit()
  writeSpeechDraft('quota', { baseRevision: 4, kit: previous })
  const replacement = { ...previous, name: 'Luma replacement' }
  const storagePrototype = Object.getPrototypeOf(dom.window.sessionStorage)
  const originalSetItem = storagePrototype.setItem
  try {
    storagePrototype.setItem = () => { throw new Error('quota') }
    writeSpeechDraft('quota', { baseRevision: 5, kit: replacement })
  } finally {
    storagePrototype.setItem = originalSetItem
  }

  const recovered = readSpeechDraft('quota')
  assert.equal(recovered?.baseRevision, 5)
  assert.equal(recovered?.kit.name, 'Luma replacement')
})
