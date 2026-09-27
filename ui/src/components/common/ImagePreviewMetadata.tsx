import type { ReactNode } from 'react'
import type { OutputMetadata } from '../../types'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import { formatGenerationDuration } from '../../lib/generationTiming'
import { formatBytes } from '../../lib/format'
import type { PreviewImage } from './ImagePreview'

export interface PreviewMetadataState {
  metadata?: OutputMetadata
  failed?: boolean
  done?: boolean
}

function InfoField({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0">
    <dt className="mb-1 text-text-muted">{label}</dt>
    <dd className="whitespace-pre-wrap [overflow-wrap:anywhere]">{children}</dd>
  </div>
}

function ImageMetadata({ metadata }: { metadata: OutputMetadata }) {
  const { t } = useUiTranslation('common')
  const params = metadata.params || {}
  const summary = ['model_type', 'resolution', 'seed', 'num_inference_steps', 'guidance_scale'] as const
  const provenance = ['job_id', 'task_id', 'root_task_id', 'director_pipeline_id'] as const
  const generationTime = formatGenerationDuration(metadata.generation_timings?.total_time_sec ?? metadata.generation_time)
  return <>
    <dl className="grid min-w-0 grid-cols-2 gap-3 text-xs">
      {summary.map(key => params[key] != null && <InfoField key={key} label={t(`imagePreview.fields.${key}`)}>
        {typeof params[key] === 'object' ? JSON.stringify(params[key]) : String(params[key])}
      </InfoField>)}
      {generationTime && <InfoField label={t('imagePreview.fields.generation_time')}>{generationTime}</InfoField>}
    </dl>
    <dl className="min-w-0 space-y-4 text-sm">
      {(['prompt', 'negative_prompt'] as const).map(key => typeof params[key] === 'string' && params[key] !== '' &&
        <InfoField key={key} label={t(`imagePreview.fields.${key}`)}>{params[key]}</InfoField>)}
    </dl>
    <dl className="min-w-0 space-y-3 border-t border-border pt-4 text-xs">
      {metadata.source !== 'none' && <InfoField label={t('imagePreview.fields.source')}>{t(`imagePreview.sources.${metadata.source}`)}</InfoField>}
      {provenance.map(key => metadata[key] && <InfoField key={key} label={t(`imagePreview.fields.${key}`)}>{metadata[key]}</InfoField>)}
    </dl>
    <details className="min-w-0 text-xs">
      <summary tabIndex={0} className="flex min-h-11 cursor-pointer items-center rounded px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{t('imagePreview.allInfo')}</summary>
      <pre className="mt-2 max-w-full whitespace-pre-wrap [overflow-wrap:anywhere] text-[11px] text-text-secondary">{JSON.stringify(metadata, null, 2)}</pre>
    </details>
  </>
}

function FileProperties({ image, dimensions, duration, metadata }: {
  image: PreviewImage
  dimensions: string
  duration: string
  metadata?: OutputMetadata
}) {
  const { t } = useUiTranslation('common')
  const createdAt = image.created_at ?? metadata?.created_at
  return <dl className="grid min-w-0 grid-cols-2 gap-3 text-xs">
    {dimensions && <InfoField label={t('imagePreview.fields.dimensions')}>{dimensions}</InfoField>}
    {duration && <InfoField label={t('imagePreview.fields.duration')}>{duration}</InfoField>}
    {image.size != null && <InfoField label={t('imagePreview.fields.size')}>{formatBytes(image.size)}</InfoField>}
    {createdAt != null && <InfoField label={t('imagePreview.fields.created_at')}>{formatAppTimestamp(createdAt)}</InfoField>}
  </dl>
}

function hasSavedMetadata(metadata?: OutputMetadata): metadata is OutputMetadata {
  return Boolean(metadata && (metadata.source !== 'none' ||
    Object.keys(metadata.params || {}).length > 0 ||
    Object.entries(metadata).some(([key, value]) => !['source', 'params'].includes(key) && value != null)))
}

function MetadataStatus({ info, onRetry }: { info: PreviewMetadataState; onRetry: () => void }) {
  const { t } = useUiTranslation('common')
  if (!info.done) return <p role="status" className="text-sm">{t('imagePreview.loading')}</p>
  if (info.failed) return <div role="alert" className="text-sm">{t('imagePreview.infoFailed')}
    <button type="button" className="mt-2 block min-h-11 underline" onClick={onRetry}>{t('imagePreview.retryInfo')}</button>
  </div>
  if (hasSavedMetadata(info.metadata)) return <ImageMetadata metadata={info.metadata} />
  return <p className="text-xs text-text-muted">{t('imagePreview.noInfo')}</p>
}

export function ImagePreviewInformation({ image, dimensions, duration, info, onRetry }: {
  image: PreviewImage
  dimensions: string
  duration: string
  info: PreviewMetadataState
  onRetry: () => void
}) {
  const { t } = useUiTranslation('common')
  return <aside aria-label={t('imagePreview.information')} className="min-w-0 shrink-0 space-y-4 border-t border-border p-4 md:w-80 md:overflow-y-auto md:overscroll-contain md:border-t-0 md:border-l lg:w-96">
    <FileProperties image={image} dimensions={dimensions} duration={duration} metadata={info.metadata} />
    <MetadataStatus info={info} onRetry={onRetry} />
  </aside>
}
