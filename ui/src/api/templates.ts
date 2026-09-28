import { BASE } from './http'

export type TemplateEditor = 'video3d' | 'video2d'
export const TEMPLATE_LICENSES = ['CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'CC-BY-NC-4.0', 'MIT', 'all-rights-reserved'] as const
export type TemplateLicense = typeof TEMPLATE_LICENSES[number]

export interface TemplateSlot { id: string; label: string; hint: string; accepts: string[]; required: boolean; target: string }
export interface TemplateControl { id: string; label: string; type: 'number' | 'text' | 'color' | 'boolean' | 'choice'; pointer: string; min?: number; max?: number; options?: unknown[]; default: unknown }
export interface TemplateAuthor { name?: string; x?: string; url?: string }

export interface TemplateSummary {
  id: string
  editor: TemplateEditor
  title: string
  description: string
  tags: string[]
  author: TemplateAuthor
  license: TemplateLicense
  templateVersion: string
  createdAt: string
  updatedAt: string
  slots: TemplateSlot[]
  controls: TemplateControl[]
  media: number
  source: 'user' | 'imported' | 'community'
  previewUrl: string | null
}

export interface TemplatePreflight {
  canImport: boolean
  exists?: boolean
  error?: { code: string; message: string }
  issues?: Array<{ code: string; message: string }>
  template?: Pick<TemplateSummary, 'id' | 'editor' | 'title' | 'description' | 'tags' | 'author' | 'license' | 'templateVersion' | 'slots' | 'controls'>
  media?: Array<{ path: string; type: string; bytes: number }>
}

export interface SaveTemplateInput {
  workspace: string
  editor: TemplateEditor
  document: unknown
  title: string
  description?: string
  tags?: string[]
  author?: TemplateAuthor
  license?: TemplateLicense
  slots?: Array<Partial<TemplateSlot> & { id: string }>
  controls?: Array<Omit<TemplateControl, 'label' | 'default'> & { label?: string; default?: unknown }>
  include_media?: boolean
  preview?: string
  expected_updated_at?: string
}

async function readJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: fallback }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || fallback)
  }
  return res.json() as Promise<T>
}

const path = (id: string) => `${BASE}/api/v1/templates/${id.split('/').map(encodeURIComponent).join('/')}`

export async function listTemplates(editor?: TemplateEditor): Promise<TemplateSummary[]> {
  const res = await fetch(`${BASE}/api/v1/templates${editor ? `?editor=${editor}` : ''}`)
  return (await readJson<{ templates: TemplateSummary[] }>(res, 'Could not list templates')).templates
}

export async function saveTemplate(input: SaveTemplateInput): Promise<TemplateSummary> {
  const res = await fetch(`${BASE}/api/v1/templates`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
  return readJson(res, 'Could not save the template')
}

export async function applyTemplate<T = unknown>(id: string, workspace: string, slots?: Record<string, string>, controls?: Record<string, unknown>): Promise<{ document: T; missingSlots: string[]; copiedMedia: string[] }> {
  const res = await fetch(`${path(id)}/apply`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace, slots, controls }),
  })
  return readJson(res, 'Could not use the template')
}

export async function deleteTemplate(id: string): Promise<void> {
  await readJson(await fetch(path(id), { method: 'DELETE' }), 'Could not delete the template')
}

export async function preflightTemplate(file: Blob): Promise<TemplatePreflight> {
  const res = await fetch(`${BASE}/api/v1/templates/preflight`, { method: 'POST', body: file })
  return readJson(res, 'Could not read the template file')
}

export async function importTemplate(file: Blob, replace = false): Promise<TemplateSummary> {
  const res = await fetch(`${BASE}/api/v1/templates/import${replace ? '?replace=true' : ''}`, { method: 'POST', body: file })
  return readJson(res, 'Could not import the template')
}

export function templatePackageUrl(id: string): string {
  return `${path(id)}/package`
}

export function templatePreviewUrl(summary: Pick<TemplateSummary, 'previewUrl'>): string | null {
  return summary.previewUrl ? `${BASE}${summary.previewUrl}` : null
}
