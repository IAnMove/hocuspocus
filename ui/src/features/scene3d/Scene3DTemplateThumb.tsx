import { useEffect, useRef } from 'react'
import type { Scene3DTemplateId } from './types.ts'
import { subscribeTemplateThumb } from './templatePreview.ts'
import { isDarkFantasyTemplate } from './darkFantasyIds'
import { isCreativeTemplate } from './creativeTemplateIds'

export function Scene3DTemplateThumb({ id, portrait = false }: { id: Scene3DTemplateId; portrait?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const bundled = isDarkFantasyTemplate(id) ? 'dark-fantasy' : isCreativeTemplate(id) ? 'creative' : null
  useEffect(() => {
    if (!canvas.current || bundled) return
    return subscribeTemplateThumb(id, canvas.current)
  }, [id, bundled])
  if (bundled) return <img src={`/examples/${bundled}/${id}.png`} alt="" loading="lazy"
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
