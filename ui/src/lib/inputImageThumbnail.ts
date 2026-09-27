import { getOutputThumbnailUrl, type ApiOutput } from '../api/outputs'
import { localEditPreview } from './localEditImages'

export function inputThumbnailSource(item: ApiOutput): string {
  const source = localEditPreview(item.url)
  if (/^(blob:|data:|local-edit:)/.test(source)) return source
  const parsed = new URL(source, 'http://localhost')
  if (parsed.pathname.includes('/api/v1/uploads/')) {
    const name = decodeURIComponent(parsed.pathname.split('/api/v1/uploads/')[1])
    return `${getOutputThumbnailUrl(name, '__uploads__')}&size=sm`
  }
  if (parsed.pathname.includes('/api/v1/file/')) {
    const name = decodeURIComponent(parsed.pathname.split('/api/v1/file/')[1])
    const workspace = parsed.searchParams.get('workspace') || item.workspace_id
    const url = getOutputThumbnailUrl(name, workspace)
    return `${url}${url.includes('?') ? '&' : '?'}size=sm`
  }
  return item.thumbnail_url || source
}
