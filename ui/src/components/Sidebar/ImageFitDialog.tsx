import { useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { forgetLocalImage, localEditPreview, rememberLocalImage } from '../../lib/localEditImages'
import { useStore } from '../../stores/useStore'

import { fitFile, loadFitImage, paintFit, type FitMode } from '../../lib/imageFit'

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

export function ImageFitDialog({
  source,
  onClose,
}: {
  source: string
  onClose: () => void
}) {
  const { t } = useUiTranslation('studio')
  const setParams = useStore(s => s.setParams)
  const canvases = useMemo(() => modelCanvases(), [])
  const current = String(useStore.getState().params.resolution || canvases[0])
  const [target, setTarget] = useState(canvases.includes(current) ? current : canvases[0])
  const [mode, setMode] = useState<FitMode>('contain')
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef(false)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const src = localEditPreview(source)

  useEffect(() => {
    let cancelled = false
    void loadFitImage(src).then(image => {
      const [width, height] = target.split('x').map(Number)
      if (!cancelled) setPreview(paintFit(image, width, height, mode).toDataURL('image/png'))
    }).catch(() => { if (!cancelled) setError(t('imageFit.failed')) })
    return () => { cancelled = true }
  }, [src, target, mode, t])

  const apply = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    const initial = useStore.getState()
    const maskSource = String(initial.params.image_mask || '')
    try {
      const [image, mask] = await Promise.all([
        loadFitImage(src), maskSource ? loadFitImage(localEditPreview(maskSource)) : null,
      ])
      const [width, height] = target.split('x').map(Number)
      const [file, maskFile] = await Promise.all([
        fitFile(paintFit(image, width, height, mode), 'fitted.png'),
        mask ? fitFile(paintFit(mask, width, height, mode, image, true), 'fitted-mask.png') : null,
      ])
      const state = useStore.getState()
      if (!active.current || state.imageStudioIntent !== 'edit'
        || state.params.image_guide !== source || String(state.params.image_mask || '') !== maskSource
        || state.params.model_type !== initial.params.model_type) return
      const token = rememberLocalImage(file)
      const maskToken = maskFile ? rememberLocalImage(maskFile) : undefined
      setParams({ image_guide: token, image_mask: maskToken, resolution: target })
      useStore.setState({ imageSourceSize: { source: token, width, height } })
      forgetLocalImage(source)
      forgetLocalImage(maskSource)
      onClose()
    } catch {
      if (active.current) setError(t('imageFit.failed'))
    } finally {
      pending.current = false
      if (active.current) setBusy(false)
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
        {error ? <p role="alert" className="mt-2 text-xs text-red-400">{error}</p> : null}
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
