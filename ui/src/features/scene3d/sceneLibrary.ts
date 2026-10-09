import { BASE } from '../../api/http'
import { getFileUrl, type ApiOutput } from '../../api/outputs'
import { documentSaveHeaders } from '../../lib/documentSaveActor'
import { parseScene3DDocument } from './document'
import type { Scene3DDocument } from './types'

export const isWorld3DOutput = (file: { name: string }) => file.name.endsWith('.world3d.scene.json')

export async function loadWorld3DOutput(file: ApiOutput, workspace: string, signal?: AbortSignal) {
  const response = await fetch(getFileUrl(file.name, workspace), { signal })
  if (!response.ok) throw new Error('Could not load scene')
  const text = await response.text()
  if (text.length > 8 * 1024 * 1024) throw new Error('Scene exceeds 8 MB')
  const document = parseScene3DDocument(JSON.parse(text))
  if (!document) throw new Error('Invalid Video3D scene')
  return document
}

export async function saveWorld3DOutput(document: Scene3DDocument, preview: string, name: string, workspace: string) {
  const response = await fetch(`${BASE}/api/v1/scenes/world3d`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...documentSaveHeaders() },
    body: JSON.stringify({ document, preview, name, workspace }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save scene')
  return result as ApiOutput
}
