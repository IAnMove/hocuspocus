import { ChevronRight, Film } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { CharacterKitLibrary } from '../../../lib/characterKit'
import { primaryButton } from '../styles'
import { ReviewPills, StageButtons, type ApprovalCardActions } from '../SeriesApprovalCard'
import { latestTakeMedia, reviewStage, shotDressing, shotLines } from '../reviewModel'
import type { SeriesProductionMode, SeriesProject, SeriesShot, SeriesShotReview } from '../types'
import { PlanSketch } from './InspectorMedia'

const METHOD_SHORT: Record<string, string> = { animation_2d: '2D', animation_3d: '3D', generated_video: 'H3', imported_video: 'clip' }

/** What dresses the shot (effects, sounds, props, set layers, card, music, 3D scene), in one short line. */
function ShotDressing({ shot }: { shot: SeriesShot }) {
  const { t } = useUiTranslation('seriesLab')
  const items = shotDressing(shot).map(item => t(`approval.card.${item.key}`, item.values))
  return items.length ? <p className="truncate text-[10px] text-text-muted" title={items.join(' · ')}>{items.join(' · ')}</p> : null
}

/** One shot in the Validation grid: its picture (latest take, else its plan), number, length, method and review state,
 * a quick approve and a clear Open. */
export function SeriesShotTile({ series, shot, entry, mode, kits, unsaved, actions, onOpen }: {
  series: SeriesProject; shot: SeriesShot; entry: SeriesShotReview; mode: SeriesProductionMode; kits: CharacterKitLibrary | null
  unsaved: number; actions: ApprovalCardActions; onOpen: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const media = latestTakeMedia(series, shot)
  const stage = reviewStage(mode, entry, shot)
  const status = entry[stage]
  const line = shotLines(series, shot)[0]
  const border = status === 'changes' ? 'border-amber-500/50' : status === 'approved' ? 'border-green-500/40' : 'border-border'
  return <article id={`series-approval-${shot.id}`} data-testid={`series-approval-${shot.id}`}
    className={`flex min-w-0 scroll-mt-16 flex-col overflow-hidden rounded-xl border bg-bg-primary ${border}`}>
    <button type="button" className="relative block aspect-video w-full overflow-hidden bg-black/70 text-left" onClick={onOpen}
      aria-label={t('inspector.tile.open', { order: shot.order })}>
      {media ? <img src={media.thumbnail} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
        : <PlanSketch series={series} shot={shot} kits={kits} className="absolute inset-0 opacity-80" />}
      <span className="absolute left-1 top-1 rounded bg-black/75 px-1.5 py-0.5 text-[11px] font-semibold text-white">#{shot.order}</span>
      <span className="absolute right-1 top-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-white">{METHOD_SHORT[shot.productionMethod || 'generated_video']}</span>
      <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-white">{t('approval.card.seconds', { seconds: Number(shot.durationSeconds.toFixed(1)) })}</span>
      {!media && <span className="absolute bottom-1 left-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-amber-200">{t('inspector.tile.noTake')}</span>}
      {media && shot.attempts.filter(item => item.status === 'completed').length > 1 && <span className="absolute bottom-1 left-1 inline-flex items-center gap-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-white">
        <Film size={10} />{shot.attempts.filter(item => item.status === 'completed').length}</span>}
      {unsaved > 0 && <span className="absolute left-1 top-7 rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-semibold text-black">{t('inspector.tile.unsaved')}</span>}
    </button>
    <div className="flex flex-1 flex-col gap-1.5 p-2">
      <p className="line-clamp-2 min-h-8 text-[11px] text-text-secondary">{line
        ? <><span className="font-semibold text-text-primary">{line.speaker}:</span> {line.text}</>
        : <span className="text-text-muted">{shot.action || t('approval.card.noLines')}</span>}</p>
      <ShotDressing shot={shot} />
      <div className="flex flex-wrap gap-1"><ReviewPills entry={entry} mode={mode} hasTake={Boolean(media)} quiet /></div>
      <div className="mt-auto flex flex-wrap gap-1.5">
        <StageButtons shot={shot} stage={stage} status={status} canApprove={stage === 'plan' || Boolean(media)} actions={actions} compact />
        <button type="button" className={`${primaryButton} min-h-10 flex-1 sm:min-h-0`} onClick={onOpen}>{t('inspector.tile.openButton')}<ChevronRight size={13} /></button>
      </div>
    </div>
  </article>
}
