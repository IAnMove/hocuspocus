import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Maximize2, Trash2, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { StoryVisualAsset } from './types'

export function ReferenceGallery({
  ids, assets, primaryId, onPrimary, onRemove,
}: {
  ids: string[]
  assets: Record<string, StoryVisualAsset>
  primaryId?: string
  onPrimary?: (id: string) => void
  onRemove: (id: string) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const { t: tCommon } = useUiTranslation('common')
  const [previewId, setPreviewId] = useState<string | null>(null)
  const previewAsset = previewId ? assets[previewId] : undefined

  useEffect(() => {
    if (!previewAsset) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('keydown', closeOnEscape)
      document.body.style.overflow = previousOverflow
    }
  }, [previewAsset])

  const confirmRemove = (id: string, asset: StoryVisualAsset) => {
    const name = asset.name || t('gallery.untitled')
    if (!window.confirm(t('gallery.removeConfirm', { name }))) return
    onRemove(id)
  }

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
        {ids.map(id => {
          const asset = assets[id]
          if (!asset) return null
          const displayName = asset.name || t('gallery.untitled')
          return (
            <div key={id} className={`relative rounded-lg overflow-hidden border ${id === primaryId ? 'border-emerald-400' : 'border-border'} bg-bg-tertiary`}>
              <img src={asset.source} alt={asset.name} className="w-full aspect-square object-cover" />
              <span className={`absolute right-1 top-1 rounded border px-1 py-0.5 text-[8px] ${asset.approval === 'approved'
                ? 'border-emerald-400/70 bg-emerald-950/80 text-emerald-200'
                : 'border-amber-400/60 bg-amber-950/80 text-amber-200'}`}>
                {asset.approval === 'approved' ? t('status.approved') : t('status.draft')}
              </span>
              <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-black/65 p-1">
                {onPrimary && <button type="button" className="text-[9px] text-white" onClick={() => onPrimary(id)}>{id === primaryId ? t('gallery.primary') : t('gallery.useAsPrimary')}</button>}
                <button
                  type="button"
                  className="ml-auto rounded p-1 text-white hover:bg-white/15"
                  onClick={() => setPreviewId(id)}
                  title={t('gallery.enlarge')}
                  aria-label={t('gallery.enlargeNamed', { name: displayName })}
                >
                  <Maximize2 size={13} />
                </button>
                <button
                  type="button"
                  className="rounded p-1 text-red-300 hover:bg-red-500/20"
                  onClick={() => confirmRemove(id, asset)}
                  title={t('gallery.remove')}
                  aria-label={t('gallery.removeNamed', { name: displayName })}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          )
        })}
      </div>
      {previewAsset && createPortal(
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-black/85 p-4 md:p-8"
          onClick={() => setPreviewId(null)}
          role="presentation"
        >
          <div
            className="flex max-h-[94vh] max-w-[96vw] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
            onClick={event => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="story-image-preview-title"
          >
            <div className="flex items-center gap-3 border-b border-border px-3 py-2.5">
              <h2 id="story-image-preview-title" className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">
                {previewAsset.name || t('gallery.previewFallback')}
              </h2>
              <button
                type="button"
                onClick={() => setPreviewId(null)}
                className="rounded-lg p-1.5 text-text-muted hover:bg-bg-hover hover:text-text-primary"
                title={tCommon('actions.close')}
                aria-label={t('gallery.closePreview')}
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex min-h-0 items-center justify-center bg-black/35 p-2">
              <img
                src={previewAsset.source}
                alt={previewAsset.name || t('gallery.previewAlt')}
                className="max-h-[84vh] max-w-[92vw] object-contain"
              />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
