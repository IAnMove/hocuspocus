import type { MusicProductionCard, MusicProductionDetail } from './types'

async function read(response: Response): Promise<unknown> {
  const body: unknown = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail?: { message?: string } }).detail : undefined
    throw new Error(detail?.message || `music production request failed (${response.status})`)
  }
  return body
}

export async function listMusicProductions(workspace: string): Promise<{ productions: MusicProductionCard[] }> {
  const body = await read(await fetch(`/api/v1/music-productions?workspace=${encodeURIComponent(workspace)}`))
  const productions = body && typeof body === 'object' && 'productions' in body ? (body as { productions?: MusicProductionCard[] }).productions : []
  return { productions: productions || [] }
}

export async function getMusicProduction(workspace: string, productionId: string): Promise<MusicProductionDetail> {
  return await read(await fetch(`/api/v1/music-productions/${encodeURIComponent(productionId)}?workspace=${encodeURIComponent(workspace)}`)) as MusicProductionDetail
}

export async function applyMusicProductionTake(workspace: string, productionId: string, shot: string, takeFile: string): Promise<unknown> {
  return read(await fetch(
    `/api/v1/music-productions/${encodeURIComponent(productionId)}/shots/${encodeURIComponent(shot)}/use-take?workspace=${encodeURIComponent(workspace)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ take_file: takeFile }) },
  ))
}

export async function retakeMusicProductionShot(workspace: string, productionId: string, shot: string): Promise<unknown> {
  return read(await fetch(
    `/api/v1/music-productions/${encodeURIComponent(productionId)}/shots/${encodeURIComponent(shot)}/retake?workspace=${encodeURIComponent(workspace)}`,
    { method: 'POST' },
  ))
}
