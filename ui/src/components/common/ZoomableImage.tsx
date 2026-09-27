import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type SyntheticEvent } from 'react'

const MAX_SCALE = 5
const DOUBLE_TAP_ZOOM = 2.5
const DOUBLE_TAP_MS = 300
const TAP_SLOP = 12
const SWIPE_DISTANCE = 56

type Point = { x: number; y: number }
type View = { scale: number; x: number; y: number }
const REST: View = { scale: 1, x: 0, y: 0 }

function distance(a: Point, b: Point) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/** A full-size image that can be pinched, double-tapped or ctrl-scrolled to
 *  zoom and dragged while zoomed. At rest, a horizontal swipe asks for the
 *  previous or next item; vertical drags stay with the page so the details
 *  below the image remain scrollable on a phone. */
export function ZoomableImage({ src, alt, className, onLoad, onError, onSwipe, onZoomChange }: {
  src: string
  alt: string
  className?: string
  onLoad?: (event: SyntheticEvent<HTMLImageElement>) => void
  onError?: () => void
  onSwipe?: (direction: 'previous' | 'next') => void
  onZoomChange?: (zoomed: boolean) => void
}) {
  const [view, setView] = useState<View>(REST)
  const [dragging, setDragging] = useState(false)
  const pointers = useRef(new Map<number, Point>())
  const gesture = useRef<{ start: View; origin: Point; pinch?: { distance: number; mid: Point } } | null>(null)
  const lastTap = useRef<{ at: number; point: Point } | null>(null)
  const frame = useRef<HTMLDivElement>(null)

  const apply = useCallback((next: View) => {
    const scale = Math.min(MAX_SCALE, Math.max(1, next.scale))
    const resting = scale <= 1.01
    const view = resting ? REST : { scale, x: next.x, y: next.y }
    setView(view)
    onZoomChange?.(!resting)
  }, [onZoomChange])

  /** Zoom around a point given in viewport coordinates. */
  const zoomAt = useCallback((current: View, scale: number, at: Point): View => {
    const box = frame.current?.getBoundingClientRect()
    if (!box) return { ...current, scale }
    const cx = at.x - (box.left + box.width / 2)
    const cy = at.y - (box.top + box.height / 2)
    const ratio = scale / current.scale
    return { scale, x: cx - (cx - current.x) * ratio, y: cy - (cy - current.y) * ratio }
  }, [])

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const points = [...pointers.current.values()]
    gesture.current = {
      start: view,
      origin: { x: event.clientX, y: event.clientY },
      ...(points.length === 2 ? { pinch: { distance: distance(points[0], points[1]), mid: { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 } } } : {}),
    }
    setDragging(true)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    const { start, origin, pinch } = gesture.current
    const points = [...pointers.current.values()]
    if (pinch && points.length >= 2) {
      const scale = start.scale * (distance(points[0], points[1]) / Math.max(1, pinch.distance))
      apply(zoomAt(start, Math.min(MAX_SCALE, Math.max(1, scale)), pinch.mid))
      return
    }
    if (start.scale > 1) apply({ ...start, x: start.x + event.clientX - origin.x, y: start.y + event.clientY - origin.y })
  }

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = gesture.current
    pointers.current.delete(event.pointerId)
    if (pointers.current.size > 0) {
      // One finger of a pinch lifted: continue as a drag from here.
      const [point] = pointers.current.values()
      gesture.current = { start: view, origin: point }
      return
    }
    gesture.current = null
    setDragging(false)
    if (!current || current.pinch) return
    const dx = event.clientX - current.origin.x
    const dy = event.clientY - current.origin.y
    if (current.start.scale <= 1 && Math.abs(dx) > SWIPE_DISTANCE && Math.abs(dx) > Math.abs(dy) * 1.5) {
      lastTap.current = null
      onSwipe?.(dx < 0 ? 'next' : 'previous')
      return
    }
    if (Math.abs(dx) > TAP_SLOP || Math.abs(dy) > TAP_SLOP) return
    const now = performance.now()
    const tap = { x: event.clientX, y: event.clientY }
    if (lastTap.current && now - lastTap.current.at < DOUBLE_TAP_MS && distance(lastTap.current.point, tap) < TAP_SLOP * 2) {
      lastTap.current = null
      apply(view.scale > 1 ? REST : zoomAt(view, DOUBLE_TAP_ZOOM, tap))
      return
    }
    lastTap.current = { at: now, point: tap }
  }

  const onPointerCancel = (event: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId)
    if (pointers.current.size === 0) {
      gesture.current = null
      setDragging(false)
    }
  }

  // Trackpad pinches arrive as ctrl+wheel. React's wheel listener is passive,
  // so the page would zoom too; a native listener can claim the gesture.
  // Plain wheel keeps scrolling the details panel.
  const viewRef = useRef(view)
  useEffect(() => { viewRef.current = view }, [view])
  useEffect(() => {
    const element = frame.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return
      event.preventDefault()
      const current = viewRef.current
      apply(zoomAt(current, current.scale * Math.exp(-event.deltaY / 200), { x: event.clientX, y: event.clientY }))
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [apply, zoomAt])

  const zoomed = view.scale > 1
  return (
    <div
      ref={frame}
      data-testid="zoomable-image"
      data-zoom={view.scale.toFixed(2)}
      className="relative flex max-h-full max-w-full select-none items-center justify-center overflow-hidden"
      style={{ touchAction: zoomed ? 'none' : 'pan-y', cursor: zoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onDoubleClick={event => event.preventDefault()}
    >
      <img
        src={src}
        alt={alt}
        draggable={false}
        className={className}
        style={{
          transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`,
          transition: dragging ? 'none' : 'transform 160ms ease-out',
        }}
        onLoad={onLoad}
        onError={onError}
      />
    </div>
  )
}
