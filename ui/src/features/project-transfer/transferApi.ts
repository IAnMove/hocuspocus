import { BASE } from '../../api/http'
import type { ReassignEntry } from './reassign.ts'
import type { PreflightReport } from './preflight.ts'

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch { /* ignore */ }
  return response.statusText || 'Request failed'
}

export async function fetchPackageFormat(): Promise<{ kind: string; template_kind: string; schema_version: number }> {
  const response = await fetch(`${BASE}/api/v1/scene-packages/format`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function exportScenePackage(input: {
  workspace: string
  documents: unknown[]
  title?: string
}): Promise<Blob> {
  const response = await fetch(`${BASE}/api/v1/scene-packages/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.blob()
}

export async function preflightScenePackage(file: File): Promise<PreflightReport> {
  const response = await fetch(`${BASE}/api/v1/scene-packages/preflight`, {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/zip' },
    body: file,
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<PreflightReport>
}

export async function importScenePackage(input: {
  workspace: string
  file: File
  reassign?: ReassignEntry[]
}): Promise<{ ok: boolean; scenes: Array<{ name: string }>; unknown_fields: string[] }> {
  const query = new URLSearchParams({
    workspace: input.workspace,
    reassign: JSON.stringify(input.reassign || []),
  })
  const response = await fetch(`${BASE}/api/v1/scene-packages/import?${query}`, {
    method: 'POST',
    headers: { 'Content-Type': input.file.type || 'application/zip' },
    body: input.file,
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
