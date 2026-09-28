// Pure helpers between the Video 3D editor and the server template library.
import type { SaveTemplateInput, TemplateAuthor, TemplateLicense, TemplateSummary } from '../../api/templates'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'
import type { Scene3DDocument } from './types.ts'
import { WORLD3D_TEMPLATE_KIND, type World3DUserTemplate } from './userTemplates.ts'

const AUTHOR_KEY = 'hocuspocus-template-author'
const titles = new Map<string, string>()

export interface TemplateForm {
  title: string
  description: string
  tags: string
  authorName: string
  authorX: string
  license: TemplateLicense
  includeMedia: boolean
  durationControl: boolean
}

export function parseTags(text: string): string[] {
  return [...new Set(text.split(/[,\n]/).map(tag => tag.trim().toLowerCase()).filter(Boolean))].slice(0, 12)
}

export function saveInput(document: Scene3DDocument, form: TemplateForm, workspace: string, preview?: string): SaveTemplateInput {
  const author: TemplateAuthor = {
    ...(form.authorName.trim() ? { name: form.authorName.trim() } : {}),
    ...(form.authorX.trim() ? { x: form.authorX.trim().replace(/^@/, '') } : {}),
  }
  return {
    workspace, editor: 'video3d', document, title: form.title.trim(), description: form.description.trim(),
    tags: parseTags(form.tags), author, license: form.license, include_media: form.includeMedia,
    ...(preview?.startsWith('data:image/') ? { preview } : {}),
    ...(form.durationControl && typeof document.duration === 'number'
      ? { controls: [{ id: 'duration', label: 'Duration (s)', type: 'number' as const, pointer: '/duration', min: 1, max: 120 }] } : {}),
  }
}

/** A library template, already applied into the workspace, as the editor's mountable pack. */
export function packFromApplied(summary: TemplateSummary, document: Scene3DDocument): World3DUserTemplate {
  titles.set(summary.id, summary.title)
  return {
    kind: WORLD3D_TEMPLATE_KIND, version: 1, id: summary.id, title: summary.title, description: summary.description,
    includeAssets: summary.media > 0, createdAt: summary.createdAt, document,
  }
}

export function userTemplateTitle(id: string | undefined): string | undefined {
  return id ? titles.get(id) : undefined
}

export function authorLabel(author: TemplateAuthor | undefined): string {
  if (!author) return ''
  return author.x ? `@${author.x}` : author.name ?? ''
}

export function readAuthor(): Pick<TemplateForm, 'authorName' | 'authorX' | 'license'> {
  try {
    const value = JSON.parse(safeStorageGet('local', AUTHOR_KEY) || '{}')
    return { authorName: String(value.authorName || ''), authorX: String(value.authorX || ''), license: value.license || 'CC-BY-4.0' }
  } catch {
    return { authorName: '', authorX: '', license: 'CC-BY-4.0' }
  }
}

export function rememberAuthor(form: Pick<TemplateForm, 'authorName' | 'authorX' | 'license'>): void {
  safeStorageSet('local', AUTHOR_KEY, JSON.stringify({ authorName: form.authorName, authorX: form.authorX, license: form.license }))
}
