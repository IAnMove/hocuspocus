import { useEffect, useMemo } from 'react'
import { getFileUrl } from '../api/client'
import type { DirectorClipImage } from '../types'

/**
 * Resolve a Director image from the local upload when available, otherwise
 * use the persisted backend filename. Only local File previews create blob
 * URLs, so only those URLs need revocation.
 */
export function useDirectorClipImageUrl(image: DirectorClipImage | null): string | null {
  const file = image?.file ?? null
  const filename = image?.filename ?? ''
  const url = useMemo(() => {
    if (file) return URL.createObjectURL(file)
    return filename ? getFileUrl(filename) : null
  }, [file, filename])

  useEffect(() => {
    if (!file || !url) return
    return () => URL.revokeObjectURL(url)
  }, [file, url])

  return url
}
