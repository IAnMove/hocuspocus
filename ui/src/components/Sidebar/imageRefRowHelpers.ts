import type { DragEvent, LiHTMLAttributes } from 'react'

export const referenceRowButton = 'min-h-11 rounded border border-border px-3 text-xs text-text-secondary'

export function hasReferenceFiles(primary: readonly File[], rows?: readonly (readonly File[])[]): boolean {
  return primary.length > 0 || (rows || []).some(row => row.length > 0)
}

/** Drag-to-reorder for the first row; the other rows reorder with the buttons. */
export function referenceDragProps(
  index: number,
  setOver: (index: number | null) => void,
  reorder: (from: number, to: number) => void,
): LiHTMLAttributes<HTMLLIElement> {
  return {
    draggable: true,
    onDragStart: (event: DragEvent) => {
      event.dataTransfer.setData('ref-index', String(index))
      event.dataTransfer.effectAllowed = 'move'
    },
    onDragOver: (event: DragEvent) => {
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
      setOver(index)
    },
    onDragLeave: () => setOver(null),
    onDrop: (event: DragEvent) => {
      event.preventDefault()
      event.stopPropagation()
      setOver(null)
      const from = parseInt(event.dataTransfer.getData('ref-index'), 10)
      if (!isNaN(from) && from !== index) reorder(from, index)
    },
  }
}
