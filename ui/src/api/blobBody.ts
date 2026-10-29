import { randomUuid } from '../lib/uuid'
import { BASE } from './http'

export interface BlobPresetCatalog {
  presets: Record<string, { height?: number; build?: string; hands?: string; feet?: string; head?: { width?: number } }>
  height: { min: number; max: number; default: number }
  build: string[]
  hands: string[]
  feet: string[]
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
  height: number
  build: string
  headWidth: number
  hands: string
  feet: string
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
          height: input.height,
          build: input.build,
          hands: input.hands,
          feet: input.feet,
          head: { width: input.headWidth },
        },
      },
    }),
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(detailMessage(body, 'Could not build the blob'))
  return (body as { result: BlobMakeResult }).result
}
