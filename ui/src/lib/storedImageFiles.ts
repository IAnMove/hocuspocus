import { getFileUrl, getStoredAssetUrl, getUploadUrl } from '../api/outputs'

const storedFiles = new WeakMap<File, string>()
export const storedImageFileUrl = (file: File) => storedFiles.get(file)
export function rememberStoredImageFile(file: File, url: string): File {
  storedFiles.set(file, url)
  return file
}

/** Saved paths may predate canonical URLs; retain explicit workspace/upload identity. */
export async function restoreImageFile(path: string, workspace: string, signal?: AbortSignal) {
  const primary = getStoredAssetUrl(path, workspace)
  const name = decodeURIComponent(primary.split('?')[0].split('/').pop() || 'image.png')
  const ambiguous = !path.startsWith('/api/') && !/(^|\/)uploads\//i.test(path.replace(/\\/g, '/'))
  const candidates = ambiguous ? [primary, getUploadUrl(name)] : [primary]
  for (const url of candidates) {
    const response = await fetch(url, { signal })
    if (!response.ok) {
      if (response.status === 404 && url !== candidates.at(-1)) continue
      throw new Error(`${name}: HTTP ${response.status}`)
    }
    const blob = await response.blob()
    if (blob.type && !blob.type.startsWith('image/') && blob.type !== 'application/octet-stream') throw new Error(`${name}: invalid image`)
    const file = rememberStoredImageFile(new File([blob], name, { type: blob.type || 'image/png' }), url)
    return { file, url }
  }
  throw new Error(`${name}: image unavailable`)
}

export function outputImageUrl(name: string, workspace: string): string {
  return workspace === '__uploads__' ? getUploadUrl(name) : getFileUrl(name, workspace)
}
