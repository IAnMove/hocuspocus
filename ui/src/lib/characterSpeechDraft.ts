import { safeStorageGet, safeStorageRemove, safeStorageSet } from './safeStorage'
import { validateFacePatchMetadata } from './characterFacePatch'
import type { CharacterKit, CharacterKitAsset } from './characterKit'

const STORAGE_PREFIX = 'hocuspocus-character-speech-draft-v1'
const PAYLOAD_VERSION = 1
const MAX_SERIALIZED_BYTES = 2 * 1024 * 1024
const MAX_KIT_ID_LENGTH = 120
const MAX_ASSET_NAME_LENGTH = 240
const MAX_SOURCE_LENGTH = 1200
const MAX_PROMPT_LENGTH = 4000
const MAX_WORKSPACE_LENGTH = 120
const MAX_PROVENANCE_ENTRIES = 500
const MAX_POSES = 32
const ID_PATTERN = new RegExp(`^[A-Za-z0-9][A-Za-z0-9._-]{0,${MAX_KIT_ID_LENGTH - 1}}$`)
const STYLES = new Set<CharacterKit['style']>(['cutout', 'children-illustration', 'anime-2d'])
const REVIEW_STATES = new Set<CharacterKitAsset['reviewState']>(['pending', 'approved', 'rejected'])
const ALPHA_STATES = new Set<CharacterKitAsset['alphaStatus']>(['unknown', 'transparent', 'opaque'])
const MOUTH_STATES = new Set(['closed', 'small', 'wide', 'round'])
const EYE_STATES = new Set(['open', 'blink'])

export type CharacterSpeechDraft = {
  baseRevision: number
  kit: CharacterKit
}

type PersistedCharacterSpeechDraft = CharacterSpeechDraft & {
  version: typeof PAYLOAD_VERSION
  workspace: string
}

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isBoundedString(value: unknown, maximum: number, required = false): value is string {
  if (typeof value !== 'string' || value.length > maximum || [...value].some(char => char.charCodeAt(0) < 32)) return false
  return !required || value.trim().length > 0
}

function isPersistentSource(value: unknown): value is string {
  return isBoundedString(value, MAX_SOURCE_LENGTH, true)
    && value === value.trim()
    && !/^(?:blob|data|javascript|vbscript|file):/i.test(value)
}

function isIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length <= MAX_KIT_ID_LENGTH && ID_PATTERN.test(value)
}

function isSafeRevision(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function validateOptionalString(value: unknown, maximum: number, label: string): void {
  if (value !== undefined && !isBoundedString(value, maximum)) throw new Error(`${label} is invalid.`)
}

function validateAsset(value: unknown, label: string): asserts value is CharacterKitAsset {
  if (!isRecord(value)) throw new Error(`${label} must be an object.`)
  if (!isIdentifier(value.id)) throw new Error(`${label} id is invalid.`)
  if (!isBoundedString(value.name, MAX_ASSET_NAME_LENGTH, true)) throw new Error(`${label} name is invalid.`)
  if (!isPersistentSource(value.source)) throw new Error(`${label} source must be a persistent image URL; blob/data URLs are not supported.`)
  if (value.kind !== 'image' && value.kind !== 'overlay') throw new Error(`${label} kind is invalid.`)
  if (typeof value.alphaStatus !== 'string' || !ALPHA_STATES.has(value.alphaStatus as CharacterKitAsset['alphaStatus'])) {
    throw new Error(`${label} alpha status is invalid.`)
  }
  if (typeof value.reviewState !== 'string' || !REVIEW_STATES.has(value.reviewState as CharacterKitAsset['reviewState'])) {
    throw new Error(`${label} review state is invalid.`)
  }
  validateOptionalString(value.prompt, MAX_PROMPT_LENGTH, `${label} prompt`)
  validateOptionalString(value.model, MAX_ASSET_NAME_LENGTH, `${label} model`)
  validateOptionalString(value.workspace, MAX_WORKSPACE_LENGTH, `${label} workspace`)
  if (value.facePatch !== undefined) {
    if (value.kind !== 'overlay') throw new Error(`${label} face patch requires an overlay asset.`)
    try {
      validateFacePatchMetadata(value.facePatch)
    } catch (cause) {
      throw new Error(`${label} face patch is invalid: ${cause instanceof Error ? cause.message : String(cause)}`)
    }
  }
}

function validateAssetRecord(value: unknown, label: string, allowedKeys?: ReadonlySet<string>): void {
  if (!isRecord(value)) throw new Error(`${label} must be an object.`)
  for (const [key, asset] of Object.entries(value)) {
    if (allowedKeys && !allowedKeys.has(key)) throw new Error(`${label} contains an unknown state.`)
    validateAsset(asset, `${label}.${key}`)
  }
}

function validateAnchor(value: unknown, label: string): void {
  if (!isRecord(value)) throw new Error(`${label} must be an object.`)
  const bounds: Record<string, [number, number]> = {
    offsetX: [-200, 200],
    offsetY: [-200, 200],
    scale: [0.001, 20],
    rotation: [-360, 360],
  }
  for (const [field, [minimum, maximum]] of Object.entries(bounds)) {
    const number = value[field]
    if (typeof number !== 'number' || !Number.isFinite(number) || number < minimum || number > maximum) {
      throw new Error(`${label}.${field} is invalid.`)
    }
  }
}

function validateAnchorRecord(value: unknown): void {
  if (!isRecord(value)) throw new Error('Character Kit anchors must be an object.')
  if (Object.keys(value).length > MAX_POSES) throw new Error('Character Kit anchors have too many poses.')
  for (const [poseId, group] of Object.entries(value)) {
    if (!isIdentifier(poseId)) throw new Error('Character Kit anchor pose id is invalid.')
    if (!isRecord(group) || !Object.hasOwn(group, 'mouth')) throw new Error(`Anchors for ${poseId} need a mouth anchor.`)
    validateAnchor(group.mouth, `${poseId}.mouth`)
    if (group.mouthStates !== undefined) {
      if (!isRecord(group.mouthStates)) throw new Error(`${poseId}.mouthStates must be an object.`)
      for (const [state, anchor] of Object.entries(group.mouthStates)) {
        if (!MOUTH_STATES.has(state)) throw new Error(`${poseId}.mouthStates contains an unknown state.`)
        validateAnchor(anchor, `${poseId}.mouthStates.${state}`)
      }
    }
    if (group.eyes !== undefined) validateAnchor(group.eyes, `${poseId}.eyes`)
  }
}

function validateKit(value: unknown): asserts value is CharacterKit {
  if (!isRecord(value)) throw new Error('Character Kit must be an object.')
  if (value.version !== 1) throw new Error('Character Kit version is unsupported.')
  if (!isIdentifier(value.id)) throw new Error('Character Kit id is invalid.')
  if (!isBoundedString(value.name, MAX_ASSET_NAME_LENGTH, true)) throw new Error('Character Kit name is invalid.')
  if (typeof value.style !== 'string' || !STYLES.has(value.style as CharacterKit['style'])) throw new Error('Character Kit style is invalid.')
  if (Object.hasOwn(value, 'base') && value.base !== undefined) validateAsset(value.base, 'Character Kit base')
  if (Object.hasOwn(value, 'identityReference') && value.identityReference !== undefined) {
    validateAsset(value.identityReference, 'Character Kit identity reference')
  }
  if (!isRecord(value.poses) || Object.keys(value.poses).length > MAX_POSES) throw new Error('Character Kit poses are invalid.')
  for (const [poseId, asset] of Object.entries(value.poses)) {
    if (!isIdentifier(poseId)) throw new Error('Character Kit pose id is invalid.')
    validateAsset(asset, `Character Kit pose ${poseId}`)
  }
  validateAssetRecord(value.mouth, 'Character Kit mouth', MOUTH_STATES)
  validateAssetRecord(value.eyes, 'Character Kit eyes', EYE_STATES)
  validateAnchorRecord(value.anchors)
  if (!Array.isArray(value.provenance) || value.provenance.length > MAX_PROVENANCE_ENTRIES
    || value.provenance.some(item => !isRecord(item))) {
    throw new Error('Character Kit provenance is invalid.')
  }
  validateOptionalString(value.lookNotes, MAX_PROMPT_LENGTH, 'Character Kit look notes')
  validateOptionalString(value.createdAt, MAX_ASSET_NAME_LENGTH, 'Character Kit createdAt')
  validateOptionalString(value.updatedAt, MAX_ASSET_NAME_LENGTH, 'Character Kit updatedAt')
}

function serializedByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

function storageKey(workspace: string, kitId?: string): string {
  if (typeof workspace !== 'string') throw new Error('Speech draft workspace must be a string.')
  return `${STORAGE_PREFIX}:${encodeURIComponent(workspace)}${kitId ? `:kit:${encodeURIComponent(kitId)}` : ''}`
}

/** The session key is namespaced and intentionally includes the encoded workspace. */
export function speechDraftStorageKey(workspace: string, kitId?: string): string {
  return storageKey(workspace, kitId)
}

function parsePersistedDraft(raw: string, workspace: string): CharacterSpeechDraft {
  if (serializedByteLength(raw) > MAX_SERIALIZED_BYTES) throw new Error('Speech draft exceeds the 2 MiB recovery limit.')
  const value: unknown = JSON.parse(raw)
  if (!isRecord(value) || value.version !== PAYLOAD_VERSION || value.workspace !== workspace || !isSafeRevision(value.baseRevision)) {
    throw new Error('Speech draft payload is invalid.')
  }
  validateKit(value.kit)
  return { baseRevision: value.baseRevision, kit: value.kit }
}

export function readSpeechDraft(workspace: string, kitId?: string): CharacterSpeechDraft | null {
  const key = storageKey(workspace, kitId)
  const raw = safeStorageGet('session', key)
  if (raw === null) return null
  try {
    const draft = parsePersistedDraft(raw, workspace)
    if (kitId && draft.kit.id !== kitId) throw new Error('Speech draft belongs to another character.')
    return draft
  } catch {
    safeStorageRemove('session', key)
    return null
  }
}

export function writeSpeechDraft(workspace: string, draft: CharacterSpeechDraft, kitId?: string): void {
  const key = storageKey(workspace, kitId)
  try {
    if (!isRecord(draft) || !isSafeRevision(draft.baseRevision)) throw new Error('Speech draft revision is invalid.')
    validateKit(draft.kit)
    if (kitId && draft.kit.id !== kitId) throw new Error('Speech draft belongs to another character.')
    const payload: PersistedCharacterSpeechDraft = {
      version: PAYLOAD_VERSION,
      workspace,
      baseRevision: draft.baseRevision,
      kit: draft.kit,
    }
    const raw = JSON.stringify(payload)
    if (serializedByteLength(raw) > MAX_SERIALIZED_BYTES) throw new Error('Speech draft is too large to save (maximum 2 MiB).')
    // Remove a previous browser value before safeStorageSet. If storage quota
    // rejects the replacement, safeStorage's memory fallback must win over a
    // stale value that would otherwise still be returned by getItem.
    safeStorageRemove('session', key)
    safeStorageSet('session', key, raw)
  } catch (cause) {
    safeStorageRemove('session', key)
    if (cause instanceof Error) throw cause
    throw new Error('Speech draft could not be serialized.')
  }
}

export function clearSpeechDraft(workspace: string, kitId?: string): void {
  safeStorageRemove('session', storageKey(workspace, kitId))
}
