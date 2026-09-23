import { useEffect, useRef, type RefObject } from 'react'

function spread(touches: TouchList) {
  return Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY)
}

/** Two-finger pinch on the phone grid changes its column count, like a
 *  photo library: fingers apart → fewer, larger tiles. The count follows the
 *  gesture continuously and is clamped to `[min, max]`. */
export function useGridPinch({ target, enabled, columns, min, max, onChange }: {
  target: RefObject<HTMLElement | null>
  enabled: boolean
  columns: number
  min: number
  max: number
  onChange: (columns: number) => void
}) {
  const latest = useRef({ columns, onChange })
  useEffect(() => { latest.current = { columns, onChange } }, [columns, onChange])

  useEffect(() => {
    const element = target.current
    if (!enabled || !element) return
    let start: { distance: number; columns: number } | null = null
    const onStart = (event: TouchEvent) => {
      if (event.touches.length === 2) start = { distance: Math.max(1, spread(event.touches)), columns: latest.current.columns }
    }
    const onMove = (event: TouchEvent) => {
      if (!start || event.touches.length !== 2) return
      event.preventDefault()
      const next = Math.min(max, Math.max(min, Math.round(start.columns / (spread(event.touches) / start.distance))))
      if (next !== latest.current.columns) latest.current.onChange(next)
    }
    const onEnd = (event: TouchEvent) => {
      if (event.touches.length < 2) start = null
    }
    element.addEventListener('touchstart', onStart, { passive: true })
    element.addEventListener('touchmove', onMove, { passive: false })
    element.addEventListener('touchend', onEnd)
    element.addEventListener('touchcancel', onEnd)
    return () => {
      element.removeEventListener('touchstart', onStart)
      element.removeEventListener('touchmove', onMove)
      element.removeEventListener('touchend', onEnd)
      element.removeEventListener('touchcancel', onEnd)
    }
  }, [target, enabled, min, max])
}
