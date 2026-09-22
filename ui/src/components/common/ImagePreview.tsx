import { lazy, Suspense, useState, type ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'
import { useObjectUrl } from '../../lib/useObjectUrl'

const ImagePreviewDialog = lazy(() => import('./ImagePreviewDialog'))

export interface PreviewImage {
  name: string
  url: string
  size?: number
  created_at?: number
  workspace_id?: string
  type?: 'image' | 'video'
  thumbnail_url?: string | null
}

export function ImagePreview({ image, children, className, onOpen, videoTime, onVideoTimeChange }: {
  image: PreviewImage
  children: ReactNode
  className?: string
  onOpen?: () => void
  videoTime?: number
  onVideoTimeChange?: (seconds: number) => void
}) {
  const { t } = useUiTranslation('common')
  const [open, setOpen] = useState(false)
  return <>
    <button type="button" className={className} aria-label={t(image.type === 'video' ? 'imagePreview.openVideo' : 'imagePreview.open', { name: image.name })}
      onClick={event => { event.stopPropagation(); onOpen?.(); setOpen(true) }}>{children}</button>
    {open && <Suspense fallback={<div role="status" className="fixed right-4 top-4 z-[150] rounded bg-bg-secondary p-3">{t('imagePreview.loading')}</div>}>
      <ImagePreviewDialog key={`${image.url}:${image.workspace_id || ''}:${image.type || 'image'}`} image={image} onClose={() => setOpen(false)}
        videoTime={videoTime} onVideoTimeChange={onVideoTimeChange} />
    </Suspense>}
  </>
}

export function LocalImagePreview({ file, label, className }: { file: File; label: string; className?: string }) {
  const url = useObjectUrl(file)
  if (!url) return null
  return <ImagePreview image={{ name: file.name, url, size: file.size }} className={className}>
    <img src={url} alt={label} className="h-full w-full object-contain" />
  </ImagePreview>
}
