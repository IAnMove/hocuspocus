import { useCallback, useSyncExternalStore } from 'react'

export function useIsMobile(breakpoint = 768): boolean {
  const query = `(max-width: ${breakpoint - 1}px)`
  const subscribe = useCallback((notify: () => void) => {
    if (typeof window === 'undefined') return () => {}
    const media = window.matchMedia(query)
    media.addEventListener('change', notify)
    return () => media.removeEventListener('change', notify)
  }, [query])
  const getSnapshot = useCallback(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
    [query],
  )

  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
