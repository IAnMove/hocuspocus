import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { ApiOutput } from '../../api/outputs'
import { useUiTranslation } from '../../i18n'
import { localEditPreview } from '../../lib/localEditImages'
import { saveCroppedImage } from '../../lib/imageCrop'

const ImageCropDialog = lazy(() => import('./ImageCropDialog'))

/** Key by input identity/scope at the caller so a late save cannot replace a new selection. */
export function ImageCropButton({ item, disabled, onReplace }: {
  item: ApiOutput; disabled?: boolean; onReplace: (item: ApiOutput, file: File) => void
}) {
  const { t } = useUiTranslation('common')
  const [open, setOpen] = useState(false)
  const active = useRef(false)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  return <>
    <button type="button" disabled={disabled} aria-label={t('crop.editName', { name: item.name })} onClick={() => setOpen(true)} className="rounded border border-border bg-bg-secondary px-2 py-1 text-xs disabled:opacity-40">{t('actions.edit')}</button>
    {open && <Suspense fallback={<p role="status">{t('status.loading')}</p>}>
      <ImageCropDialog source={localEditPreview(item.url)} name={item.name} onClose={() => setOpen(false)} onSave={async file => {
        const saved = await saveCroppedImage(file)
        if (active.current) onReplace(saved, file)
      }} />
    </Suspense>}
  </>
}
