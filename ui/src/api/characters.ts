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

async function postJson<T>(path: string, body: unknown, fallback: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
  if (!response.ok) throw await failure(response, fallback)
  return response.json()
}

/** What studio.key read from the border and how much of the image it left semi-transparent (a haze when ``haze``). */
export type StudioKeyReport = { semiTransparentShare: number; transparentShare: number; haze: boolean; screenColor?: string | null; note?: string }

/** Key a workspace image on a plain screen (studio.key). The same intentId returns the same file. */
export async function keyStudioImage(details: { workspace: string; source: string; mode: 'green' | 'blue' | 'magenta'; intentId?: string }) {
  const reply = await postJson<{ result: { file: string; url: string; sha256: string; report?: StudioKeyReport } }>('/api/v1/studio/key', {
    workspace: details.workspace, source: details.source, mode: details.mode,
    ...(details.intentId ? { intent_id: details.intentId } : {}),
  }, 'Could not remove the background')
  return reply.result
}

/** A pose's hint for the flat rig: points in % of the pose image, `mouthWidth` corner to corner in % of its width. */
export type FlatRigHint = { mouth?: [number, number]; eyes?: [number, number]; mouthWidth?: number }
/** How a pose's face was read and warped: its head's size class and pixels, whether the face points were read on the
 * head alone (`pass: 'head'`) and how many times the face was enlarged to warp it (1: not at all). */
export type FlatRigFaceSize = { size: 'small' | 'normal'; head: number; pass?: 'head' | 'whole' | null; upscale: number }
/** The mouth line a warp rig or preview used, in % of the pose image. */
export type FlatRigMouthLine = { mouth: [number, number]; mouthWidth: number; found: boolean; from: 'hint' | 'landmarks' | 'painted' | 'guess'
  faceSize?: FlatRigFaceSize }

export type FlatRigResult = {
  revision: number
  character: import('../lib/characterKit').CharacterKit
  review: string
  unwipedPoses: string[]
  warnings?: Record<string, string[]>
  poses?: Record<string, { mouthLine?: FlatRigMouthLine; hints?: FlatRigHint; faceSize?: FlatRigFaceSize }>
  /** The look the rig used: the style sent over the kit's own (its last rig's, else its style preset's). */
  style?: Record<string, number | boolean | string>
}

/** Wipe painted mouths, draw nine paper mouths and a blink, and save anchors (characters.rig.flat). Style keys left
 * out keep the kit's look, so a warp kit stays warp. */
export async function rigFlatCharacter(details: { workspace: string; kitId: string; baseRevision: number
  style?: Record<string, number | boolean | string>; poses?: string[]; hints?: Record<string, FlatRigHint | null> }): Promise<FlatRigResult> {
  return postJson(`/api/v1/character-kits/library/kits/${encodeURIComponent(details.kitId)}/flat-rig`, {
    workspace: details.workspace, baseRevision: details.baseRevision,
    ...(details.style ? { style: details.style } : {}), ...(details.poses ? { poses: details.poses } : {}),
    ...(details.hints ? { hints: details.hints } : {}),
  }, 'Could not rig the character')
}

export type FlatRigMouthPreview = FlatRigMouthLine & {
  pose: string
  /** The line through the mouth, in % of the pose image. */
  line: Array<[number, number]>
  /** The face area each state image shows, [[x0, y0], [x1, y1]] in % of the pose image. */
  view: [[number, number], [number, number]]
  hint: FlatRigHint | null
  /** mouth_line_guessed: no painted line here; mouth_line_unsure: unsure face points placed the line. */
  warnings?: string[]
  states: Partial<Record<import('../lib/characterMouthStates').CharacterMouthState, string>>
}

/** Warp one pose's mouths at a mouth line without saving (characters.rig.flat.preview). */
export async function previewFlatRigMouth(details: { workspace: string; kitId: string; pose: string
  mouth?: [number, number]; mouthWidth?: number; signal?: AbortSignal }): Promise<FlatRigMouthPreview> {
  return postJson(`/api/v1/character-kits/library/kits/${encodeURIComponent(details.kitId)}/flat-rig/preview`, {
    workspace: details.workspace, pose: details.pose,
    ...(details.mouth ? { mouth: details.mouth } : {}), ...(details.mouthWidth ? { mouthWidth: details.mouthWidth } : {}),
  }, 'Could not preview the mouths', details.signal)
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
