import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { atlasFrames, atlasLoops, frameDelayMs, stepFrame, type AtlasFrame } from './reviewModel'
import { buttonClass } from './styles'

type Backdrop = 'checker' | 'color' | 'tile'

function paintFrame(
  canvas: HTMLCanvasElement | null,
  image: HTMLImageElement | null,
  frame: AtlasFrame | undefined,
  options: { scale: number; mirror: boolean; pixel: boolean; backdrop: Backdrop; color: string },
): void {
  if (!canvas || !frame) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const width = Math.max(1, frame.w * options.scale)
  const height = Math.max(1, frame.h * options.scale)
  canvas.width = width
  canvas.height = height
  ctx.imageSmoothingEnabled = !options.pixel
  fillBackdrop(ctx, width, height, options.backdrop, options.color)
  if (!image?.complete || !image.naturalWidth) return
  ctx.save()
  if (options.mirror) {
    ctx.translate(width, 0)
    ctx.scale(-1, 1)
  }
  ctx.drawImage(image, frame.x, frame.y, frame.w, frame.h, 0, 0, width, height)
  ctx.restore()
}

function fillBackdrop(ctx: CanvasRenderingContext2D, width: number, height: number, backdrop: Backdrop, color: string): void {
  if (backdrop === 'color') {
    ctx.fillStyle = color
    ctx.fillRect(0, 0, width, height)
    return
  }
  const cell = backdrop === 'tile' ? 16 : 8
  for (let y = 0; y < height; y += cell) {
    for (let x = 0; x < width; x += cell) {
      const light = ((x / cell) + (y / cell)) % 2 === 0
      ctx.fillStyle = backdrop === 'tile' ? (light ? '#3f6212' : '#14532d') : (light ? '#2a2a35' : '#1a1a25')
      ctx.fillRect(x, y, cell, cell)
    }
  }
}

export function SpriteSheetPlayer({ imageUrl, atlas, pixel }: { imageUrl: string; atlas: unknown; pixel: boolean }) {
  const { t } = useUiTranslation('gameAssets')
  const frames = atlasFrames(atlas)
  const [index, setIndex] = useState(0)
  const [scale, setScale] = useState(1)
  const [mirror, setMirror] = useState(false)
  const [loop, setLoop] = useState(() => atlasLoops(atlas))
  const [backdrop, setBackdrop] = useState<Backdrop>('checker')
  const [color, setColor] = useState('#1a1a25')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const frame = frames[Math.min(index, Math.max(0, frames.length - 1))]
  const delay = frameDelayMs(frame?.duration)

  useEffect(() => {
    const image = new Image()
    image.onload = () => {
      imageRef.current = image
      paintFrame(canvasRef.current, image, frame, { scale, mirror, pixel, backdrop, color })
    }
    image.src = imageUrl
    return () => { image.onload = null }
  }, [imageUrl, frame, scale, mirror, pixel, backdrop, color])

  useEffect(() => {
    const timer = setTimeout(() => setIndex(current => stepFrame(current, frames.length, loop)), delay)
    return () => clearTimeout(timer)
  }, [index, delay, loop, frames.length])

  return (
    <div className="space-y-2">
      <canvas ref={canvasRef} data-frame={index} className="max-w-full border border-border" />
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">{t('scale')}
          <select aria-label={t('scale')} className="ml-1" value={scale} onChange={event => setScale(Number(event.target.value))}>
            {[1, 2, 4, 8].map(value => <option key={value} value={value}>×{value}</option>)}
          </select>
        </label>
        <label className="text-sm">{t('backdrop')}
          <select aria-label={t('backdrop')} className="ml-1" value={backdrop} onChange={event => setBackdrop(event.target.value as Backdrop)}>
            <option value="checker">{t('checker')}</option>
            <option value="color">{t('solid')}</option>
            <option value="tile">{t('tileBackdrop')}</option>
          </select>
        </label>
        {backdrop === 'color' && <input aria-label={t('solid')} type="color" value={color} onChange={event => setColor(event.target.value)} />}
        <button type="button" className={buttonClass} aria-pressed={mirror} onClick={() => setMirror(value => !value)}>{t('mirror')}</button>
        <button type="button" className={buttonClass} aria-pressed={loop} onClick={() => setLoop(value => !value)}>{t('repeat')}</button>
      </div>
    </div>
  )
}
