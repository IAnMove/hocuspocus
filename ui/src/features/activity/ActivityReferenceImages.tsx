import { useState } from 'react'
import { ImageOff } from 'lucide-react'
import { ImagePreview } from '../../components/common/ImagePreview'
import { useUiTranslation } from '../../i18n'
import type { ActivityTaskLike } from './lineage'

function localMediaUrl(value: unknown): value is string {
  return typeof value === 'string' && /^\/api\/v1\/(?:uploads|file|outputs\/thumbnail)\//.test(value)
}

function ReferenceThumbnail({ url, thumbnail, label }: { url: string; thumbnail: string; label: string }) {
  const [failed, setFailed] = useState(false)
  const [fallback, setFallback] = useState(false)
  if (failed) return <ImageOff size={18} aria-label={label} />
  return <img src={fallback ? url : thumbnail} alt={label} loading="lazy" decoding="async" className="h-full w-full object-contain"
    onError={() => { if (fallback || thumbnail === url) setFailed(true); else setFallback(true) }} />
}

export function ActivityReferenceImages({ task }: { task: ActivityTaskLike }) {
  const { t } = useUiTranslation('activity')
  const items = task.metadata?.reference_images
  if (!Array.isArray(items)) return null
  const references = items.filter((item): item is { url: string; name?: string; thumbnail_url?: string } =>
    Boolean(item && typeof item === 'object' && localMediaUrl(item.url))).slice(0, 10)
  if (!references.length) return null
  return <div aria-label={t('referenceImages')} className="mt-1.5 flex flex-wrap gap-1">
    {references.map((item, index) => <ImagePreview key={item.url}
      image={{ name: item.name || t('referenceImage', { n: index + 1 }), url: item.url }}
      className="flex h-12 w-12 items-center justify-center overflow-hidden rounded border border-border bg-bg-tertiary hover:border-accent-blue">
      <ReferenceThumbnail url={item.url} thumbnail={localMediaUrl(item.thumbnail_url) ? item.thumbnail_url : item.url} label={t('referenceImage', { n: index + 1 })} />
    </ImagePreview>)}
  </div>
}
