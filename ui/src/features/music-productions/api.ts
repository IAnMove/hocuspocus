import type { MusicProductionCard, MusicProductionDetail, ReviewPlan } from './types'

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

function shotUrl(workspace: string, productionId: string, shot: string, action: string): string {
  return `/api/v1/music-productions/${encodeURIComponent(productionId)}/shots/${encodeURIComponent(shot)}/${action}?workspace=${encodeURIComponent(workspace)}`
}

export async function reviewMusicProductionShot(workspace: string, productionId: string, shot: string, status: string, note?: string): Promise<unknown> {
  return read(await fetch(shotUrl(workspace, productionId, shot, 'review'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, note }),
  }))
}

export async function lockMusicProductionShot(workspace: string, productionId: string, shot: string, locked: boolean): Promise<unknown> {
  return read(await fetch(shotUrl(workspace, productionId, shot, 'lock'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ locked }),
  }))
}

export async function requestMusicProductionShot(workspace: string, productionId: string, shot: string, instruction: string, apply: boolean): Promise<ReviewPlan> {
  return await read(await fetch(shotUrl(workspace, productionId, shot, 'request'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instruction, apply }),
  })) as ReviewPlan
}

export async function undoMusicProductionShot(workspace: string, productionId: string, shot: string, historyId: string): Promise<unknown> {
  return read(await fetch(shotUrl(workspace, productionId, shot, 'undo'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ history_id: historyId }),
  }))
}
