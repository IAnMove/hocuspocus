import { BASE } from './http'

export async function fetchCharacterKitLibrary(workspace: string): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library?workspace=${encodeURIComponent(workspace)}`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Character Kits' }))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Could not load Character Kits')
  }
  return response.json()
}

export async function saveCharacterKit(
  workspace: string,
  library: import('../lib/characterKit').CharacterKitLibrary,
  kit: import('../lib/characterKit').CharacterKit,
): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library/kits/${encodeURIComponent(kit.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision, kit, makeActive: true }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not save Character Kit' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : 'Could not save Character Kit')
  }
  return response.json()
}

export async function deleteCharacterKit(
  workspace: string,
  library: import('../lib/characterKit').CharacterKitLibrary,
  kitId: string,
): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library/kits/${encodeURIComponent(kitId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not delete Character Kit' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : 'Could not delete Character Kit')
  }
  return response.json()
}

export async function cleanCharacterKitFaceOverlay(details: {
  workspace: string
  source: string
  padding?: number
}): Promise<import('../lib/characterKitFaceRig').FaceRigCleanupResult> {
  const response = await fetch(`${BASE}/api/v1/character-kits/face-rig/cleanup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace: details.workspace,
      source: details.source,
      padding: details.padding ?? 8,
    }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not clean Face Rig overlay' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : 'Could not clean Face Rig overlay')
  }
  return response.json()
}

export async function describeCharacterRefs(params: {
  kind: 'character' | 'object'
  image_paths: string[]
  roles?: string[]
  workspace?: string
}): Promise<{ a_prompt: string; kind: string }> {
  const res = await fetch(`${BASE}/api/v1/characters/describe-refs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Could not describe the reference images' }))
    throw new Error(err.detail || 'Could not describe the reference images')
  }
  return res.json()
}
