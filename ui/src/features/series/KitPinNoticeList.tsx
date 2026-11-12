import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import { kitPinNotices } from './kitPinNotice'
import type { SeriesEpisode, SeriesProject } from './types'

export function KitPinNoticeList({ series, episode, kits }: {
  series: SeriesProject
  episode: SeriesEpisode
  kits: CharacterKit[]
}) {
  const { t } = useUiTranslation('seriesLab')
  const notices = kitPinNotices(series, episode, kits)
  if (!notices.length) return null
  return <div className="mb-3 space-y-1">
    {notices.map(notice => (
      <p key={notice.kitId} className="text-xs text-amber-200">
        {t('episode.kitPinBehind', { name: notice.name, pinned: notice.pinned, latest: notice.latest })}
      </p>
    ))}
  </div>
}
