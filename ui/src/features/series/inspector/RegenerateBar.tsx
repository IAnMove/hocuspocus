import type { TFunction } from 'i18next'
import { Loader2, RotateCcw } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { SeriesServerRenderItem, SeriesServerRenderJob } from '../../../api/series'
import { primaryButton, secondaryButton } from '../styles'
import type { SeriesProject, SeriesShot } from '../types'
import { characterName } from './context'
import type { Regeneration } from './model'

const LIVE = new Set(['queued', 'running', 'cancelling'])

/** What re-rendering the shot regenerates, in words: the voices it records, the scene and take, the foley. */
function steps(t: TFunction<'seriesLab'>, series: SeriesProject, shot: SeriesShot, plan: Regeneration): string {
  const spoken = shot.dialogueBeats.some(beat => beat.text.trim())
  const voices = plan.record.length
    ? t('inspector.regenerate.record', { count: plan.record.length, lines: plan.record.map(line => `#${line.number} ${characterName(series, line.characterId)}`).join(', ') })
    : spoken ? t('inspector.regenerate.reuse') : ''
  const scene = t(shot.productionMethod === 'animation_3d' ? 'inspector.regenerate.scene3d' : 'inspector.regenerate.scene2d')
  return [voices, scene, plan.foley ? t('inspector.regenerate.withFoley') : ''].filter(Boolean).join(' · ')
}

/** Why the shot asks to be rendered: it changed after its take, a line is newer than it, or it has none yet. */
function reason(shot: SeriesShot, plan: Regeneration) {
  if (!shot.attempts.some(value => value.status === 'completed')) return 'inspector.regenerate.noTake' as const
  return plan.newer.length ? 'inspector.regenerate.newerVoices' as const : 'inspector.regenerate.stale' as const
}

/** The server render of this shot as it goes: its stage, or why it failed; another render of the episode blocks it. */
function RenderState({ item, live, mine }: { item?: SeriesServerRenderItem; live: boolean; mine: boolean }) {
  const { t } = useUiTranslation('seriesLab')
  if (mine && item) return <p role="status" className="mt-1 text-[11px] text-violet-200">{t('inspector.regenerate.progress', { stage: t(`inspector.regenerate.stages.${item.stage}`) })}</p>
  if (live) return <p className="mt-1 text-[10px] text-text-muted">{t('inspector.regenerate.busy')}</p>
  return item?.status === 'failed' ? <p role="alert" className="mt-1 text-[11px] text-red-300">{item.error}</p> : null
}

/** A generated or imported take: nothing renders, its sound is laid at the cut; only its foley is made by a render. */
function CutOnly({ foley, disabled, error, onRender }: { foley: boolean; disabled: boolean; error: string; onRender: () => void }) {
  const { t } = useUiTranslation('seriesLab')
  return <div className="rounded-xl border border-border bg-bg-secondary p-3 text-[11px] text-text-secondary">
    <p>{t('inspector.regenerate.cut')}</p>
    {foley && <button type="button" className={`${secondaryButton} mt-2 min-h-10 sm:min-h-0`} disabled={disabled} onClick={onRender}>
      <RotateCcw size={13} />{t('inspector.regenerate.foley')}</button>}
    {error && <p role="alert" className="mt-1 text-red-300">{error}</p>}
  </div>
}

/** This shot's item in the episode's server render, whether that render is running and whether it is this shot's turn. */
function renderOf(job: SeriesServerRenderJob | undefined, shotId: string) {
  const item = job?.items.find(value => value.shotId === shotId)
  const live = Boolean(job && LIVE.has(job.status))
  return { item, live, mine: live && Boolean(item) && !['done', 'failed'].includes(item!.status) }
}

/** The one call to action after an edit: re-render this shot, and what that regenerates (which voices, the scene, the take). */
export function RegenerateBar({ series, shot, plan, job, busy, error, onRender }: {
  series: SeriesProject; shot: SeriesShot; plan: Regeneration; job?: SeriesServerRenderJob; busy: boolean; error: string; onRender: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const { item, live, mine } = renderOf(job, shot.id)
  if (!plan.renders) return <CutOnly foley={plan.foley} disabled={live || busy} error={error} onRender={onRender} />
  return <div data-testid="series-inspector-regenerate" className={`rounded-xl border p-3 ${plan.stale ? 'border-amber-500/40 bg-amber-500/5' : 'border-border bg-bg-secondary'}`}>
    {plan.stale && <p className="text-xs font-semibold text-amber-100">{t(reason(shot, plan))}</p>}
    <div className="mt-1 flex flex-wrap items-center gap-2">
      <button type="button" className={`${plan.stale ? primaryButton : secondaryButton} min-h-10 sm:min-h-0`} disabled={live || busy} onClick={onRender}>
        {mine || busy ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}{t('approval.card.rerender')}</button>
      <p className="min-w-0 flex-1 text-[10px] text-text-muted">{steps(t, series, shot, plan)}</p>
    </div>
    <RenderState item={item} live={live} mine={mine} />
    {error && <p role="alert" className="mt-1 text-[11px] text-red-300">{error}</p>}
  </div>
}
