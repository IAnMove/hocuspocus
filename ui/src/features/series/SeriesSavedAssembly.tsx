import { Download, Play } from 'lucide-react'
import { getFileUrl } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { SectionCard } from './components'
import { greenButton, secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

export function SeriesSavedAssembly({ workspace, series, episode }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode
}) {
  const { t } = useUiTranslation('seriesLab')
  const asset = episode.latestAssemblyAssetId ? series.assets[episode.latestAssemblyAssetId] : undefined
  if (!asset || asset.kind !== 'video' || !asset.uri || asset.ownerType !== 'episode' || asset.ownerId !== episode.id) return null
  const url = getFileUrl(asset.uri.replace(/^outputs\//, ''), asset.workspaceId || workspace)
  const thumbnail = episode.thumbnailAssetId ? series.assets[episode.thumbnailAssetId] : undefined
  return <SectionCard title={t('review.savedAssembly')} description={episode.title}>
    {thumbnail?.uri && <img className="mb-2 w-full max-w-sm rounded-lg border border-border" alt={episode.title} loading="lazy"
      src={getFileUrl(thumbnail.uri.replace(/^outputs\//, ''), thumbnail.workspaceId || workspace)} />}
    <div className="flex flex-wrap gap-2">
      <a className={greenButton} href={url} target="_blank" rel="noreferrer"><Play size={14} />{t('review.openJoined')}</a>
      <a className={secondaryButton} href={url} download><Download size={14} />{t('review.downloadJoined')}</a>
    </div>
  </SectionCard>
}
