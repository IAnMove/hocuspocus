// Pure helpers shared by the Video 3D and Video 2D template libraries.
import type { SaveTemplateInput, TemplateAuthor, TemplateEditor, TemplateLicense } from '../../api/templates'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'

const AUTHOR_KEY = 'hocuspocus-template-author'

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

export function saveInput(editor: TemplateEditor, document: { duration?: unknown }, form: TemplateForm, workspace: string, preview?: string): SaveTemplateInput {
  const author: TemplateAuthor = {
    ...(form.authorName.trim() ? { name: form.authorName.trim() } : {}),
    ...(form.authorX.trim() ? { x: form.authorX.trim().replace(/^@/, '') } : {}),
  }
  return {
    workspace, editor, document, title: form.title.trim(), description: form.description.trim(),
    tags: parseTags(form.tags), author, license: form.license, include_media: form.includeMedia,
    ...(preview?.startsWith('data:image/') ? { preview } : {}),
    ...(form.durationControl && typeof document.duration === 'number'
      ? { controls: [{ id: 'duration', label: 'Duration (s)', type: 'number' as const, pointer: '/duration', min: 1, max: 600 }] } : {}),
  }
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

export const COMMUNITY_REPO = 'https://github.com/IAnMove/hocuspocus-community'

/** Pre-filled "Submit a template" issue form of the community repository. */
export function communitySubmitUrl(summary: { title: string; description?: string; tags?: string[]; license?: string }): string {
  const params = new URLSearchParams({
    template: 'submit-template.yml', title: `[Template] ${summary.title}`, template_title: summary.title,
    description: summary.description ?? '', tags: (summary.tags ?? []).join(', '), license: summary.license ?? '',
  })
  return `${COMMUNITY_REPO}/issues/new?${params.toString()}`
}
