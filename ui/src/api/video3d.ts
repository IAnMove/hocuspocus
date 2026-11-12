import { BASE } from './http'
import type { ApiOutput } from './outputs'
import { documentSaveHeaders } from '../lib/documentSaveActor'

export async function saveScene(scene: import('../types').Scene, preview: string, workspace?: string): Promise<{ name: string; type: 'scene'; url: string; thumbnail_url: string }> {
  const res = await fetch(`${BASE}/api/v1/scenes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...documentSaveHeaders() },
    body: JSON.stringify({ scene, preview, workspace }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save scene' }))
    throw new Error(error.detail || 'Failed to save scene')
  }
  return res.json()
}

export async function saveSceneRecording(
  recording: Blob,
  details: {
    scene: import('../types').Scene
    embeddedAudio?: boolean
    prompt: string
    recipe: Record<string, unknown> | null
  workspace?: string
  },
  audio?: Blob,
): Promise<ApiOutput> {
  const form = new FormData()
  const extension = recording.type.includes('mp4') ? 'mp4' : 'webm'
  form.append('file', recording, `${details.scene.name || '3d-scene'}.${extension}`)
  form.append('metadata', JSON.stringify(details))
  if (audio) form.append('audio', audio, 'scene-mix.wav')
  const res = await fetch(`${BASE}/api/v1/scenes/recordings`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save MP4 recording' }))
    throw new Error(error.detail || 'Failed to save MP4 recording')
  }
  return res.json()
}
