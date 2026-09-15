import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { applyWorldSfxTranslate, parseWorldSfx, type WorldSfx } from '../sceneFx/world'
import { slotPoseAtTime } from './performance.ts'
import { cloneScene3DDocument, parseScene3DDocument } from './document.ts'
import { patchScene3DSlot } from './templates.ts'
import { WORLD_SFX_SELECT_PREFIX, type TransformPatch } from './transformGizmo.ts'
import type { Scene3DDocument } from './types.ts'

export const SCENE3D_DRAFT_PREFIX = 'hocuspocus:scene3d-draft:v1'
export const SCENE3D_DRAFT_INDEX_KEY = 'hocuspocus:scene3d-drafts:index:v1'
export const SCENE3D_LAST_PREFIX = 'hocuspocus:scene3d-last:v1:'
export const SCENE3D_HISTORY_LIMIT = 50
export const SCENE3D_MAX_DRAFT_BYTES = 1_500_000
export const SCENE3D_MAX_DRAFTS = 8
export const SCENE3D_DRAFT_VERSION = 1 as const

export type Scene3DDocumentRef = {
  workspace: string
  documentId: string
  revision: number
}

export type Scene3DSaveState =
  | 'saved'
  | 'unsaved'
  | 'saving'
  | 'conflict'
  | 'locked'
  | 'persist-error'

export type DraftStorage = {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export type Scene3DHistory = {
  identity: Scene3DDocumentRef
  past: Scene3DDocument[]
  present: Scene3DDocument
  future: Scene3DDocument[]
  checkpoint: Scene3DDocument
  group: string | null
  ownerId: string
  conflict: Scene3DDocument | null
  persistError: boolean
  locked: boolean
}

type DraftPayload = {
  version: typeof SCENE3D_DRAFT_VERSION
  identity: Scene3DDocumentRef
  ownerId: string
  epoch: number
  updatedAt: number
  document: Scene3DDocument
  checkpoint: Scene3DDocument
}

type IndexEntry = {
  key: string
  workspace: string
  documentId: string
  revision: number
  updatedAt: number
}

type SceneUpdater = Scene3DDocument | ((current: Scene3DDocument) => Scene3DDocument)

export function createOwnerId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function createDocumentId(): string {
  return `scene-${globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`}`
}

export function normalizeDocumentRef(input: Partial<Scene3DDocumentRef> & { workspace?: string }): Scene3DDocumentRef {
  const workspace = boundId(input.workspace || 'default', 120) || 'default'
  const documentId = boundId(input.documentId || createDocumentId(), 180)
  const revision = Number.isSafeInteger(input.revision) && (input.revision ?? 0) >= 0 ? Number(input.revision) : 0
  return { workspace, documentId, revision }
}

export function draftStorageKey(identity: Scene3DDocumentRef): string {
  const ref = normalizeDocumentRef(identity)
  return `${SCENE3D_DRAFT_PREFIX}:${encodeURIComponent(ref.workspace)}:${encodeURIComponent(ref.documentId)}:${ref.revision}`
}

export function lastIdentityKey(workspace: string): string {
  return `${SCENE3D_LAST_PREFIX}${encodeURIComponent(boundId(workspace || 'default', 120) || 'default')}`
}

export function sameDocumentRef(left: Scene3DDocumentRef, right: Scene3DDocumentRef): boolean {
  return left.workspace === right.workspace && left.documentId === right.documentId && left.revision === right.revision
}

export function documentsEqual(left: Scene3DDocument, right: Scene3DDocument): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function createHistory(
  document: Scene3DDocument,
  identity: Scene3DDocumentRef,
  ownerId: string,
  checkpoint = document,
): Scene3DHistory {
  const present = cloneScene3DDocument(document)
  return {
    identity: normalizeDocumentRef(identity),
    past: [],
    present,
    future: [],
    checkpoint: cloneScene3DDocument(checkpoint),
    group: null,
    ownerId,
    conflict: null,
    persistError: false,
    locked: false,
  }
}

export function withHistoryLock(history: Scene3DHistory, locked: boolean): Scene3DHistory {
  return history.locked === locked ? history : { ...history, locked }
}

export function applyHistoryChange(history: Scene3DHistory, next: Scene3DDocument, group?: string): Scene3DHistory {
  if (history.locked) return history
  const present = cloneScene3DDocument(next)
  if (documentsEqual(history.present, present)) return group === history.group ? history : { ...history, group: group ?? null }
  if (group && group === history.group) {
    return { ...history, present, persistError: false }
  }
  const past = appendPast(history.past, history.present)
  return {
    ...history,
    past,
    present,
    future: [],
    group: group ?? null,
    persistError: false,
  }
}

export function undoHistory(history: Scene3DHistory): Scene3DHistory {
  if (history.locked || history.past.length === 0) return history
  const present = history.past[history.past.length - 1]
  return {
    ...history,
    past: history.past.slice(0, -1),
    present: cloneScene3DDocument(present),
    future: [cloneScene3DDocument(history.present), ...history.future],
    group: null,
  }
}

export function redoHistory(history: Scene3DHistory): Scene3DHistory {
  if (history.locked || history.future.length === 0) return history
  const present = history.future[0]
  return {
    ...history,
    past: appendPast(history.past, history.present),
    present: cloneScene3DDocument(present),
    future: history.future.slice(1),
    group: null,
  }
}

export function endHistoryGroup(history: Scene3DHistory): Scene3DHistory {
  return history.group ? { ...history, group: null } : history
}

export function checkpointHistory(history: Scene3DHistory): Scene3DHistory {
  if (history.locked) return history
  return { ...history, checkpoint: cloneScene3DDocument(history.present), group: null }
}

export function bindSavedRevision(history: Scene3DHistory, revision: number): Scene3DHistory {
  const nextRevision = Number.isSafeInteger(revision) && revision >= 0 ? revision : history.identity.revision + 1
  return {
    ...history,
    identity: { ...history.identity, revision: nextRevision },
    checkpoint: cloneScene3DDocument(history.present),
    group: null,
  }
}

export function captureSaveTarget(history: Scene3DHistory): { document: Scene3DDocument; identity: Scene3DDocumentRef } {
  return {
    document: cloneScene3DDocument(history.present),
    identity: { ...history.identity },
  }
}

export function historySaveState(history: Scene3DHistory, saving = false): Scene3DSaveState {
  if (history.locked) return 'locked'
  if (history.conflict) return 'conflict'
  if (saving) return 'saving'
  if (history.persistError) return 'persist-error'
  return documentsEqual(history.present, history.checkpoint) ? 'saved' : 'unsaved'
}

export function resolveHistoryConflict(history: Scene3DHistory, choice: 'mine' | 'theirs'): Scene3DHistory {
  if (!history.conflict) return history
  if (choice === 'mine') return { ...history, conflict: null }
  return {
    ...applyHistoryChange({ ...history, conflict: null, locked: false }, history.conflict),
    locked: history.locked,
    conflict: null,
  }
}

export function ingestRemotePayload(history: Scene3DHistory, raw: string | null, ownerId: string): Scene3DHistory {
  const payload = parseDraftPayload(raw)
  if (!payload || payload.ownerId === ownerId) return history
  if (!sameDocumentRef(payload.identity, history.identity)) return history
  if (documentsEqual(payload.document, history.present)) return history
  return { ...history, conflict: cloneScene3DDocument(payload.document) }
}

export function persistHistoryDraft(history: Scene3DHistory, storage: DraftStorage): Scene3DHistory {
  if (history.group || history.conflict) return history
  const result = commitDraft(storage, history.identity, serializeDraft(history), true)
  if (result === 'ok') {
    return history.persistError ? { ...history, persistError: false } : history
  }
  return history.persistError ? history : { ...history, persistError: true }
}

export function readDraftPayload(storage: DraftStorage, identity: Scene3DDocumentRef): DraftPayload | null {
  const key = draftStorageKey(identity)
  const main = parseDraftPayload(readStorage(storage, key))
  if (main && sameDocumentRef(main.identity, identity)) return main
  const backup = parseDraftPayload(readStorage(storage, `${key}:bak`))
  if (backup && sameDocumentRef(backup.identity, identity)) return backup
  return null
}

export function switchHistoryDocument(
  history: Scene3DHistory,
  storage: DraftStorage,
  nextDocument: Scene3DDocument,
  nextIdentity: Scene3DDocumentRef,
  ownerId: string,
): Scene3DHistory {
  persistHistoryDraft(endHistoryGroup(history), storage)
  const identity = normalizeDocumentRef(nextIdentity)
  const restored = readDraftPayload(storage, identity)
  const next = restored
    ? historyFromDraft(restored, ownerId, history.locked)
    : withHistoryLock(createHistory(nextDocument, identity, ownerId), history.locked)
  return persistHistoryDraft(next, storage)
}

export function switchHistoryWorkspace(
  history: Scene3DHistory,
  storage: DraftStorage,
  nextWorkspace: string,
  ownerId: string,
  fallback: Scene3DDocument,
): Scene3DHistory {
  const workspace = boundId(nextWorkspace || 'default', 120) || 'default'
  if (history.identity.workspace === workspace) return history
  persistHistoryDraft(endHistoryGroup(history), storage)
  return persistHistoryDraft(withHistoryLock(restoreOrCreateHistory(fallback, workspace, ownerId, storage), history.locked), storage)
}

export function restoreOrCreateHistory(
  initial: Scene3DDocument,
  workspace: string,
  ownerId: string,
  storage: DraftStorage,
): Scene3DHistory {
  const last = readLastIdentity(storage, workspace)
  if (last) {
    const restored = readDraftPayload(storage, last)
    if (restored) return historyFromDraft(restored, ownerId, false)
  }
  return createHistory(initial, { workspace: workspace || 'default', documentId: createDocumentId(), revision: 0 }, ownerId)
}

export function acknowledgeGallerySave(
  history: Scene3DHistory,
  storage: DraftStorage,
  saved: { document: Scene3DDocument; identity: Scene3DDocumentRef; revision: number },
): Scene3DHistory {
  const sameLive = history.identity.documentId === saved.identity.documentId
    && history.identity.workspace === saved.identity.workspace
    && documentsEqual(history.present, saved.document)
  if (sameLive) return persistHistoryDraft(bindSavedRevision(history, saved.revision), storage)
  const nextIdentity = normalizeDocumentRef({ ...saved.identity, revision: saved.revision })
  commitDraft(storage, nextIdentity, serializeDraft(createHistory(saved.document, nextIdentity, history.ownerId)), false)
  return history
}

export function applyScene3DGizmoPatch(
  document: Scene3DDocument,
  id: string,
  patch: TransformPatch,
  seconds: number,
): Scene3DDocument {
  if (!id.startsWith(WORLD_SFX_SELECT_PREFIX)) return patchScene3DSlot(document, id, patch)
  return applyWorldCuePatch(document, id.slice(WORLD_SFX_SELECT_PREFIX.length), patch, seconds)
}

export function browserDraftStorage(): DraftStorage {
  return {
    getItem(key) {
      try { return window.localStorage.getItem(key) } catch { return null }
    },
    setItem(key, value) {
      window.localStorage.setItem(key, value)
    },
    removeItem(key) {
      try { window.localStorage.removeItem(key) } catch { /* keep last valid */ }
    },
  }
}

export function useScene3DHistory(initialDocument: Scene3DDocument, workspace: string, locked: boolean) {
  const ownerId = useMemo(() => createOwnerId(), [])
  const storage = useMemo(() => browserDraftStorage(), [])
  const fallbackDocument = useRef(initialDocument)
  const [history, setHistory] = useState(() => restoreOrCreateHistory(initialDocument, workspace || 'default', ownerId, storage))
  const historyRef = useRef(history)
  const commit = useCallback((updater: (current: Scene3DHistory) => Scene3DHistory) => {
    setHistory(current => {
      const next = updater(current)
      historyRef.current = next
      return next
    })
  }, [])

  useEffect(() => {
    historyRef.current = history
  }, [history])

  useEffect(() => {
    commit(current => withHistoryLock(current, locked))
  }, [locked, commit])

  useEffect(() => {
    const nextWorkspace = workspace || 'default'
    commit(current => current.identity.workspace === nextWorkspace
      ? current
      : switchHistoryWorkspace(current, storage, nextWorkspace, ownerId, fallbackDocument.current))
  }, [workspace, commit, storage, ownerId])

  useEffect(() => {
    const next = persistHistoryDraft(history, storage)
    if (next !== history) commit(() => next)
  }, [history, storage, commit])

  useEffect(() => {
    const endGroup = () => {
      commit(current => current.group ? persistHistoryDraft(endHistoryGroup(current), storage) : current)
    }
    window.addEventListener('pointerup', endGroup)
    window.addEventListener('pointercancel', endGroup)
    return () => {
      window.removeEventListener('pointerup', endGroup)
      window.removeEventListener('pointercancel', endGroup)
    }
  }, [commit, storage])

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (!isDraftStorageKey(event.key)) return
      commit(current => ingestRemotePayload(current, event.newValue, ownerId))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [commit, ownerId])

  const apply = useCallback((updater: SceneUpdater, group?: string) => {
    commit(current => applyHistoryChange(current, typeof updater === 'function' ? updater(current.present) : updater, group))
  }, [commit])

  const open = useCallback((document: Scene3DDocument, identity: Scene3DDocumentRef) => {
    commit(current => switchHistoryDocument(current, storage, document, identity, ownerId))
  }, [commit, storage, ownerId])

  const resolveConflict = useCallback((choice: 'mine' | 'theirs') => {
    commit(current => persistHistoryDraft(resolveHistoryConflict(current, choice), storage))
  }, [commit, storage])

  const acknowledgeSave = useCallback((document: Scene3DDocument, identity: Scene3DDocumentRef, revision: number) => {
    commit(current => acknowledgeGallerySave(current, storage, { document, identity, revision }))
  }, [commit, storage])
  const undo = useCallback(() => { commit(current => undoHistory(current)) }, [commit])
  const redo = useCallback(() => { commit(current => redoHistory(current)) }, [commit])
  const checkpoint = useCallback(() => { commit(current => checkpointHistory(current)) }, [commit])
  const endGroup = useCallback(() => { commit(current => endHistoryGroup(current)) }, [commit])
  const captureForSave = useCallback(() => captureSaveTarget(historyRef.current), [])

  return {
    document: history.present,
    identity: history.identity,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    saveState: historySaveState(history),
    conflict: history.conflict,
    apply,
    undo,
    redo,
    checkpoint,
    open,
    acknowledgeSave,
    captureForSave,
    resolveConflict,
    endGroup,
  }
}

function isDraftStorageKey(key: string | null): key is string {
  return Boolean(key && key.startsWith(SCENE3D_DRAFT_PREFIX) && !key.endsWith(':bak') && !key.endsWith(':tmp'))
}

function boundId(value: string, max: number): string {
  return value.trim().slice(0, max)
}

function appendPast(past: Scene3DDocument[], present: Scene3DDocument): Scene3DDocument[] {
  const next = [...past, cloneScene3DDocument(present)]
  return next.length > SCENE3D_HISTORY_LIMIT ? next.slice(next.length - SCENE3D_HISTORY_LIMIT) : next
}

function historyFromDraft(payload: DraftPayload, ownerId: string, locked = false): Scene3DHistory {
  return withHistoryLock(createHistory(payload.document, payload.identity, ownerId, payload.checkpoint), locked)
}

function serializeDraft(history: Scene3DHistory): DraftPayload {
  return {
    version: SCENE3D_DRAFT_VERSION,
    identity: { ...history.identity },
    ownerId: history.ownerId,
    epoch: Date.now(),
    updatedAt: Date.now(),
    document: cloneScene3DDocument(history.present),
    checkpoint: cloneScene3DDocument(history.checkpoint),
  }
}

function parseDraftPayload(raw: string | null): DraftPayload | null {
  if (!raw) return null
  try {
    if (encodedBytes(raw) > SCENE3D_MAX_DRAFT_BYTES) return null
    const value = JSON.parse(raw) as Partial<DraftPayload>
    return validDraftPayload(value)
  } catch {
    return null
  }
}

function validDraftPayload(value: Partial<DraftPayload> | null): DraftPayload | null {
  if (!value || value.version !== SCENE3D_DRAFT_VERSION || typeof value.ownerId !== 'string') return null
  if (!value.identity || typeof value.identity.workspace !== 'string' || typeof value.identity.documentId !== 'string') return null
  const document = parseScene3DDocument(value.document)
  const checkpoint = parseScene3DDocument(value.checkpoint) ?? document
  if (!document || !checkpoint) return null
  return {
    version: SCENE3D_DRAFT_VERSION,
    identity: normalizeDocumentRef(value.identity),
    ownerId: value.ownerId.slice(0, 80),
    epoch: Number(value.epoch) || 0,
    updatedAt: Number(value.updatedAt) || 0,
    document,
    checkpoint,
  }
}

function commitDraft(
  storage: DraftStorage,
  identity: Scene3DDocumentRef,
  payload: DraftPayload,
  rememberLast: boolean,
): 'ok' | 'quota' | 'too-large' {
  const result = writeDraftRecord(storage, identity, payload)
  if (result === 'ok') {
    if (rememberLast) writeLastIdentity(storage, identity)
    pruneDraftIndex(storage, draftStorageKey(identity))
  }
  return result
}

function writeDraftRecord(storage: DraftStorage, identity: Scene3DDocumentRef, payload: DraftPayload): 'ok' | 'quota' | 'too-large' {
  const serialized = JSON.stringify(payload)
  if (encodedBytes(serialized) > SCENE3D_MAX_DRAFT_BYTES) return 'too-large'
  const key = draftStorageKey(identity)
  const previous = readStorage(storage, key)
  try {
    storage.setItem(`${key}:tmp`, serialized)
    if (previous) storage.setItem(`${key}:bak`, previous)
    storage.setItem(key, serialized)
    try { storage.setItem(`${key}:bak`, serialized) } catch { /* key already holds the new valid draft */ }
    try { storage.removeItem(`${key}:tmp`) } catch { /* last valid already in key */ }
    rememberIndex(storage, identity, payload.updatedAt)
    return 'ok'
  } catch {
    return 'quota'
  }
}

function rememberIndex(storage: DraftStorage, identity: Scene3DDocumentRef, updatedAt: number) {
  const entries = readIndex(storage).filter(entry => !sameDocumentRef(entry, identity))
  entries.push({
    key: draftStorageKey(identity),
    workspace: identity.workspace,
    documentId: identity.documentId,
    revision: identity.revision,
    updatedAt,
  })
  writeIndex(storage, entries)
}

function pruneDraftIndex(storage: DraftStorage, keepKey: string) {
  const entries = readIndex(storage).sort((left, right) => right.updatedAt - left.updatedAt)
  const kept: IndexEntry[] = []
  for (const entry of entries) {
    const payload = readDraftPayload(storage, entry)
    const unsaved = payload && !documentsEqual(payload.document, payload.checkpoint)
    if (kept.length < SCENE3D_MAX_DRAFTS || entry.key === keepKey || unsaved) {
      kept.push(entry)
      continue
    }
    try {
      storage.removeItem(entry.key)
      storage.removeItem(`${entry.key}:bak`)
      storage.removeItem(`${entry.key}:tmp`)
    } catch { /* keep last valid of the active document */ }
  }
  writeIndex(storage, kept)
}

function readIndex(storage: DraftStorage): IndexEntry[] {
  try {
    const parsed = JSON.parse(readStorage(storage, SCENE3D_DRAFT_INDEX_KEY) || '[]') as IndexEntry[]
    return Array.isArray(parsed) ? parsed.filter(item => item && typeof item.key === 'string') : []
  } catch {
    return []
  }
}

function writeIndex(storage: DraftStorage, entries: IndexEntry[]) {
  try {
    storage.setItem(SCENE3D_DRAFT_INDEX_KEY, JSON.stringify(entries))
  } catch { /* index is advisory */ }
}

function readLastIdentity(storage: DraftStorage, workspace: string): Scene3DDocumentRef | null {
  try {
    const parsed = JSON.parse(readStorage(storage, lastIdentityKey(workspace)) || 'null') as Scene3DDocumentRef | null
    if (!parsed || typeof parsed.documentId !== 'string') return null
    return normalizeDocumentRef({ ...parsed, workspace })
  } catch {
    return null
  }
}

function writeLastIdentity(storage: DraftStorage, identity: Scene3DDocumentRef) {
  try {
    storage.setItem(lastIdentityKey(identity.workspace), JSON.stringify(identity))
  } catch { /* last pointer is advisory */ }
}

function readStorage(storage: DraftStorage, key: string): string | null {
  try { return storage.getItem(key) } catch { return null }
}

function encodedBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

function applyWorldCuePatch(document: Scene3DDocument, cueId: string, patch: TransformPatch, seconds: number): Scene3DDocument {
  const DEG = 180 / Math.PI
  return {
    ...document,
    worldSfx: parseWorldSfx((document.worldSfx ?? []).map(cue => patchWorldCue(cue, cueId, patch, document, seconds, DEG))),
  }
}

function patchWorldCue(
  cue: WorldSfx,
  cueId: string,
  patch: TransformPatch,
  document: Scene3DDocument,
  seconds: number,
  deg: number,
): WorldSfx {
  if (cue.id !== cueId) return cue
  let next: WorldSfx = { ...cue }
  if (patch.position) {
    const slot = cue.anchor?.slotId ? document.slots.find(item => item.id === cue.anchor!.slotId) : undefined
    next = applyWorldSfxTranslate(
      next,
      patch.position,
      slot ? slotPoseAtTime(slot, seconds, document.duration) : undefined,
      patch.anchorOffset,
    )
  }
  if (patch.worldRotation) {
    next = { ...next, rotation: { x: patch.worldRotation[0] * deg, y: patch.worldRotation[1] * deg, z: patch.worldRotation[2] * deg } }
  }
  if (patch.scale !== undefined) next = { ...next, scale: patch.scale }
  return next
}
