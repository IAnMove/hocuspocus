import { useEffect, useRef, type RefObject } from 'react'
import type { GalleryDirection } from './mediaGalleryLayout'

const KEYS: Record<string, GalleryDirection> = {
  ArrowDown: 'down', j: 'down',
  ArrowUp: 'up', k: 'up',
  ArrowLeft: 'left', h: 'left',
  ArrowRight: 'right', l: 'right',
}

function ignoredTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null
  if (!element) return false
  if (element.isContentEditable || /^(INPUT|TEXTAREA|SELECT|VIDEO|AUDIO)$/.test(element.tagName)) return true
  // Other panels' own controls (sliders, listboxes, menus) keep their arrows.
  return !!element.closest('[role="slider"], [role="listbox"], [role="menu"], [role="tablist"], [role="radiogroup"]')
}

/** Desktop browsing without the mouse: arrows or h/j/k/l move the current
 *  item (a row at a time vertically), Enter opens its details, Escape leaves
 *  selection mode. Inactive while typing or while any dialog is open. */
export function useGalleryKeyboard({ scope, enabled, onMove, onOpen, onEscape }: {
  /** The gallery's scroller; keys only apply while it is on screen. */
  scope: RefObject<HTMLElement | null>
  enabled: boolean
  onMove: (direction: GalleryDirection) => void
  onOpen: () => void
  onEscape?: () => void
}) {
  const handlers = useRef({ onMove, onOpen, onEscape })
  useEffect(() => { handlers.current = { onMove, onOpen, onEscape } }, [onMove, onOpen, onEscape])

  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || ignoredTarget(event.target)) return
      const gallery = scope.current
      if (!gallery?.isConnected || gallery.offsetParent === null) return
      if (document.querySelector('[aria-modal="true"]')) return
      const direction = KEYS[event.key]
      if (direction) {
        event.preventDefault()
        handlers.current.onMove(direction)
      } else if (event.key === 'Enter' && !(event.target as HTMLElement | null)?.closest('button, a')) {
        event.preventDefault()
        handlers.current.onOpen()
      } else if (event.key === 'Escape' && handlers.current.onEscape) {
        handlers.current.onEscape()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, scope])
}
