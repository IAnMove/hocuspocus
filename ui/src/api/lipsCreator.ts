import { BASE } from './http'
import type { CharacterKit, CharacterKitLibrary } from '../lib/characterKit'

const libraries = new Map<string, CharacterKitLibrary>()
export const lipsLibrarySnapshot = (workspace: string) => libraries.get(workspace)
export const LIPS_LIBRARY_UPDATED = 'hocus:lips-library-updated'
function remember(workspace: string, library: CharacterKitLibrary, changed = false) {
  libraries.set(workspace, library)
  if (changed && typeof window !== 'undefined') window.dispatchEvent(new window.CustomEvent(LIPS_LIBRARY_UPDATED, { detail: { workspace } }))
  return library
}

async function request(path: string, init?: RequestInit): Promise<CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/lips-creator/${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Could not load or save the mouth collection.')
  }
  return response.json()
}

export const fetchLipsLibrary = (workspace: string, signal?: AbortSignal) => request(`library?workspace=${encodeURIComponent(workspace)}`, { signal }).then(library => remember(workspace, library))
export const saveLipsPack = (workspace: string, library: CharacterKitLibrary, kit: CharacterKit) => request(`packs/${encodeURIComponent(kit.id)}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace, baseRevision: library.revision, kit }),
}).then(library => remember(workspace, library, true))
export const deleteLipsPack = (workspace: string, library: CharacterKitLibrary, id: string) => request(`packs/${encodeURIComponent(id)}`, {
  method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace, baseRevision: library.revision }),
}).then(library => remember(workspace, library, true))

export interface LipsCommandResult { pack_id?: string; character_id?: string; library?: CharacterKitLibrary; requests?: unknown[] }
export async function runLipsCommand(workspace: string, operation: string, input: Record<string, unknown>, intentId?: string): Promise<LipsCommandResult> {
  const response = await fetch(`${BASE}/api/v1/character-kits/lips-creator/commands`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, operation, input: { ...input, workspace }, ...(intentId ? { intent_id: intentId } : {}) }),
  })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Lips Creator command failed.')
  const result = body.result as LipsCommandResult
  if (result.library && operation !== 'lips.apply') remember(workspace, result.library, operation !== 'lips.list')
  return result
}
