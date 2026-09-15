import { useEffect, useRef } from 'react'
import type { Scene3DTemplateId } from './types.ts'
import { subscribeTemplateThumb } from './templatePreview.ts'

export function Scene3DTemplateThumb({ id }: { id: Scene3DTemplateId }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvas.current) return
    return subscribeTemplateThumb(id, canvas.current)
  }, [id])
  return <canvas
    ref={canvas}
    width={320}
    height={180}
    className="h-[104px] w-full rounded-md bg-[#10131c]"
    aria-hidden="true"
    data-testid={`world3d-template-thumb-${id}`}
  />
}
