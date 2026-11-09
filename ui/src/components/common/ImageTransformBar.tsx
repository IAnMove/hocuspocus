import { useRef, useState, type ComponentType } from 'react'
import { FlipHorizontal, FlipVertical, RotateCcw, RotateCw } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { CropRect } from '../../lib/imageCrop'
import { loadFitImage } from '../../lib/imageFit'
import { IMAGE_TRANSFORMS, canvasObjectUrl, transformImage, transformRect, type ImageTransform } from '../../lib/imageTransform'

/** The picture after one change, with the selected area carried over to it. */
export type TransformedView = { image: HTMLImageElement; url: string; rect: CropRect }

const ICONS: Record<ImageTransform, ComponentType<{ size?: number }>> = {
  rotateLeft: RotateCcw, rotateRight: RotateCw, flipHorizontal: FlipHorizontal, flipVertical: FlipVertical,
}

/** Rotate and flip buttons of the image editor. One change at a time: the next one starts from the result. */
export default function ImageTransformBar({ image, rect, disabled, onResult, onError }: {
  image: HTMLImageElement; rect: CropRect; disabled?: boolean
  onResult: (view: TransformedView) => void; onError: () => void
}) {
  const { t } = useUiTranslation('common')
  const [pending, setPending] = useState(false)
  const running = useRef(false)
  const apply = async (op: ImageTransform) => {
    if (running.current) return
    running.current = true; setPending(true)
    try {
      const url = await canvasObjectUrl(transformImage(image, op))
      onResult({ image: await loadFitImage(url), url, rect: transformRect(rect, image.naturalWidth, image.naturalHeight, op) })
    } catch { onError() }
    finally { running.current = false; setPending(false) }
  }
  return <div role="group" aria-label={t('crop.transformGroup')} className="flex flex-wrap gap-2">
    {IMAGE_TRANSFORMS.map(op => {
      const Icon = ICONS[op]
      return <button key={op} type="button" disabled={disabled || pending} aria-label={t(`crop.${op}`)} title={t(`crop.${op}`)}
        onClick={() => void apply(op)} className="inline-flex items-center gap-1 rounded border border-border bg-bg-tertiary px-2 py-1 text-xs disabled:opacity-40">
        <Icon size={14} />{t(`crop.${op}`)}
      </button>
    })}
  </div>
}
