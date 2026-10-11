import { BASE } from '../../api/http'
import type { Scene3DSlot } from './types'

export type LibraryProp = { id: string; name: string; description: string; heightM: number; file: string; style: string; approved: boolean }
export const PROP_DRAG_TYPE = 'application/x-hocus-prop'
export function filterProps(props: LibraryProp[], text: string, style: string) {
  return props.filter(prop => (!style || prop.style === style) && `${prop.name} ${prop.description}`.toLowerCase().includes(text.toLowerCase()))
}
export function propSlot(prop: LibraryProp, workspace: string, id = prop.id): Scene3DSlot {
  return { id, slot: 'prop', media: 'image', sourceUrl: `${BASE}/api/v1/file/${encodeURIComponent(prop.file)}?workspace=${encodeURIComponent(workspace)}`,
    surface: 'cutout', grounded: true, position: [0, 0, 0], rotationY: 0, scale: prop.heightM / 2, clip: null }
}
export async function propsCommand(operation: string, input: Record<string, unknown>, intent?: string) {
  const response = await fetch(`${BASE}/api/v1/props/commands`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation, version: 1, input, ...(intent ? { intent_id: intent } : {}) }) })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  return body.result
}

