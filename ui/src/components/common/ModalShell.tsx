import { useEffect, useId, useRef, type ReactNode } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter(element => element.getAttribute('aria-hidden') !== 'true' && !element.hidden)
}

interface ModalShellProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
  onMouseDown?: (event: React.MouseEvent<HTMLDivElement>) => void
}

/**
 * Small modal primitive for overlays that own the page interaction while open.
 * The caller supplies the visual shell; this component owns dialog semantics,
 * keyboard containment, and focus hand-off.
 */
export function ModalShell({
  open,
  title,
  onClose,
  children,
  className,
  onMouseDown,
}: ModalShellProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return

    restoreFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null

    const dialog = dialogRef.current
    const first = dialog ? focusableElements(dialog)[0] : undefined
    ;(first ?? dialog)?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      const currentDialog = dialogRef.current
      if (!currentDialog) return

      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }

      if (event.key !== 'Tab') return

      const focusable = focusableElements(currentDialog)
      if (focusable.length === 0) {
        event.preventDefault()
        currentDialog.focus()
        return
      }

      const active = document.activeElement
      const firstFocusable = focusable[0]
      const lastFocusable = focusable[focusable.length - 1]
      if (event.shiftKey && (active === firstFocusable || !currentDialog.contains(active))) {
        event.preventDefault()
        lastFocusable.focus()
      } else if (!event.shiftKey && (active === lastFocusable || !currentDialog.contains(active))) {
        event.preventDefault()
        firstFocusable.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      restoreFocusRef.current?.focus()
      restoreFocusRef.current = null
    }
  }, [open])

  if (!open) return null

  return (
    <div
      ref={dialogRef}
      id={titleId}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      tabIndex={-1}
      className={className}
      onMouseDown={onMouseDown}
    >
      {children}
    </div>
  )
}
