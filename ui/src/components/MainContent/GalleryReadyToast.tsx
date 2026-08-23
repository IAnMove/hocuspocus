import { useEffect } from 'react'
import { useStore } from '../../stores/useStore'

export function GalleryReadyToast() {
  const toast = useStore(s => s.galleryToast)
  const clearGalleryToast = useStore(s => s.clearGalleryToast)

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => clearGalleryToast(), 4000)
    return () => window.clearTimeout(timer)
  }, [toast, clearGalleryToast])

  if (!toast) return null
  return (
    <div
      role="status"
      className="pointer-events-none fixed bottom-16 left-1/2 z-[70] max-w-[min(90vw,28rem)] -translate-x-1/2 rounded-lg border border-border bg-bg-secondary/95 px-3 py-2 text-xs text-text-primary shadow-lg"
    >
      {toast.message}
    </div>
  )
}
