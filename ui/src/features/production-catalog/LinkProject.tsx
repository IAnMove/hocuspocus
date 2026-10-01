import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { linkWork } from './api'

export function LinkProject({
  workspace, productionId, onLinked,
}: {
  workspace: string
  productionId: string
  onLinked: () => void
}) {
  const { t } = useTranslation('productionCatalog')
  const [kind, setKind] = useState<'story' | 'episode'>('story')
  const [projectId, setProjectId] = useState('')
  const [failed, setFailed] = useState(false)
  return <form className="mt-2 flex flex-wrap items-center gap-2" data-link-project={productionId} onSubmit={event => {
    event.preventDefault()
    const id = projectId.trim()
    if (!id) return
    linkWork(workspace, productionId, { kind, id }).then(() => onLinked(), () => setFailed(true))
  }}>
    <span>{t('link.action')}</span>
    <label>
      {t('link.kind')}
      <select className="ml-1 rounded border border-border bg-bg-primary" value={kind} onChange={event => setKind(event.target.value === 'episode' ? 'episode' : 'story')}>
        <option value="story">{t('link.story')}</option>
        <option value="episode">{t('link.episode')}</option>
      </select>
    </label>
    <input aria-label={t('link.id')} value={projectId} onChange={event => setProjectId(event.target.value)} className="rounded border border-border bg-bg-primary px-1" />
    <button type="submit" className="rounded border border-border px-2 py-1">{t('link.submit')}</button>
    {failed ? <span>{t('link.failed')}</span> : null}
  </form>
}
