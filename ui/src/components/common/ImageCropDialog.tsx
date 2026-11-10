import { controlReason } from '../../i18n/controlLabel'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { ModalShell } from './ModalShell'
import ImageTransformBar, { type TransformedView } from './ImageTransformBar'
import { useUiTranslation } from '../../i18n'
import { loadFitImage } from '../../lib/imageFit'
import { clampCrop, cropFromPoints, cropImageFile, type CropRect } from '../../lib/imageCrop'

export default function ImageCropDialog({ source, name, onSave, onClose }: {
  source: string; name: string; onSave: (file: File) => Promise<void>; onClose: () => void
}) {
  const { t } = useUiTranslation('common')
  const [image, setImage] = useState<HTMLImageElement | null>(null)
  const [rect, setRect] = useState<CropRect>({ x: 0, y: 0, width: 1, height: 1 })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const active = useRef(false), saving = useRef(false)
  const drag = useRef<{ x: number; y: number } | null>(null)
  // What is on screen: the source, or the picture after the rotate and flip buttons (a temporary address, revoked when replaced).
  const [shown, setShown] = useState(source)
  const original = useRef<HTMLImageElement | null>(null), owned = useRef('')
  useEffect(() => () => { if (owned.current) URL.revokeObjectURL(owned.current) }, [])
  useEffect(() => {
    active.current = true
    void loadFitImage(source).then(loaded => {
      if (!active.current) return
      original.current = loaded
      setShown(source)
      setImage(loaded)
      setRect({ x: 0, y: 0, width: loaded.naturalWidth, height: loaded.naturalHeight })
    }).catch(() => { if (active.current) setError(t('crop.loadFailed')) })
    return () => { active.current = false }
  }, [source, t])
  const close = () => { if (!saving.current) onClose() }
  const showTransformed = (view: TransformedView) => {
    if (!active.current) { URL.revokeObjectURL(view.url); return }
    const previous = owned.current
    owned.current = view.url
    setShown(view.url); setImage(view.image); setRect(view.rect); setError('')
    if (previous) URL.revokeObjectURL(previous)
  }
  const restore = () => {
    if (!original.current) return
    const previous = owned.current
    owned.current = ''
    setShown(source); setImage(original.current); setError('')
    setRect({ x: 0, y: 0, width: original.current.naturalWidth, height: original.current.naturalHeight })
    if (previous) URL.revokeObjectURL(previous)
  }
  const point = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return { x: (event.clientX - bounds.left) / bounds.width * image!.naturalWidth,
      y: (event.clientY - bounds.top) / bounds.height * image!.naturalHeight }
  }
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current && image) setRect(cropFromPoints(drag.current, point(event), image.naturalWidth, image.naturalHeight))
  }
  const save = async () => {
    if (!image || saving.current) return
    saving.current = true; setBusy(true); setError('')
    try {
      const file = await cropImageFile(image, rect, name)
      if (!active.current) return
      await onSave(file)
      if (active.current) onClose()
    } catch { if (active.current) setError(t('crop.saveFailed')) }
    finally { saving.current = false; if (active.current) setBusy(false) }
  }
  return <ModalShell open title={t('crop.title')} onClose={close} className="fixed inset-0 z-[160] flex items-center justify-center bg-black/80 p-2 sm:p-4">
    <div className="max-h-full w-full max-w-3xl overflow-y-auto rounded-xl bg-bg-secondary p-4 space-y-3">
      <h2 className="text-sm font-semibold">{t('crop.title')} · {name}</h2>
      <p className="text-xs text-text-muted">{t('crop.hint')}</p>
      {image ? <>
        <div className="mx-auto w-fit max-w-full overflow-hidden bg-black">
          <div data-testid="crop-surface" className="relative touch-none select-none" style={{ pointerEvents: busy ? 'none' : 'auto' }}
            onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = point(event) }}
            onPointerMove={move} onPointerUp={event => { move(event); drag.current = null }} onPointerCancel={() => { drag.current = null }}>
            <img src={shown} alt={name} draggable={false} className="block max-h-[50dvh] max-w-full object-contain" />
            <div className="pointer-events-none absolute border-2 border-white bg-transparent" style={{
              left: `${rect.x / image.naturalWidth * 100}%`, top: `${rect.y / image.naturalHeight * 100}%`,
              width: `${rect.width / image.naturalWidth * 100}%`, height: `${rect.height / image.naturalHeight * 100}%`,
              boxShadow: '0 0 0 9999px rgba(0,0,0,.55)',
            }} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ImageTransformBar image={image} rect={rect} busy={busy} onResult={showTransformed} onError={() => setError(t('crop.transformFailed'))} />
          {shown !== source && <button type="button" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} className="text-xs underline" onClick={restore}>{t('crop.restore')}</button>}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(['x', 'y', 'width', 'height'] as const).map(field => <label key={field} className="text-xs">{t(`crop.${field}`)}
            <input aria-label={t(`crop.${field}`)} type="number" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} min={field === 'x' || field === 'y' ? 0 : 1} value={rect[field]}
              onChange={event => setRect(clampCrop({ ...rect, [field]: Number(event.target.value) }, image.naturalWidth, image.naturalHeight))}
              className="block w-full rounded border border-border bg-bg-tertiary p-2" />
          </label>)}
        </div>
        <button type="button" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} className="text-xs underline" onClick={() => setRect({ x: 0, y: 0, width: image.naturalWidth, height: image.naturalHeight })}>{t('crop.reset')}</button>
      </> : <p role="status">{error || t('status.loading')}</p>}
      {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={close} className="rounded border border-border px-3 py-2 text-xs">{t('actions.cancel')}</button>
        <button type="button" disabled={busy || !image} onClick={() => void save()} className="rounded bg-accent-blue px-3 py-2 text-xs text-white disabled:opacity-50">{busy ? t('crop.saving') : t('crop.save')}</button>
      </div>
    </div>
  </ModalShell>
}
