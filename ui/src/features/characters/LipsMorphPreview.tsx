import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import type { CharacterFaceAnchor } from '../../lib/characterKit'
import { mouthContourMesh, renderMouthMorph, type MouthMorphFrame } from '../../lib/lipsMorph'

export type LipsMorphImage = { source: string; anchor?: CharacterFaceAnchor }
const SIZE = 384
const imageKey = (image: LipsMorphImage) => JSON.stringify(image)
const canvas = () => { const element = document.createElement('canvas'); element.width = SIZE; element.height = SIZE; return element }

async function prepareImage(key: string): Promise<MouthMorphFrame> {
  const { source, anchor } = JSON.parse(key) as LipsMorphImage
  const image = new Image()
  image.crossOrigin = 'anonymous'; image.src = source
  await image.decode()
  const surface = canvas(), context = surface.getContext('2d', { willReadFrequently: true })!
  const boxWidth = SIZE * (anchor ? Math.max(.005, anchor.scale) : .75)
  const boxHeight = SIZE * (anchor ? Math.max(.005, anchor.scale) : .65)
  const scale = Math.min(boxWidth / image.naturalWidth, boxHeight / image.naturalHeight)
  context.translate(SIZE * (.5 + (anchor?.offsetX ?? 0) / 100), SIZE * (.5 + (anchor?.offsetY ?? 0) / 100))
  context.rotate((anchor?.rotation ?? 0) * Math.PI / 180)
  context.drawImage(image, -image.naturalWidth * scale / 2, -image.naturalHeight * scale / 2, image.naturalWidth * scale, image.naturalHeight * scale)
  const pixels = context.getImageData(0, 0, SIZE, SIZE)
  // Inspect original transparency as well: padding around an opaque image is not a lip contour.
  const original = document.createElement('canvas'); original.width = 96; original.height = 96
  const probe = original.getContext('2d', { willReadFrequently: true })!
  probe.drawImage(image, 0, 0, 96, 96)
  const mesh = mouthContourMesh(probe.getImageData(0, 0, 96, 96).data, 96, 96)
    ? mouthContourMesh(pixels.data, SIZE, SIZE) : undefined
  return { image: surface, mesh }
}

export function LipsMorphPreview({ image, images, manual, duration, animate, resetToken, alt, fallbackClassName, fallbackStyle, onSupportChange }: {
  image: LipsMorphImage; images: LipsMorphImage[]; manual?: { from: LipsMorphImage; to: LipsMorphImage; progress: number }
  duration: number; animate: boolean; resetToken: number; alt: string
  fallbackClassName: string; fallbackStyle?: CSSProperties; onSupportChange: (supported: boolean) => void
}) {
  const surface = useRef<HTMLCanvasElement>(null), cache = useRef(new Map<string, Promise<MouthMorphFrame>>())
  const displayed = useRef<MouthMorphFrame | undefined>(undefined)
  const previousReset = useRef(resetToken)
  const layers = useRef<readonly [HTMLCanvasElement, HTMLCanvasElement] | undefined>(undefined)
  const [ready, setReady] = useState(false)
  const targetKey = imageKey(image), fromKey = manual ? imageKey(manual.from) : '', toKey = manual ? imageKey(manual.to) : ''
  const progress = manual?.progress, preloadKey = JSON.stringify(images.map(imageKey))
  const getFrame = useCallback((key: string) => {
    let frame = cache.current.get(key)
    if (!frame) { frame = prepareImage(key); cache.current.set(key, frame) }
    return frame
  }, [])
  useEffect(() => {
    const keys = JSON.parse(preloadKey) as string[]
    for (const key of keys) void getFrame(key).catch(() => {})
    // Discard superseded sprites/placements instead of accumulating regenerated PNGs.
    for (const key of cache.current.keys()) if (!keys.includes(key)) cache.current.delete(key)
  }, [preloadKey, getFrame])
  useEffect(() => {
    let stopped = false, request = 0
    const element = surface.current, context = element?.getContext('2d')
    if (!element || !context) return
    const reset = resetToken !== previousReset.current
    previousReset.current = resetToken
    const render = (from: MouthMorphFrame, to: MouthMorphFrame, mix: number) => {
      layers.current ??= [canvas(), canvas()]
      const mesh = renderMouthMorph(context, from, to, mix, layers.current)
      // A new phoneme can arrive midway through a transition. Start from this exact drawing.
      displayed.current = { image: element, mesh }
      element.dataset.progress = String(mix); element.dataset.mode = from.mesh && to.mesh ? 'warp' : 'direct'
      setReady(true)
    }
    const run = async () => {
      if (fromKey && toKey && progress !== undefined) {
        const [from, to] = await Promise.all([getFrame(fromKey), getFrame(toKey)])
        if (stopped) return
        onSupportChange(Boolean(from.mesh && to.mesh)); render(from, to, progress); return
      }
      const target = await getFrame(targetKey)
      if (stopped) return
      onSupportChange(Boolean(target.mesh))
      if (reset || !animate || !displayed.current?.mesh || !target.mesh || duration <= 0) { render(target, target, 1); return }
      const snapshot = canvas(); snapshot.getContext('2d')!.drawImage(element, 0, 0)
      const from = { image: snapshot, mesh: displayed.current.mesh }, start = performance.now()
      const tick = (now: number) => {
        if (stopped) return
        const fraction = Math.min(1, Math.max(0, (now - start) / duration))
        const eased = fraction * fraction * (3 - 2 * fraction)
        render(from, target, eased)
        if (fraction < 1) request = requestAnimationFrame(tick)
      }
      request = requestAnimationFrame(tick)
    }
    void run().catch(() => { if (!stopped) { setReady(false); onSupportChange(false) } })
    return () => { stopped = true; cancelAnimationFrame(request) }
  }, [targetKey, fromKey, toKey, progress, animate, duration, resetToken, onSupportChange, getFrame])
  return <>
    {!ready && <img src={image.source} alt={alt} className={fallbackClassName} style={fallbackStyle} />}
    <canvas ref={surface} width={SIZE} height={SIZE} role="img" aria-label={alt} data-testid="lips-morph-canvas"
      className={`absolute inset-0 h-full w-full ${ready ? '' : 'invisible'}`} />
  </>
}
