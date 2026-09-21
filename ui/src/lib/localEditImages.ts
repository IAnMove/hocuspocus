import { uploadImage } from '../api/generation'

const files = new Map<string, File>()
const previews = new Map<string, string>()
let nextId = 0

export function rememberLocalImage(file: File): string {
  const id = `local-edit:${++nextId}`
  files.set(id, file)
  previews.set(id, URL.createObjectURL(file))
  return id
}

export function localEditPreview(value: string | undefined): string {
  if (!value) return ''
  return previews.get(value) || value
}

export function forgetLocalImage(value: string | undefined): void {
  if (!value) return
  const preview = previews.get(value)
  if (preview) URL.revokeObjectURL(preview)
  files.delete(value)
  previews.delete(value)
  if (value.startsWith('blob:')) {
    files.delete(value)
    URL.revokeObjectURL(value)
  }
}

export function studioMediaUrl(value: string): string {
  const trimmed = value.trim()
  if (trimmed.startsWith('/api/v1/')) return trimmed
  try {
    if (/^https?:\/\//i.test(trimmed)) {
      const parsed = new URL(trimmed)
      return `${parsed.pathname}${parsed.search}`
    }
  } catch {
    return trimmed
  }
  return trimmed
}

export async function materializeLocalEditImage(value: unknown): Promise<unknown> {
  if (typeof value !== 'string' || !value) return value
  const token = value.trim()
  const file = files.get(token)
  if (token.startsWith('local-edit:') || token.startsWith('blob:')) {
    if (!file) throw new Error('The local edit image is no longer in this tab. Choose it again.')
    const uploaded = await uploadImage(file)
    const name = uploaded.filename || token.slice(token.lastIndexOf('/') + 1)
    return uploaded.url && uploaded.url.startsWith('/api/v1/')
      ? uploaded.url
      : `/api/v1/uploads/${name}`
  }
  return studioMediaUrl(token)
}
