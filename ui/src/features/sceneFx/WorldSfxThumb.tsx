import { useEffect, useRef } from 'react'
import type { WorldSfxKind } from './world'
import { subscribeWorldSfxThumb } from './worldSfxPreview'

export function WorldSfxThumb({ kind }: { kind: WorldSfxKind }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (!canvas.current) return
    return subscribeWorldSfxThumb(kind, canvas.current)
  }, [kind])
  return <canvas ref={canvas} width={192} height={108} className="h-[108px] w-full rounded-md bg-[#10131c]" aria-hidden="true" data-testid={`world-sfx-thumb-${kind}`} />
}
