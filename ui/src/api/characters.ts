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
  const { prepareCharacterRestPose } = await import('../lib/characterRestPose')
  const { uploadImage, getFileUrl } = await import('./client')
  kit = await prepareCharacterRestPose(kit, workspace, uploadImage, (filename, sourceWorkspace) => getFileUrl(filename, sourceWorkspace))
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

async function failure(response: Response, fallback: string): Promise<Error> {
  const error = await response.json().catch(() => ({ detail: fallback }))
  const detail = error.detail
  return new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : fallback)
}

async function postJson<T>(path: string, body: unknown, fallback: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) throw await failure(response, fallback)
  return response.json()
}

/** Key a workspace image on a plain screen (studio.key). The same intentId returns the same file. */
export async function keyStudioImage(details: { workspace: string; source: string; mode: 'green' | 'blue' | 'magenta'; intentId?: string }) {
  const reply = await postJson<{ result: { file: string; url: string; sha256: string } }>('/api/v1/studio/key', {
    workspace: details.workspace, source: details.source, mode: details.mode,
    ...(details.intentId ? { intent_id: details.intentId } : {}),
  }, 'Could not remove the background')
  return reply.result
}

export type FlatRigResult = {
  revision: number
  character: import('../lib/characterKit').CharacterKit
  review: string
  unwipedPoses: string[]
}

/** Wipe painted mouths, draw nine paper mouths and a blink, and save anchors (characters.rig.flat). */
export async function rigFlatCharacter(details: { workspace: string; kitId: string; baseRevision: number
  style?: Record<string, number | boolean>; poses?: string[] }): Promise<FlatRigResult> {
  return postJson(`/api/v1/character-kits/library/kits/${encodeURIComponent(details.kitId)}/flat-rig`, {
    workspace: details.workspace, baseRevision: details.baseRevision,
    ...(details.style ? { style: details.style } : {}), ...(details.poses ? { poses: details.poses } : {}),
  }, 'Could not rig the character')
}

export type SpeechCheck = {
  transcript: string
  wer: number
  medianPitchHz: number | null
  wordsPerSecond: number
  duration: number
  warnings: string[]
}

/** Transcript, word error rate, pitch and pace of a workspace take (qa.speech). */
export async function checkSpeech(details: { workspace: string; file: string; text: string; language: string
  pitchRange?: [number, number] }): Promise<SpeechCheck> {
  const reply = await postJson<{ result: SpeechCheck }>('/api/v1/qa/speech', {
    workspace: details.workspace, file: details.file, text: details.text, language: details.language,
    ...(details.pitchRange ? { pitch_range: details.pitchRange } : {}),
  }, 'Could not check the voice')
  return reply.result
}
