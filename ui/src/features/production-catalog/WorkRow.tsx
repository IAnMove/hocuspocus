import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { previewUrl } from '../production-shots/preview'
import { LinkProject } from './LinkProject'
import { openLinkedProject } from './projectLink'
import { ReviewShotsButton } from './ReviewShotsButton'
import { linkedTarget } from './target'
import { FORMAT_KEYS, ORIGIN_KEYS, STATUS_KEYS, isFormat, isOrigin, isStatus, type CatalogWork } from './types'

export function WorkRow({ work, onLinked }: { work: CatalogWork, onLinked: () => void }) {
  const { t } = useTranslation('productionCatalog')
  const target = linkedTarget(work.project, work.series_id)
  const [missing, setMissing] = useState(false)
  const preview = previewUrl(work.preview, work.workspace_id)
  const format = work.format && isFormat(work.format) ? t(FORMAT_KEYS[work.format]) : work.format
  const status = isStatus(work.status) ? t(STATUS_KEYS[work.status]) : work.status
  const origin = isOrigin(work.origin) ? t(ORIGIN_KEYS[work.origin]) : work.origin
  return <article className="border-b border-border py-3 text-xs" data-production-id={work.production_id} data-workspace={work.workspace_id} data-origin={work.origin}>
    <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h3 className="text-sm text-text-primary">{work.title}</h3>
        <p className="text-text-muted">
          {origin}{format ? ` · ${format}` : ''} · {status}
          {work.updated_at ? ` · ${t('updated', { when: work.updated_at })}` : ` · ${t('updatedUnknown')}`}
        </p>
        <p>
          {work.project?.kind === 'story' && t('projectStory', { id: work.project.id })}
          {work.project?.kind === 'episode' && t('projectEpisode', { id: work.project.id })}
          {!work.project && t('unlinked')}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <ReviewShotsButton workspace={work.workspace_id} productionId={work.production_id} label={t('reviewShots')} />
        {target ? <button type="button" className="rounded border border-border px-2 py-1" data-open-project={target.id} data-project-kind={target.kind} onClick={() => {
          void openLinkedProject(work.workspace_id, target).then(result => { if (result === 'missing') setMissing(true) }, () => setMissing(true))
        }}>{t('openProject')}{missing ? ` — ${t('projectUnavailable')}` : ''}</button> : <span>{work.project ? t('projectUnavailable') : null}</span>}
      </div>
    </div>
    {preview ? <img src={preview} alt={t('previewAlt')} className="mt-2 h-16 w-28 rounded border border-border object-cover" /> : null}
    {!work.project ? <LinkProject workspace={work.workspace_id} productionId={work.production_id} onLinked={onLinked} /> : null}
  </article>
}
