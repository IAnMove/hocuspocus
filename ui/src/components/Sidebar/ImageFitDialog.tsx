import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { localEditPreview, rememberLocalImage } from '../../lib/localEditImages'
import { useStore } from '../../stores/useStore'

type FitMode = 'contain' | 'cover' | 'stretch'

function modelCanvases(): string[] {
  const options = useStore.getState().modelOptions
  const values = new Set<string>()
  for (const preset of Object.values(options?.resolution_presets || {})) {
    for (const value of Object.values(preset.values || {})) {
      if (/^\d+x\d+$/.test(value)) values.add(value)
    }
  }
  if (!values.size) {
    ;['1024x1024', '1280x720', '720x1280', '2048x2048'].forEach(item => values.add(item))
  }
  return [...values]
}

function paintFit(image: HTMLImageElement, width: number, height: number, mode: FitMode): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas')
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, width, height)
  if (mode === 'stretch') {
    ctx.drawImage(image, 0, 0, width, height)
    return canvas
  }
  const scale = mode === 'cover'
    ? Math.max(width / image.width, height / image.height)
    : Math.min(width / image.width, height / image.height)
  const drawW = image.width * scale
  const drawH = image.height * scale
  ctx.drawImage(image, (width - drawW) / 2, (height - drawH) / 2, drawW, drawH)
  return canvas
}

export function ImageFitDialog({
  source,
  onClose,
}: {
  source: string
  onClose: () => void
}) {
  const { t } = useUiTranslation('studio')
  const setParams = useStore(s => s.setParams)
  const setParam = useStore(s => s.setParam)
  const canvases = useMemo(() => modelCanvases(), [])
  const current = String(useStore.getState().params.resolution || canvases[0])
  const [target, setTarget] = useState(canvases.includes(current) ? current : canvases[0])
  const [mode, setMode] = useState<FitMode>('contain')
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const src = localEditPreview(source)

  useEffect(() => {
    const image = new Image()
    image.onload = () => {
      const [width, height] = target.split('x').map(Number)
      setPreview(paintFit(image, width, height, mode).toDataURL('image/jpeg', 0.85))
    }
    image.src = src
  }, [src, target, mode])

  const apply = async () => {
    const image = new Image()
    image.src = src
    await image.decode()
    const [width, height] = target.split('x').map(Number)
    const blob = await new Promise<Blob>((resolve, reject) => {
      paintFit(image, width, height, mode).toBlob(
        value => value ? resolve(value) : reject(new Error('blob')),
        'image/jpeg',
        0.92,
      )
    })
    setBusy(true)
    try {
      const file = new File([blob], 'fitted.jpg', { type: 'image/jpeg' })
      const token = rememberLocalImage(file)
      setParams({ image_guide: token })
      setParam('resolution', target)
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[140] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-[420px] max-w-[94vw] rounded-2xl border border-border bg-bg-secondary p-4" onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">{t('imageFit.title')}</h3>
          <button type="button" onClick={onClose} className="p-1 text-text-muted" aria-label={t('imageFit.close')}>
            <X size={16} />
          </button>
        </div>
        <p className="mt-1 text-[11px] text-text-muted">{t('imageFit.hint')}</p>
        <label className="mt-3 block text-[11px] text-text-muted">
          {t('imageFit.target')}
          <select
            className="mt-1 w-full rounded border border-border bg-bg-tertiary px-2 py-1.5 text-xs"
            value={target}
            onChange={event => setTarget(event.target.value)}
          >
            {canvases.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <div className="mt-2 flex gap-1">
          {(['contain', 'cover', 'stretch'] as const).map(item => (
            <button
              key={item}
              type="button"
              onClick={() => setMode(item)}
              className={`flex-1 rounded-lg border px-2 py-1 text-[10px] ${
                mode === item ? 'border-accent-blue text-text-primary' : 'border-border text-text-muted'
              }`}
            >
              {t(`imageFit.${item}`)}
            </button>
          ))}
        </div>
        {preview ? (
          <img src={preview} alt="" className="mt-3 max-h-48 w-full rounded-lg object-contain bg-black" />
        ) : null}
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-xs text-text-muted">{t('imageFit.cancel')}</button>
          <button type="button" disabled={busy} onClick={() => void apply()} className="rounded-lg bg-accent-blue px-3 py-1.5 text-xs text-white disabled:opacity-50">
            {t('imageFit.apply')}
          </button>
        </div>
      </div>
    </div>
  )
}
