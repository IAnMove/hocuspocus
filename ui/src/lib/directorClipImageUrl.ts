import { getFileUrl } from '../api/client'
import type { DirectorClipImage } from '../types'
import { useObjectUrl } from './useObjectUrl'

/**
 * Resolve a Director image from the local upload when available, otherwise
 * use the persisted backend filename. Only local File previews create blob
 * URLs, so only those URLs need revocation.
 */
export function useDirectorClipImageUrl(image: DirectorClipImage | null): string | null {
  const file = image?.file ?? null
  const filename = image?.filename ?? ''
  return useObjectUrl(file, filename ? getFileUrl(filename) : null)
}
