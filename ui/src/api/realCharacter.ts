import { randomUuid } from '../lib/uuid'
import { detailMessage } from './blobBody'
import { BASE } from './http'

/** A realistic (PS2-era) 3D person made on the server: `model3d.real.*`, the same operations the MCP tools and the Wizard call. */
export type RealGender = 'man' | 'woman'
export type RealStepId = 'guides' | 'body' | 'head' | 'character' | 'kit'
export const REAL_STEPS: RealStepId[] = ['guides', 'body', 'head', 'character', 'kit']
export const REAL_ACTIVE = ['queued', 'running', 'cancelling']

export interface RealMakeInput {
  workspace: string
  name: string
  gender?: RealGender
  skin?: string
  height?: number
  body?: string
  bottom?: string
  outfitPrompt?: string
  facePrompt?: string
  seed?: number
  talkKit?: boolean
}

export interface RealNote { code: string; message: string; pose?: string; file?: string }

export interface RealRecipe {
  name: string
  slug: string
  input: { gender?: RealGender; skin?: string; height?: number; body?: string; bottom?: string; outfit_prompt?: string; face_prompt?: string; seed?: number; talk_kit?: boolean }
  kit_id: string | null
  madeAt?: string
  missing?: boolean
}

export interface RealJobResult {
  file: string
  rigged_file: string
  rigged_url: string
  kit_id: string | null
  preview: string | null
  warnings: RealNote[]
  talk_kit?: { review?: string; mouthFound?: Record<string, boolean | undefined> } | null
  recipe: RealRecipe
  reused: string[]
}

export interface RealJob {
  jobId: string
  name: string
  status: string
  stage?: string
  steps: Array<{ id: RealStepId; status: string; error?: string }>
  result?: RealJobResult
  error?: string
  errorCode?: string
}

export interface RealCharacterRow {
  name: string
  slug: string
  gender?: RealGender
  outfit_prompt?: string
  face_prompt?: string
  seed?: number
  kit_id: string | null
  rigged_file?: string
  face_url?: string | null
  body_url?: string | null
  madeAt?: string
  missing: boolean
}

export interface RealPreset { id: string; gender: 'any' | RealGender; label: { es: string; en: string }; prompt: string }
export interface RealPresets { outfits: RealPreset[]; faces: RealPreset[] }

/** The `model3d.real.make` input: only the fields given, so a remake keeps the stored recipe for the rest. */
export function realMakeInput(input: RealMakeInput): Record<string, unknown> {
  const fields: Array<[string, unknown]> = [
    ['gender', input.gender], ['skin', input.skin], ['height', input.height], ['body', input.body], ['bottom', input.bottom],
    ['outfit_prompt', input.outfitPrompt?.trim()], ['face_prompt', input.facePrompt?.trim()], ['seed', input.seed], ['talk_kit', input.talkKit],
  ]
  return { workspace: input.workspace, name: input.name, ...Object.fromEntries(fields.filter(([, value]) => value !== undefined && value !== '')) }
}

async function post<T>(path: string, body: Record<string, unknown>, fallback: string): Promise<T> {
  const res = await fetch(`${BASE}/api/v1/model3d/real${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const parsed = await res.json().catch(() => null)
  if (!res.ok) throw new Error(detailMessage(parsed, fallback))
  return (parsed as { result: T }).result
}

export function makeRealCharacter(input: RealMakeInput): Promise<RealJob> {
  return post('', { version: 1, intent_id: randomUuid(), input: realMakeInput(input) }, 'Could not start the realistic character')
}

export function realCharacterJob(workspace: string, jobId: string): Promise<RealJob> {
  return post('/status', { version: 1, input: { workspace, job_id: jobId } }, 'Could not read the job')
}

export function cancelRealCharacter(workspace: string, jobId: string): Promise<RealJob> {
  return post('/cancel', { version: 1, input: { workspace, job_id: jobId } }, 'Could not stop the job')
}

export function getRealCharacter(workspace: string, name: string): Promise<RealRecipe> {
  return post('/get', { version: 1, input: { workspace, name } }, 'Could not read the character')
}

export async function listRealCharacters(workspace: string): Promise<RealCharacterRow[]> {
  const result = await post<{ characters: RealCharacterRow[] }>('/list', { version: 1, input: { workspace } }, 'Could not list the characters')
  return result.characters
}

export function fetchRealPresets(): Promise<RealPresets> {
  return post('/presets', { version: 1 }, 'Could not read the prompt library')
}
