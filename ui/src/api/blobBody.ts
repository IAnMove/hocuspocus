import { randomUuid } from '../lib/uuid'
import { BASE } from './http'

export interface BlobPresetCatalog {
  presets: Record<string, {
    height?: number
    build?: string
    hands?: string
    feet?: string
    family?: string
    hair?: { style?: string }
    head?: { width?: number }
  }>
  height: { min: number; max: number; default: number }
  build: string[]
  family: string[]
  hands: string[]
  feet: string[]
  hair: { style: string[] }
  head: { limits: { width: [number, number] }; default: { width: number } }
}

export interface BlobMakeResult {
  file: string
  url: string
  rigged_file: string
  rigged_url: string
  name: string
  workspace: string
}

export interface BlobMakeInput {
  workspace: string
  name: string
  preset?: string
  height?: number
  build?: string
  headWidth?: number
  hands?: string
  feet?: string
  family?: string
  hairStyle?: string
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail?: unknown }).detail : null
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  return fallback
}

export async function fetchBlobPresets(): Promise<BlobPresetCatalog> {
  const res = await fetch(`${BASE}/api/v1/model3d/blob/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1 }),
  })
  if (!res.ok) throw new Error(detailMessage(await res.json().catch(() => null), 'Could not read blob presets'))
  const body = await res.json()
  return body.result as BlobPresetCatalog
}

export async function makeBlob(input: BlobMakeInput): Promise<BlobMakeResult> {
  const res = await fetch(`${BASE}/api/v1/model3d/blob`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version: 1,
      intent_id: randomUuid(),
      input: {
        workspace: input.workspace,
        name: input.name,
        ...(input.preset ? { preset: input.preset } : {}),
        traits: {
          ...(input.height != null ? { height: input.height } : {}),
          ...(input.build ? { build: input.build } : {}),
          ...(input.hands ? { hands: input.hands } : {}),
          ...(input.feet ? { feet: input.feet } : {}),
          ...(input.headWidth != null ? { head: { width: input.headWidth } } : {}),
          ...(input.family ? { family: input.family } : {}),
          ...(input.hairStyle ? { hair: { style: input.hairStyle } } : {}),
        },
      },
    }),
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(detailMessage(body, 'Could not build the blob'))
  return (body as { result: BlobMakeResult }).result
}

export interface AnimeMakeInput {
  workspace: string
  name: string
  gender?: string
  body?: string
  height?: number
  skin?: string
  eyeColor?: string
  hairStyle?: string
  hairColor?: string
  outfit?: string
  outfitColors?: { top?: string; bottom?: string; shoes?: string; accent?: string }
}

export interface AnimeMakeResult extends BlobMakeResult {
  kit_id: string
  poses: string[]
  preview: string
  face?: { fit: number[]; taper: number }
  faceAnchor?: { center: number[]; radii: number[] }
}

/** One anime 3D character from traits: `model3d.anime.make` (a lofted body rigged on CPU plus its anime_head face kit). */
export async function makeAnime(input: AnimeMakeInput): Promise<AnimeMakeResult> {
  const colors = Object.fromEntries(Object.entries(input.outfitColors ?? {}).filter(([, value]) => typeof value === 'string' && value))
  const res = await fetch(`${BASE}/api/v1/model3d/anime`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version: 1,
      intent_id: randomUuid(),
      input: {
        workspace: input.workspace,
        name: input.name,
        traits: {
          ...(input.gender ? { gender: input.gender } : {}),
          ...(input.body ? { body: input.body } : {}),
          ...(input.height != null ? { height: input.height } : {}),
          ...(input.skin ? { skin: input.skin } : {}),
          ...(input.eyeColor ? { eye_color: input.eyeColor } : {}),
          ...(input.hairStyle ? { hair_style: input.hairStyle } : {}),
          ...(input.hairColor ? { hair_color: input.hairColor } : {}),
          ...(input.outfit ? { outfit: input.outfit } : {}),
          ...(Object.keys(colors).length ? { outfit_colors: colors } : {}),
        },
      },
    }),
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(detailMessage(body, 'Could not build the anime character'))
  return (body as { result: AnimeMakeResult }).result
}
