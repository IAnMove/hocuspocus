import { useEffect, useRef } from 'react'
import type { Scene3DTemplateId } from './types.ts'
import { subscribeTemplateThumb } from './templatePreview.ts'
import { isDarkFantasyTemplate } from './darkFantasyIds'

export function Scene3DTemplateThumb({ id, portrait = false }: { id: Scene3DTemplateId; portrait?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvas.current || isDarkFantasyTemplate(id)) return
    return subscribeTemplateThumb(id, canvas.current)
  }, [id])
  if (isDarkFantasyTemplate(id)) return <img src={`/examples/dark-fantasy/${id}.png`} alt="" loading="lazy"
    className={`${portrait ? 'h-44' : 'h-[104px]'} w-full rounded-md bg-[#10131c] object-contain`} data-testid={`world3d-template-thumb-${id}`} />
  return <canvas
    ref={canvas}
    width={320}
    height={180}
    className="h-[104px] w-full rounded-md bg-[#10131c]"
    aria-hidden="true"
    data-testid={`world3d-template-thumb-${id}`}
  />
}
