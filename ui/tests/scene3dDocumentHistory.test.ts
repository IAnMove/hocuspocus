import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate, patchScene3DSlot } from '../src/features/scene3d/templates.ts'
import { defaultSpeech, type FacePlacement } from '../src/features/scene3d/speech/types.ts'
import { defaultMediaScreen } from '../src/features/scene3d/mediaScreen.ts'
import { createWorldSfx, parseWorldSfx } from '../src/features/sceneFx/world.ts'
import { parseSceneFx } from '../src/features/sceneFx/types.ts'
import {
  SCENE3D_DRAFT_PREFIX,
  acknowledgeGallerySave,
  applyHistoryChange,
  applyScene3DGizmoPatch,
  captureSaveTarget,
  createDocumentId,
  createHistory,
  createOwnerId,
  documentsEqual,
  draftStorageKey,
  endHistoryGroup,
  historySaveState,
  ingestRemotePayload,
  lastIdentityKey,
  persistHistoryDraft,
  readDraftPayload,
  redoHistory,
  restoreOrCreateHistory,
  switchHistoryDocument,
  switchHistoryWorkspace,
  undoHistory,
  withHistoryLock,
  type DraftStorage,
  type Scene3DDocumentRef,
} from '../src/features/scene3d/documentHistory.ts'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document })

const face: FacePlacement = {
  meshIndex: 0,
  center: [0, 1.5, 0.1],
  size: [0.1, 0.08],
  skin: [0.5, 0.3, 0.2],
  eyes: {
    left: [-0.04, 1.55, 0.1],
    right: [0.04, 1.55, 0.1],
    size: [0.04, 0.02],
    skinLeft: [0.5, 0.3, 0.2],
    skinRight: [0.5, 0.3, 0.2],
  },
}

function memoryStorage(quota = Number.POSITIVE_INFINITY): DraftStorage & { map: Map<string, string> } {
  const map = new Map<string, string>()
  return {
    map,
    getItem(key) { return map.get(key) ?? null },
    setItem(key, value) {
      if (value.length > quota) throw new Error('quota')
      map.set(key, value)
    },
    removeItem(key) { map.delete(key) },
  }
}

function identity(documentId: string, workspace = 'ws-a', revision = 0): Scene3DDocumentRef {
  return { workspace, documentId, revision }
}

function sampleDocument(): Scene3DDocument {
  const document = applyScene3DTemplate('two-shot')
  document.slots[0].sourceUrl = '/hero.glb'
  document.slots[0].sourceRef = { workspaceId: 'ws-a', filename: 'hero.glb', url: '/hero.glb', assetId: 'hero' }
  document.slots[0].speech = { ...defaultSpeech(), face, cues: [{ start: 0, end: 0.2, viseme: 'A' }] }
  return document
}

function moveMouth(document: Scene3DDocument, x: number): Scene3DDocument {
  const slot = document.slots[0]
  const current = slot.speech?.face ?? face
  return patchScene3DSlot(document, slot.id, {
    speech: { ...defaultSpeech(), ...slot.speech, face: { ...current, center: [x, current.center[1], current.center[2]] } },
  })
}

function changeGlb(document: Scene3DDocument, url: string): Scene3DDocument {
  return patchScene3DSlot(document, document.slots[0].id, {
    sourceUrl: url,
    sourceRef: { workspaceId: 'ws-a', filename: url.split('/').pop() || 'model.glb', url, assetId: 'next' },
    media: 'model3d',
  })
}

function addScreen(document: Scene3DDocument): Scene3DDocument {
  const id = 'screen_test'
  return {
    ...document,
    slots: [...document.slots, {
      id, slot: 'prop', media: 'screen', sourceUrl: '', clip: null,
      position: [0, 0, -2], rotationY: 0, scale: 1, screen: { ...defaultMediaScreen(), sourceUrl: '/board.png' },
    }],
  }
}

function addSfx(document: Scene3DDocument): Scene3DDocument {
  const world = createWorldSfx('sparks', document.duration, (document.worldSfx ?? []).map(cue => cue.id))
  return {
    ...document,
    worldSfx: parseWorldSfx([...(document.worldSfx ?? []), world]),
    sfx: parseSceneFx([...(document.sfx ?? []), { id: 'fx-test', kind: 'sparks', start: 0, end: 1 }]),
  }
}

test('undo and redo restore mouth, GLB, screen and SFX fields', () => {
  const start = sampleDocument()
  const id = identity('doc-a')
  let history = createHistory(start, id, 'tab-1')
  const mouth = moveMouth(start, 0.42)
  history = applyHistoryChange(history, mouth)
  const glb = changeGlb(mouth, '/villain.glb')
  history = applyHistoryChange(history, glb)
  const screened = addScreen(glb)
  history = applyHistoryChange(history, screened)
  const withSfx = addSfx(screened)
  history = applyHistoryChange(history, withSfx)
  assert.equal(history.present.slots[0].speech?.face?.center[0], 0.42)
  assert.equal(history.present.slots[0].sourceUrl, '/villain.glb')
  assert.equal(history.present.slots.some(slot => slot.media === 'screen' && slot.screen?.sourceUrl === '/board.png'), true)
  assert.equal((history.present.worldSfx ?? []).length, 1)
  assert.equal((history.present.sfx ?? []).length, 1)
  history = undoHistory(history)
  history = undoHistory(history)
  history = undoHistory(history)
  history = undoHistory(history)
  assert.equal(documentsEqual(history.present, start), true)
  assert.equal(history.present.slots[0].speech?.face?.center[0], 0)
  assert.equal(history.present.slots[0].sourceUrl, '/hero.glb')
  assert.equal(history.present.slots.some(slot => slot.media === 'screen'), false)
  history = redoHistory(history)
  history = redoHistory(history)
  history = redoHistory(history)
  history = redoHistory(history)
  assert.equal(history.present.slots[0].speech?.face?.center[0], 0.42)
  assert.equal(history.present.slots[0].sourceUrl, '/villain.glb')
  assert.equal(history.present.slots.at(-1)?.screen?.sourceUrl, '/board.png')
  assert.equal(history.present.worldSfx?.[0]?.kind, 'sparks')
  assert.equal(history.present.sfx?.[0]?.kind, 'sparks')
})

test('a drag group stores one undo step instead of hundreds of in-between states', () => {
  const start = sampleDocument()
  let history = createHistory(start, identity('drag'), 'tab-1')
  let current = start
  for (let index = 1; index <= 200; index += 1) {
    current = patchScene3DSlot(current, current.slots[0].id, { position: [index / 100, 0, 0] })
    history = applyHistoryChange(history, current, 'drag:subject_1')
  }
  history = endHistoryGroup(history)
  assert.equal(history.past.length, 1)
  assert.equal(history.present.slots[0].position[0], 2)
  history = undoHistory(history)
  assert.deepEqual(history.present.slots[0].position, start.slots[0].position)
  history = redoHistory(history)
  assert.equal(history.present.slots[0].position[0], 2)
})

test('gizmo patches during a drag still collapse to one history entry', () => {
  const start = sampleDocument()
  let history = createHistory(start, identity('gizmo'), 'tab-1')
  for (let index = 1; index <= 80; index += 1) {
    const next = applyScene3DGizmoPatch(history.present, start.slots[0].id, { position: [index, 0, 0] }, 0)
    history = applyHistoryChange(history, next, `drag:${start.slots[0].id}`)
  }
  assert.equal(history.past.length, 1)
  assert.equal(history.present.slots[0].position[0], 80)
})

test('refresh and A→B→A recover the matching workspace/document/revision draft', () => {
  const storage = memoryStorage()
  const owner = createOwnerId()
  const docA = changeGlb(sampleDocument(), '/a.glb')
  const docB = changeGlb(sampleDocument(), '/b.glb')
  const idA = identity('scene-a', 'ws-a', 3)
  const idB = identity('scene-b', 'ws-a', 1)
  let history = applyHistoryChange(createHistory(sampleDocument(), idA, owner), docA)
  history = persistHistoryDraft(history, storage)
  history = switchHistoryDocument(history, storage, docB, idB, owner)
  history = applyHistoryChange(history, moveMouth(docB, 0.7))
  history = persistHistoryDraft(history, storage)
  history = switchHistoryDocument(history, storage, sampleDocument(), idA, owner)
  assert.equal(history.identity.documentId, 'scene-a')
  assert.equal(history.present.slots[0].sourceUrl, '/a.glb')
  const restored = restoreOrCreateHistory(createDefaultScene3DDocument(), 'ws-a', owner, storage)
  assert.equal(restored.identity.documentId, 'scene-a')
  assert.equal(restored.identity.revision, 3)
  assert.equal(restored.present.slots[0].sourceUrl, '/a.glb')
  history = switchHistoryDocument(history, storage, docB, idB, owner)
  assert.equal(history.present.slots[0].speech?.face?.center[0], 0.7)
  assert.equal(history.present.slots[0].sourceUrl, '/b.glb')
})

test('full or corrupt storage keeps the last valid draft', () => {
  const storage = memoryStorage()
  const start = sampleDocument()
  const id = identity('keep-valid')
  persistHistoryDraft(applyHistoryChange(createHistory(start, id, 'tab-1'), changeGlb(start, '/kept.glb')), storage)
  const key = draftStorageKey(id)
  const valid = storage.getItem(key)
  assert.ok(valid)
  storage.setItem(key, '{not-json')
  const recovered = readDraftPayload(storage, id)
  assert.equal(recovered?.document.slots[0].sourceUrl, '/kept.glb')
  assert.equal(storage.getItem(key), '{not-json')
  const tight = memoryStorage(20)
  tight.map.set(key, valid!)
  tight.map.set(`${key}:bak`, valid!)
  const failed = persistHistoryDraft(applyHistoryChange(createHistory(start, id, 'tab-1'), changeGlb(start, '/too-big.glb')), tight)
  assert.equal(failed.persistError, true)
  assert.equal(tight.getItem(key), valid)
  assert.equal(historySaveState(failed), 'persist-error')
})

test('save snapshot stays on the original document after a switch; lock blocks mutations', () => {
  const storage = memoryStorage()
  const docA = changeGlb(sampleDocument(), '/export-a.glb')
  const docB = changeGlb(sampleDocument(), '/export-b.glb')
  let history = applyHistoryChange(createHistory(sampleDocument(), identity('export-a'), 'tab-1'), docA)
  const snapshot = captureSaveTarget(history)
  history = switchHistoryDocument(history, storage, docB, identity('export-b'), 'tab-1')
  assert.equal(snapshot.identity.documentId, 'export-a')
  assert.equal(snapshot.document.slots[0].sourceUrl, '/export-a.glb')
  assert.equal(history.present.slots[0].sourceUrl, '/export-b.glb')
  const locked = withHistoryLock(history, true)
  const ignored = applyHistoryChange(locked, changeGlb(locked.present, '/mutated.glb'))
  assert.equal(ignored.present.slots[0].sourceUrl, '/export-b.glb')
  assert.equal(historySaveState(locked), 'locked')
  const undone = undoHistory(locked)
  assert.equal(undone.present.slots[0].sourceUrl, '/export-b.glb')
})

test('gallery save writes a new revision and leaves the previous payload untouched', () => {
  const storage = memoryStorage()
  const gallery = sampleDocument()
  const frozen = JSON.stringify(gallery)
  const from = identity('gallery-a', 'ws-a', 4)
  let history = applyHistoryChange(createHistory(gallery, from, 'tab-1'), moveMouth(gallery, 0.2))
  history = persistHistoryDraft(history, storage)
  const saved = moveMouth(gallery, 0.2)
  history = acknowledgeGallerySave(history, storage, { document: saved, identity: from, revision: 9 })
  assert.equal(JSON.stringify(gallery), frozen)
  assert.equal(history.identity.revision, 9)
  assert.equal(historySaveState(history), 'saved')
  const previous = readDraftPayload(storage, from)
  assert.equal(previous?.document.slots[0].speech?.face?.center[0], 0.2)
  const next = readDraftPayload(storage, { ...from, revision: 9 })
  assert.equal(next?.identity.revision, 9)
  const other = applyHistoryChange(createHistory(sampleDocument(), identity('gallery-b'), 'tab-1'), changeGlb(sampleDocument(), '/other.glb'))
  const skipped = acknowledgeGallerySave(other, storage, { document: saved, identity: from, revision: 10 })
  assert.equal(skipped.identity.documentId, 'gallery-b')
  assert.equal(skipped.present.slots[0].sourceUrl, '/other.glb')
})

test('workspace switch persists the source draft and restores the destination last document', () => {
  const storage = memoryStorage()
  const owner = createOwnerId()
  const fallback = sampleDocument()
  const docA = changeGlb(sampleDocument(), '/ws-a.glb')
  const docB = changeGlb(sampleDocument(), '/ws-b.glb')
  persistHistoryDraft(applyHistoryChange(createHistory(sampleDocument(), identity('scene-b', 'ws-b', 0), owner), docB), storage)
  let history = applyHistoryChange(createHistory(sampleDocument(), identity('scene-a', 'ws-a', 0), owner), docA)
  history = persistHistoryDraft(history, storage)
  history = switchHistoryWorkspace(history, storage, 'ws-b', owner, fallback)
  assert.equal(history.identity.workspace, 'ws-b')
  assert.equal(history.identity.documentId, 'scene-b')
  assert.equal(history.present.slots[0].sourceUrl, '/ws-b.glb')
  assert.equal(readDraftPayload(storage, identity('scene-a', 'ws-a', 0))?.document.slots[0].sourceUrl, '/ws-a.glb')
  history = applyHistoryChange(history, changeGlb(history.present, '/ws-b-edited.glb'))
  history = persistHistoryDraft(history, storage)
  history = switchHistoryWorkspace(history, storage, 'ws-a', owner, fallback)
  assert.equal(history.identity.documentId, 'scene-a')
  assert.equal(history.present.slots[0].sourceUrl, '/ws-a.glb')
  history = switchHistoryWorkspace(history, storage, 'ws-b', owner, fallback)
  assert.equal(history.present.slots[0].sourceUrl, '/ws-b-edited.glb')
})

test('workspace switch into an empty workspace opens a fresh fallback instead of retagging the source', () => {
  const storage = memoryStorage()
  const owner = createOwnerId()
  const fallback = sampleDocument()
  const docA = changeGlb(sampleDocument(), '/keep-a.glb')
  let history = persistHistoryDraft(applyHistoryChange(createHistory(sampleDocument(), identity('scene-a', 'ws-a', 0), owner), docA), storage)
  history = switchHistoryWorkspace(history, storage, 'ws-empty', owner, fallback)
  assert.equal(history.identity.workspace, 'ws-empty')
  assert.notEqual(history.identity.documentId, 'scene-a')
  assert.equal(history.present.slots[0].sourceUrl, fallback.slots[0].sourceUrl)
  assert.equal(readDraftPayload(storage, identity('scene-a', 'ws-a', 0))?.document.slots[0].sourceUrl, '/keep-a.glb')
  const lastEmpty = JSON.parse(storage.getItem(lastIdentityKey('ws-empty')) || 'null') as Scene3DDocumentRef
  assert.equal(lastEmpty.workspace, 'ws-empty')
  assert.notEqual(lastEmpty.documentId, 'scene-a')
})

test('gallery save that no longer matches the live document does not steal the last-identity pointer', () => {
  const storage = memoryStorage()
  const gallery = sampleDocument()
  const from = identity('gallery-a', 'ws-a', 4)
  let live = persistHistoryDraft(applyHistoryChange(createHistory(gallery, from, 'tab-1'), moveMouth(gallery, 0.2)), storage)
  const saved = live.present
  live = switchHistoryDocument(live, storage, changeGlb(sampleDocument(), '/other.glb'), identity('gallery-b', 'ws-a', 0), 'tab-1')
  const skipped = acknowledgeGallerySave(live, storage, { document: saved, identity: from, revision: 9 })
  assert.equal(skipped.identity.documentId, 'gallery-b')
  assert.equal(JSON.parse(storage.getItem(lastIdentityKey('ws-a')) || 'null').documentId, 'gallery-b')
  const restored = restoreOrCreateHistory(createDefaultScene3DDocument(), 'ws-a', 'tab-1', storage)
  assert.equal(restored.identity.documentId, 'gallery-b')
  assert.equal(restored.present.slots[0].sourceUrl, '/other.glb')
  assert.equal(readDraftPayload(storage, { ...from, revision: 9 })?.identity.revision, 9)
})

test('edits after a gallery save stay on the last-identity pointer', () => {
  const storage = memoryStorage()
  const start = sampleDocument()
  const from = identity('live-edit', 'ws-a', 1)
  let history = persistHistoryDraft(applyHistoryChange(createHistory(start, from, 'tab-1'), moveMouth(start, 0.2)), storage)
  const saved = history.present
  history = applyHistoryChange(history, changeGlb(history.present, '/after-save.glb'))
  history = acknowledgeGallerySave(history, storage, { document: saved, identity: from, revision: 8 })
  assert.equal(history.identity.revision, 1)
  assert.equal(history.present.slots[0].sourceUrl, '/after-save.glb')
  history = persistHistoryDraft(history, storage)
  const restored = restoreOrCreateHistory(createDefaultScene3DDocument(), 'ws-a', 'tab-1', storage)
  assert.equal(restored.identity.revision, 1)
  assert.equal(restored.present.slots[0].sourceUrl, '/after-save.glb')
})

test('another tab marks an explicit conflict instead of clobbering the live document', () => {
  const start = sampleDocument()
  let history = applyHistoryChange(createHistory(start, identity('live'), 'tab-mine'), changeGlb(start, '/mine.glb'))
  const theirs = JSON.stringify({
    version: 1,
    identity: identity('live'),
    ownerId: 'tab-theirs',
    epoch: 2,
    updatedAt: Date.now(),
    document: changeGlb(start, '/theirs.glb'),
    checkpoint: start,
  })
  history = ingestRemotePayload(history, theirs, 'tab-mine')
  assert.equal(history.conflict?.slots[0].sourceUrl, '/theirs.glb')
  assert.equal(history.present.slots[0].sourceUrl, '/mine.glb')
  assert.equal(historySaveState(history), 'conflict')
  assert.ok(draftStorageKey(identity('live')).startsWith(SCENE3D_DRAFT_PREFIX))
  assert.ok(createDocumentId().startsWith('scene-'))
})
