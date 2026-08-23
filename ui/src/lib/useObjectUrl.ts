import { useEffect, useMemo } from 'react'

/**
 * Create exactly one object URL for the current Blob/File and revoke it when
 * the source changes or its consumer unmounts. A persisted URL can be supplied
 * as a fallback without taking ownership of it.
 */
export function useObjectUrl(source: Blob | null, fallback: string | null = null): string | null {
  const objectUrl = useMemo(
    () => source ? URL.createObjectURL(source) : null,
    [source],
  )

  useEffect(() => {
    if (!objectUrl) return
    return () => URL.revokeObjectURL(objectUrl)
  }, [objectUrl])

  return objectUrl || fallback
}
