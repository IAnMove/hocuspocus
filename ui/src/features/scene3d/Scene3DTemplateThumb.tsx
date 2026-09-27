import { useEffect, useRef } from 'react'
import type { Scene3DTemplateId } from './types.ts'
import { subscribeTemplateThumb } from './templatePreview.ts'

/** A template's preview. `fill` makes it span its card at 16:9; the canvas
 *  only starts rendering once it scrolls into view, so a big library stays light. */
export function Scene3DTemplateThumb({ id, portrait = false, fill = false }: { id: Scene3DTemplateId; portrait?: boolean; fill?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const target = canvas.current
    if (!target) return
    if (typeof IntersectionObserver === 'undefined') return subscribeTemplateThumb(id, target)
    let stop: (() => void) | undefined
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return
      observer.disconnect()
      stop = subscribeTemplateThumb(id, target)
    }, { rootMargin: '200px' })
    observer.observe(target)
    return () => { observer.disconnect(); stop?.() }
  }, [id])
  return <canvas
    ref={canvas}
    width={320}
    height={180}
    className={`${fill ? 'aspect-video h-auto' : portrait ? 'h-44' : 'h-[104px]'} w-full rounded-md bg-[#10131c]`}
    aria-hidden="true"
    data-testid={`world3d-template-thumb-${id}`}
  />
}
