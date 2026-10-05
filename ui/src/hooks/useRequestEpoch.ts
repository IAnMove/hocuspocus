import { useCallback, useEffect, useRef } from 'react'

/**
 * Serialise overlapping async loads: `begin()` marks a new request and returns
 * `stale()`, true once a newer request began or the component unmounted.
 * Check it after every `await` before touching state.
 */
export function useRequestEpoch(): () => () => boolean {
  const epochRef = useRef(0)
  useEffect(() => () => { epochRef.current += 1 }, [])
  return useCallback(() => {
    const epoch = ++epochRef.current
    return () => epochRef.current !== epoch
  }, [])
}
