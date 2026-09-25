import { isCutoutMotionTemplate } from './cutoutMotionIds'
import { useEffect, useRef } from 'react'
import type { Scene3DTemplateId } from './types.ts'
import { subscribeTemplateThumb } from './templatePreview.ts'
import { isDarkFantasyTemplate } from './darkFantasyIds'
import { isCreativeTemplate } from './creativeTemplateIds'

/** A template's preview. `fill` makes it span its card at 16:9; the canvas
 *  only starts rendering once it scrolls into view, so a big library stays light. */
export function Scene3DTemplateThumb({ id, portrait = false, fill = false }: { id: Scene3DTemplateId; portrait?: boolean; fill?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const bundled = isCutoutMotionTemplate(id) ? 'moving-cutouts' : id.startsWith('dark-still-') ? 'dark-stillness' : isDarkFantasyTemplate(id) ? 'dark-fantasy' : isCreativeTemplate(id) ? 'creative' : null
  useEffect(() => {
    const target = canvas.current
    if (!target || bundled) return
    if (typeof IntersectionObserver === 'undefined') return subscribeTemplateThumb(id, target)
    let stop: (() => void) | undefined
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return
      observer.disconnect()
      stop = subscribeTemplateThumb(id, target)
    }, { rootMargin: '200px' })
    observer.observe(target)
    return () => { observer.disconnect(); stop?.() }
  }, [id, bundled])
  const size = fill ? 'aspect-video h-auto' : portrait ? 'h-44' : 'h-[104px]'
  if (bundled) return <img src={`/examples/${bundled}/${id}.png`} alt="" loading="lazy"
    className={`${size} w-full rounded-md bg-[#10131c] object-contain`} data-testid={`world3d-template-thumb-${id}`} />
  return <canvas
    ref={canvas}
    width={320}
    height={180}
    className={`${fill ? 'aspect-video h-auto' : 'h-[104px]'} w-full rounded-md bg-[#10131c]`}
    aria-hidden="true"
    data-testid={`world3d-template-thumb-${id}`}
  />
}
