import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface HorizontalScrollTabsProps {
  children: ReactNode
  activeKey?: string
  className?: string
  viewportClassName?: string
  ariaLabel?: string
}

export function HorizontalScrollTabs({
  children,
  activeKey,
  className = '',
  viewportClassName = '',
  ariaLabel = 'Scrollable tabs',
}: HorizontalScrollTabsProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [edges, setEdges] = useState({ left: false, right: false })

  const updateEdges = useCallback(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const max = Math.max(0, viewport.scrollWidth - viewport.clientWidth)
    setEdges({
      left: viewport.scrollLeft > 2,
      right: viewport.scrollLeft < max - 2,
    })
  }, [])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const observer = new ResizeObserver(updateEdges)
    observer.observe(viewport)
    Array.from(viewport.children).forEach(child => observer.observe(child))
    viewport.addEventListener('scroll', updateEdges, { passive: true })
    const frame = window.requestAnimationFrame(updateEdges)
    return () => {
      window.cancelAnimationFrame(frame)
      viewport.removeEventListener('scroll', updateEdges)
      observer.disconnect()
    }
  }, [children, updateEdges])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport || !activeKey) return
    const active = Array.from(viewport.querySelectorAll<HTMLElement>('[data-scroll-key]'))
      .find(element => element.dataset.scrollKey === activeKey)
    active?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
  }, [activeKey])

  const move = (direction: -1 | 1) => {
    const viewport = viewportRef.current
    if (!viewport) return
    viewport.scrollBy({
      left: direction * Math.max(160, viewport.clientWidth * 0.7),
      behavior: 'smooth',
    })
  }

  const arrowClass = 'shrink-0 rounded-md border border-border bg-bg-tertiary p-1.5 text-text-secondary shadow-sm hover:bg-bg-hover hover:text-text-primary'

  return (
    <div className={`flex min-w-0 items-center gap-1 ${className}`}>
      {edges.left && (
        <button
          type="button"
          className={arrowClass}
          onClick={() => move(-1)}
          aria-label="Show previous tabs"
          title="Previous tabs"
        >
          <ChevronLeft size={14} />
        </button>
      )}
      <div
        ref={viewportRef}
        role="tablist"
        aria-label={ariaLabel}
        className={`min-w-0 flex-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${viewportClassName}`}
      >
        {children}
      </div>
      {edges.right && (
        <button
          type="button"
          className={arrowClass}
          onClick={() => move(1)}
          aria-label="Show more tabs"
          title="More tabs"
        >
          <ChevronRight size={14} />
        </button>
      )}
    </div>
  )
}
