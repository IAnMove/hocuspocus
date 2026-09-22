import { useEffect, useState } from 'react'
import { Download, X } from 'lucide-react'
import { fetchOutputMetadata } from '../../api/outputs'
import { useUiTranslation } from '../../i18n'
import { formatGenerationDuration } from '../../lib/generationTiming'
import { ModalShell } from './ModalShell'
import type { PreviewImage } from './ImagePreview'
import { ImagePreviewInformation, type PreviewMetadataState } from './ImagePreviewMetadata'

function metadataTarget(image: PreviewImage): { name: string; workspace?: string } | null {
  try {
    const url = new URL(image.url, window.location.href)
    if (url.origin !== window.location.origin) return null
    if (url.pathname.startsWith('/api/v1/uploads/')) {
      return { name: decodeURIComponent(url.pathname.slice('/api/v1/uploads/'.length)), workspace: '__uploads__' }
    }
    if (!url.pathname.startsWith('/api/v1/file/')) return null
    return { name: decodeURIComponent(url.pathname.slice('/api/v1/file/'.length)),
      workspace: url.searchParams.get('workspace') || image.workspace_id }
  } catch {
    return null
  }
}

export default function ImagePreviewDialog({ image, onClose, videoTime, onVideoTimeChange }: {
  image: PreviewImage
  onClose: () => void
  videoTime?: number
  onVideoTimeChange?: (seconds: number) => void
}) {
  const { t } = useUiTranslation('common')
  const [dimensions, setDimensions] = useState('')
  const [duration, setDuration] = useState('')
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [metadataAttempt, setMetadataAttempt] = useState(0)
  const { name, url, workspace_id } = image
  const isVideo = image.type === 'video'
  const [info, setInfo] = useState<PreviewMetadataState>({ done: metadataTarget(image) === null })
  useEffect(() => {
    const controller = new AbortController()
    const target = metadataTarget({ name, url, workspace_id })
    if (!target) return
    void fetchOutputMetadata(target.name, target.workspace, controller.signal)
      .then(metadata => { if (!controller.signal.aborted) setInfo({ metadata, done: true }) })
      .catch(() => { if (!controller.signal.aborted) setInfo({ failed: true, done: true }) })
    return () => controller.abort()
  }, [name, url, workspace_id, metadataAttempt]) // Descriptor objects may change with progress renders.
  let src = image.url
  if (attempt && !/^(blob:|data:)/i.test(src)) {
    const retryUrl = new URL(src, window.location.href)
    retryUrl.searchParams.set('preview_retry', String(attempt))
    src = retryUrl.href
  }
  const actionClass = 'flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg hover:bg-bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent'
  return <ModalShell open title={t(isVideo ? 'imagePreview.videoTitle' : 'imagePreview.title')} onClose={onClose}
    className="fixed inset-0 z-[150] flex items-center justify-center overflow-hidden bg-black/85 p-2 sm:p-6"
    onMouseDown={event => { event.stopPropagation(); if (event.target === event.currentTarget) onClose() }}>
    <section className="flex max-h-[calc(100dvh-1rem)] min-w-0 w-full max-w-[1600px] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary text-text-primary sm:max-h-[calc(100dvh-3rem)]">
      <header className="flex shrink-0 items-center gap-2 border-b border-border p-2 sm:p-3">
        <h2 className="min-w-0 flex-1 truncate pl-1 text-sm" title={image.name}>{image.name}</h2>
        <a href={image.url} download={image.name} className={actionClass} aria-label={t(isVideo ? 'imagePreview.downloadVideo' : 'imagePreview.download')}><Download size={18} /></a>
        <button type="button" className={actionClass} onClick={onClose} aria-label={t('actions.close')}><X size={20} /></button>
      </header>
      <div className="flex min-h-0 min-w-0 flex-col overflow-x-hidden overflow-y-auto overscroll-contain md:flex-row md:overflow-hidden">
        <div className="flex min-h-40 min-w-0 shrink-0 items-center justify-center bg-black/30 p-2 md:flex-1">
          {failed ? <div role="alert" className="p-4 text-sm">{t(isVideo ? 'imagePreview.videoFailed' : 'imagePreview.failed')}
            <button type="button" className="mt-2 block min-h-11 underline" onClick={() => { setFailed(false); setAttempt(value => value + 1) }}>{t('actions.retry')}</button>
          </div> : isVideo ? <video key={src} src={src} poster={image.thumbnail_url || undefined} controls playsInline preload="metadata" tabIndex={0}
            aria-label={image.name} className="block max-h-[55dvh] min-w-0 w-full object-contain md:max-h-[min(75dvh,calc(100dvh-9rem))]"
            onError={() => setFailed(true)} onLoadedMetadata={event => {
              const video = event.currentTarget
              if (video.videoWidth && video.videoHeight) setDimensions(`${video.videoWidth} × ${video.videoHeight}`)
              setDuration(formatGenerationDuration(video.duration))
              if (videoTime != null && videoTime > 0 && Number.isFinite(video.duration)) video.currentTime = Math.min(videoTime, Math.max(0, video.duration - 0.001))
            }} onTimeUpdate={event => {
              const time = event.currentTarget.currentTime
              if (Number.isFinite(time)) onVideoTimeChange?.(time)
            }} /> : <img src={src} alt={image.name} className="block max-h-[55dvh] max-w-full object-contain md:max-h-[min(75dvh,calc(100dvh-9rem))]"
            onError={() => setFailed(true)} onLoad={event => setDimensions(`${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`)} />}
        </div>
        <ImagePreviewInformation image={image} dimensions={dimensions} duration={duration} info={info}
          onRetry={() => { setInfo({}); setMetadataAttempt(value => value + 1) }} />
      </div>
    </section>
  </ModalShell>
}
