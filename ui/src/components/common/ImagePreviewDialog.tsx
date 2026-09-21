import { useEffect, useState } from 'react'
import { Download, X } from 'lucide-react'
import { fetchOutputMetadata } from '../../api/outputs'
import type { OutputMetadata } from '../../types'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import { ModalShell } from './ModalShell'
import type { PreviewImage } from './ImagePreview'

function metadataTarget(image: PreviewImage): { name: string; workspace?: string } | null {
  const url = new URL(image.url, window.location.href)
  if (url.origin !== window.location.origin) return null
  if (url.pathname.startsWith('/api/v1/uploads/')) {
    return { name: decodeURIComponent(url.pathname.slice('/api/v1/uploads/'.length)), workspace: '__uploads__' }
  }
  if (!url.pathname.startsWith('/api/v1/file/')) return null
  return { name: decodeURIComponent(url.pathname.slice('/api/v1/file/'.length)),
    workspace: url.searchParams.get('workspace') || image.workspace_id }
}

function ImageMetadata({ metadata }: { metadata: OutputMetadata }) {
  const { t } = useUiTranslation('common')
  const params = metadata.params || {}
  const summary = ['model_type', 'resolution', 'seed', 'num_inference_steps', 'guidance_scale'] as const
  return <>
    <dl className="space-y-2 text-xs">
      {summary.map(key => params[key] != null && <div key={key}>
        <dt className="text-text-muted">{t(`imagePreview.fields.${key}`)}</dt>
        <dd className="break-words">{String(params[key])}</dd>
      </div>)}
      {typeof params.prompt === 'string' && <div><dt className="text-text-muted">Prompt</dt><dd className="whitespace-pre-wrap break-words">{params.prompt}</dd></div>}
    </dl>
    <details className="mt-4 text-xs"><summary className="cursor-pointer">{t('imagePreview.allInfo')}</summary>
      <pre className="mt-2 whitespace-pre-wrap break-all text-[10px] text-text-secondary">{JSON.stringify(metadata, null, 2)}</pre>
    </details>
  </>
}

export default function ImagePreviewDialog({ image, onClose }: { image: PreviewImage; onClose: () => void }) {
  const { t } = useUiTranslation('common')
  const [dimensions, setDimensions] = useState('')
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const { name, url, workspace_id } = image
  const [info, setInfo] = useState<{ metadata?: OutputMetadata; failed?: boolean; done?: boolean }>({ done: metadataTarget(image) === null })
  useEffect(() => {
    const controller = new AbortController()
    const target = metadataTarget({ name, url, workspace_id })
    if (!target) return
    void fetchOutputMetadata(target.name, target.workspace, controller.signal)
      .then(metadata => { if (!controller.signal.aborted) setInfo({ metadata, done: true }) })
      .catch(() => { if (!controller.signal.aborted) setInfo({ failed: true, done: true }) })
    return () => controller.abort()
  }, [name, url, workspace_id]) // Descriptor objects may change with progress renders.
  const src = attempt && !image.url.startsWith('blob:')
    ? `${image.url}${image.url.includes('?') ? '&' : '?'}preview_retry=${attempt}` : image.url
  return <ModalShell open title={t('imagePreview.title')} onClose={onClose}
    className="fixed inset-0 z-[150] flex items-center justify-center bg-black/85 p-3 sm:p-6"
    onMouseDown={event => { event.stopPropagation(); if (event.target === event.currentTarget) onClose() }}>
    <section className="flex max-h-[94dvh] w-full max-w-[1600px] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary text-text-primary">
      <header className="flex items-center gap-3 border-b border-border p-3">
        <h2 className="min-w-0 flex-1 truncate text-sm" title={image.name}>{image.name}</h2>
        <a href={image.url} download={image.name} className="p-2" aria-label={t('imagePreview.download')}><Download size={18} /></a>
        <button type="button" className="p-2" onClick={onClose} aria-label={t('actions.close')}><X size={20} /></button>
      </header>
      <div className="flex min-h-0 flex-col overflow-y-auto md:flex-row">
        <div className="flex min-h-48 min-w-0 flex-1 items-center justify-center overflow-auto bg-black/30 p-2">
          {failed ? <div role="alert" className="p-6 text-sm">{t('imagePreview.failed')}
            <button type="button" className="ml-3 underline" onClick={() => { setFailed(false); setAttempt(Date.now()) }}>{t('actions.retry')}</button>
          </div> : <img src={src} alt={image.name} className="max-h-[75dvh] max-w-full object-contain"
            onError={() => setFailed(true)} onLoad={event => setDimensions(`${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`)} />}
        </div>
        <aside className="shrink-0 space-y-3 overflow-y-auto p-4 md:w-80">
          <p className="text-sm">{dimensions}</p>
          {Boolean(image.size) && <p className="text-xs text-text-muted">{(image.size! / 1024 / 1024).toFixed(2)} MB</p>}
          {Boolean(image.created_at) && <p className="text-xs text-text-muted">{formatAppTimestamp(image.created_at)}</p>}
          {!info.done && <p role="status">{t('imagePreview.loading')}</p>}
          {info.failed && <p role="alert">{t('imagePreview.infoFailed')}</p>}
          {info.metadata ? <ImageMetadata metadata={info.metadata} /> : info.done && !info.failed && <p className="text-xs text-text-muted">{t('imagePreview.noInfo')}</p>}
        </aside>
      </div>
    </section>
  </ModalShell>
}
