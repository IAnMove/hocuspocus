import { useUiTranslation } from '../../../i18n'
import type { CharacterKitLibrary } from '../../../lib/characterKit'
import type { SeriesProject, SeriesShot } from '../types'
import { planBackground, planCast, type TakeEntry } from './model'

/** A shot without a take, sketched from its plan: the location's picture with the cast standing where the plan puts it. */
export function PlanSketch({ series, shot, kits, className = '' }: { series: SeriesProject; shot: SeriesShot; kits: CharacterKitLibrary | null; className?: string }) {
  const background = planBackground(series, shot)
  const cast = shot.productionMethod === 'animation_2d' ? planCast(series, shot, kits) : []
  const framing = shot.layout2d?.framing || shot.framing
  const height = framing === 'close' ? 140 : framing === 'medium' ? 110 : 80
  return <div className={`relative overflow-hidden bg-black/70 ${className}`}>
    {background && <img src={background.url} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover opacity-90" />}
    {cast.map((figure, index) => figure.src && <img key={`${figure.characterId}-${index}`} src={figure.src} alt={figure.name} loading="lazy"
      className="absolute bottom-0 max-w-none -translate-x-1/2 object-contain drop-shadow"
      style={{ left: `${figure.x}%`, height: `${Math.min(160, height * figure.scale)}%` }} />)}
  </div>
}

/** The shot's picture on top of the inspector: the chosen take playing (with its scrub bar), the other takes to switch
 * to, or the plan sketched when nothing is rendered yet. */
export function InspectorMedia({ series, shot, takes, selected, onSelect, kits }: {
  series: SeriesProject; shot: SeriesShot; takes: TakeEntry[]; selected?: string; onSelect: (attemptId: string) => void
  kits: CharacterKitLibrary | null
}) {
  const { t } = useUiTranslation('seriesLab')
  const take = takes.find(item => item.attempt.id === selected) || takes[0]
  const frame = 'aspect-video w-full overflow-hidden rounded-xl bg-black'
  // Never taller than about half the screen, so the shot's parts start right under it.
  return <div className="mx-auto w-full space-y-2" style={{ maxWidth: 'min(100%, calc(50vh * 16 / 9))' }}>
    {take
      ? <video key={take.url} className={`${frame} object-contain`} src={take.url} poster={take.thumbnail} controls playsInline preload="metadata"
        aria-label={t('inspector.media.take', { number: take.number })} />
      : <div className="relative"><PlanSketch series={series} shot={shot} kits={kits} className={frame} />
        <span className="absolute left-2 top-2 rounded-full bg-black/70 px-2 py-0.5 text-[10px] text-white">{t('inspector.media.planOnly')}</span></div>}
    {takes.length > 1 && <div role="radiogroup" aria-label={t('inspector.media.takes')} className="flex gap-1.5 overflow-x-auto pb-1">
      {takes.map(item => {
        const approved = item.attempt.id === shot.approvedAttemptId
        return <button key={item.attempt.id} type="button" role="radio" aria-checked={item.attempt.id === take?.attempt.id}
          className={`min-h-10 shrink-0 rounded-lg border px-2.5 text-[11px] sm:min-h-8 ${item.attempt.id === take?.attempt.id ? 'border-violet-400 bg-violet-500/20 text-violet-100' : 'border-border text-text-secondary'}`}
          onClick={() => onSelect(item.attempt.id)}>
          {t('inspector.takes.take', { number: item.number })}{approved ? ' ✓' : ''}{item.attempt.reviewStage === 'preview' ? ` · ${t('approval.stage.preview')}` : ''}
        </button>
      })}
    </div>}
  </div>
}
