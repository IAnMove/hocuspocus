import { useEffect, useRef } from 'react'
import { ensureTextFonts, paintKineticTexts, paintSceneLyrics, type KineticText, type SceneLyrics } from '../../lib/kineticText'

export function KineticTextOverlay({ cues, lyrics, seconds, width, height, envelope = 0 }: { cues?: KineticText[]; lyrics?: SceneLyrics; seconds: number; width: number; height: number; envelope?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const ratio = Math.min(1, 1280 / Math.max(1, width), 720 / Math.max(1, height))
  const pixelWidth = Math.max(1, Math.round(width * ratio))
  const pixelHeight = Math.max(1, Math.round(height * ratio))
  useEffect(() => {
    let cancel = false
    const draw = () => {
      const ctx = canvas.current?.getContext('2d')
      if (!ctx || cancel) return
      ctx.clearRect(0, 0, pixelWidth, pixelHeight)
      paintKineticTexts(ctx, pixelWidth, pixelHeight, seconds, cues, envelope)
      paintSceneLyrics(ctx, pixelWidth, pixelHeight, seconds, lyrics, envelope)
    }
    draw()
    void ensureTextFonts(cues).then(draw)
    return () => { cancel = true }
  }, [cues, lyrics, seconds, pixelWidth, pixelHeight, envelope])
  return cues?.length || lyrics ? <canvas ref={canvas} width={pixelWidth} height={pixelHeight} aria-hidden="true" className="pointer-events-none absolute inset-0 z-[900] h-full w-full" /> : null
}
