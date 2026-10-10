import { BASE } from './http'

/** A personal Video 3D template saved in the workspace (by an agent, the Wizard or world3d.templates.user.put). */
export interface World3DWorkspaceTemplate {
  id: string
  title: string
  description: string
  createdAt?: string | null
  updatedAt?: string | null
  createdBy?: 'agent' | 'wizard' | 'user' | null
  baseTemplateId?: string | null
  duration: number
  width: number
  height: number
  format: 'portrait' | 'landscape'
  slots: number
  pending: number
}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = await response.json().catch(() => ({})) as { detail?: { message?: string } | string }
  if (!response.ok) {
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || fallback)
  }
  return body as T
}

export async function listWorld3DWorkspaceTemplates(workspace: string, signal?: AbortSignal): Promise<World3DWorkspaceTemplate[]> {
  const query = new URLSearchParams({ workspace })
  const response = await fetch(`${BASE}/api/v1/world3d/templates/workspace?${query}`, { cache: 'no-store', signal })
  const body = await readJson<{ templates?: World3DWorkspaceTemplate[] }>(response, 'Could not list the workspace Video 3D templates')
  return Array.isArray(body.templates) ? body.templates : []
}

export async function getWorld3DWorkspaceTemplate(workspace: string, id: string): Promise<{ id: string; title: string; description?: string; createdAt?: string; document: unknown }> {
  const query = new URLSearchParams({ workspace })
  const response = await fetch(`${BASE}/api/v1/world3d/templates/workspace/${encodeURIComponent(id)}?${query}`, { cache: 'no-store' })
  const body = await readJson<{ template: { id: string; title: string; description?: string; createdAt?: string; document: unknown } }>(
    response, 'Could not open the workspace Video 3D template')
  return body.template
}

/** The current document of a Video 3D working scene (``w3d-…``) an agent instantiated and patched. */
export async function getWorld3DWorkingScene(workspace: string, sceneId: string): Promise<unknown> {
  const response = await fetch(`${BASE}/api/v1/world3d/templates/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation: 'world3d.scene.inspect', version: 1, input: { workspace, scene_id: sceneId } }),
  })
  const body = await readJson<{ result?: { scene?: { document?: unknown } } }>(response, 'Could not open the Video 3D scene')
  if (!body.result?.scene?.document) throw new Error('The Video 3D scene has no document')
  return body.result.scene.document
}

/** A working Video 3D scene (``w3d-…``) an agent instantiated or patched and did not publish at its current revision. */
export interface World3DWorkingScene {
  sceneId: string
  revision: number
  templateId: string
  title: string
  /** Seconds since the epoch of its last change. */
  updatedAt: number
  published?: { file: string; revision: number } | null
  duration?: number
  width?: number
  height?: number
  slots?: number
  pending?: number
}

export async function listWorld3DWorkingScenes(workspace: string, signal?: AbortSignal): Promise<World3DWorkingScene[]> {
  const query = new URLSearchParams({ workspace })
  const response = await fetch(`${BASE}/api/v1/world3d/templates/working-scenes?${query}`, { cache: 'no-store', signal })
  const body = await readJson<{ scenes?: World3DWorkingScene[] }>(response, 'Could not list the working Video 3D scenes')
  return Array.isArray(body.scenes) ? body.scenes : []
}
