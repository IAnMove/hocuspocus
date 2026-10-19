import { useCallback, useEffect, useRef } from 'react'
import type { Scene3DDocument, Scene3DTemplateId } from './types.ts'
import { subscribeDocumentThumb, subscribeTemplateThumb } from './templatePreview.ts'

type ThumbLayout = { portrait?: boolean; fill?: boolean }

/** The canvas every thumb shares. `fill` makes it span its card at 16:9; it only starts drawing once it scrolls
 *  into view, so a big library stays light. `start` must keep its identity between renders. */
function LazyThumb({ testId, portrait = false, fill = false, start }: ThumbLayout & { testId: string; start: (canvas: HTMLCanvasElement) => () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const target = canvas.current
    if (!target) return
    if (typeof IntersectionObserver === 'undefined') return start(target)
    let stop: (() => void) | undefined
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return
      observer.disconnect()
      stop = start(target)
    }, { rootMargin: '200px' })
    observer.observe(target)
    return () => { observer.disconnect(); stop?.() }
  }, [start])
  return <canvas
    ref={canvas}
    width={320}
    height={180}
    className={`${fill ? 'aspect-video h-auto' : portrait ? 'h-44' : 'h-[104px]'} w-full rounded-md bg-[#10131c]`}
    aria-hidden="true"
    data-testid={testId}
  />
}

/** A built-in template's preview. */
export function Scene3DTemplateThumb({ id, ...layout }: ThumbLayout & { id: Scene3DTemplateId }) {
  const start = useCallback((canvas: HTMLCanvasElement) => subscribeTemplateThumb(id, canvas), [id])
  return <LazyThumb testId={`world3d-template-thumb-${id}`} start={start} {...layout} />
}

/** A document the library fetches (a stage card) drawn by the same renderer; `load` runs once the canvas is in view
 *  and must keep its identity between renders. */
export function Scene3DDocumentThumb({ id, load, ...layout }: ThumbLayout & { id: string; load: () => Promise<Scene3DDocument> }) {
  const start = useCallback((canvas: HTMLCanvasElement) => subscribeDocumentThumb(load, canvas), [load])
  return <LazyThumb testId={`world3d-template-thumb-${id}`} start={start} {...layout} />
}
