import { ExternalLink } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import type { MusicProductionPublication } from './types'

type Publisher = 'user' | 'agent' | 'wizard'
const PUBLISHERS: readonly string[] = ['user', 'agent', 'wizard'] satisfies Publisher[]

/** The production's newest published page (`production.publish`), opened in a new tab: a release or a review preview,
 *  when it was published and by whom. */
export function PublishedPageLink({ publication }: { publication: MusicProductionPublication }) {
  const { t } = useUiTranslation('navigation')
  if (!/^https?:\/\//i.test(publication.page)) return null
  const preview = publication.mode === 'preview'
  const by = (PUBLISHERS.includes(publication.published_by ?? '') ? publication.published_by : 'user') as Publisher
  const when = formatAppTimestamp(publication.published_at)
  return <span className="flex flex-wrap items-center gap-2 text-[11px]" data-testid="music-production-publication" data-mode={publication.mode}>
    <a href={publication.page} target="_blank" rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-text-primary hover:bg-bg-hover">
      <ExternalLink size={12} />{t(preview ? 'musicProductions.publication.preview' : 'musicProductions.publication.release')}
    </a>
    <span className="text-text-muted">
      {t(`musicProductions.publication.by.${by}`)}{when ? ` · ${when}` : ''}
      {(publication.count ?? 1) > 1 ? ` · ${t('musicProductions.publication.count', { count: publication.count })}` : ''}
    </span>
  </span>
}
