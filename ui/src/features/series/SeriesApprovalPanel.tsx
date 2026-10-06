import { useCallback, useEffect, useMemo, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useSeriesStore } from './store'
import {
  episodeReview, groupShotsByScene, latestTake, matchesFilter, REVIEW_FILTERS, reviewSummary, shotCast, shotReview,
  type CastMember, type ReviewFilter, type SceneGroup,
} from './reviewModel'
import { SeriesApprovalHeader } from './SeriesApprovalHeader'
import { SeriesApprovalCard, type ApprovalCardActions } from './SeriesApprovalCard'
import { useApprovalRender } from './useApprovalRender'
import { openShotInEditor, useShotEditSession } from './shotEditSession'
import type { SeriesEpisode, SeriesProductionMode, SeriesProject, SeriesShot, SeriesShotReviewChange } from './types'

const MAX_CHANGES = 500

/** Every on-screen character of the episode once, with the first pose a shot uses. */
function episodeCast(series: SeriesProject, episode: SeriesEpisode): CastMember[] {
  const seen = new Map<string, CastMember>()
  for (const shot of episode.shots) for (const member of shotCast(series, shot)) if (!seen.has(member.characterId)) seen.set(member.characterId, member)
  return [...seen.values()]
}

function FilterBar({ filter, counts, onFilter }: { filter: ReviewFilter; counts: Record<ReviewFilter, number>; onFilter: (filter: ReviewFilter) => void }) {
  const { t } = useUiTranslation('seriesLab')
  return <div role="tablist" aria-label={t('approval.filters.label')} className="sticky top-0 z-10 -mx-1 flex gap-1 overflow-x-auto bg-bg-primary/95 px-1 py-2 backdrop-blur">
    {REVIEW_FILTERS.map(value => <button key={value} type="button" role="tab" aria-selected={filter === value}
      className={`min-h-10 shrink-0 rounded-lg px-3 text-[11px] sm:min-h-8 ${filter === value ? 'bg-violet-500/20 text-violet-100' : 'text-text-muted hover:bg-bg-hover'}`}
      onClick={() => onFilter(value)}>{t(`approval.filters.${value}`, { count: counts[value] })}</button>)}
  </div>
}

function SceneHeader({ group, series, approved }: { group: SceneGroup; series: SeriesProject; approved: number }) {
  const { t } = useUiTranslation('seriesLab')
  const location = series.locations.find(item => item.id === group.locationId)?.name
  return <header className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border pb-1">
    <h3 className="text-xs font-semibold text-text-primary">{t('approval.scene.title', { number: group.number })}{location ? ` · ${location}` : ''}</h3>
    {(group.time || group.title) && <span className="min-w-0 truncate text-[10px] text-text-muted">{[group.time, group.title].filter(Boolean).join(' · ')}</span>}
    <span className="ml-auto text-[10px] text-text-muted">{t('approval.scene.progress', { done: approved, total: group.shots.length })}</span>
  </header>
}

export function SeriesApprovalPanel({ workspace, series, episode, reload, updateEpisode, saveNow, onOpenFaceRig, onOpenResults }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; reload: () => Promise<void>
  updateEpisode: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void; saveNow: () => Promise<unknown>
  onOpenFaceRig?: (characterId: string, poseId?: string) => void; onOpenResults?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const saveReview = useSeriesStore(state => state.saveReview)
  const [filter, setFilter] = useState<ReviewFilter>('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const render = useApprovalRender(workspace, series.id, episode.id, reload)
  const { mode } = episodeReview(episode)
  const summary = useMemo(() => reviewSummary(episode), [episode])
  const groups = useMemo(() => groupShotsByScene(episode), [episode])
  const cast = useMemo(() => episodeCast(series, episode), [series, episode])
  const focusShotId = useShotEditSession(state => state.focusShotId)
  useEffect(() => {
    if (!focusShotId) return
    setFilter('all')
    window.setTimeout(() => document.getElementById(`series-approval-${focusShotId}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 50)
    useShotEditSession.setState({ focusShotId: '' })
  }, [focusShotId])
  const send = useCallback(async (change: Parameters<typeof saveReview>[1]) => {
    setBusy(true); setError('')
    try { return await saveReview(episode.id, change, { workspace, seriesId: series.id }) } catch (reason) { setError((reason as Error).message); throw reason } finally { setBusy(false) }
  }, [workspace, series.id, episode.id, saveReview])
  const quiet = (task: Promise<unknown>) => { void task.catch(() => { /* shown in the panel */ }) }
  const actions: ApprovalCardActions = {
    review: async (shot, stage, status) => {
      const take = stage === 'preview' && status !== 'pending' ? latestTake(shot) : undefined
      quiet(send({ shots: [{ shotId: shot.id, ...(stage === 'plan' ? { plan: status } : { preview: status }), ...(take ? { attemptId: take.id } : {}) }] }))
    },
    saveNote: shot => note => send({ shots: [{ shotId: shot.id, note }] }),
    rerender: shot => { void render.start([shot.id]) },
    openEditor: shot => { void openShotInEditor(workspace, series, episode, shot).catch(reason => setError((reason as Error).message)) },
    openFaceRig: onOpenFaceRig,
    changeShot: next => updateEpisode(current => ({ ...current, shots: current.shots.map(shot => shot.id === next.id ? next : shot) })),
  }
  const visible = (shot: SeriesShot) => matchesFilter(filter, shot, shotReview(episode, shot.id), mode)
  const approveVisible = () => {
    const shots: SeriesShotReviewChange[] = episode.shots.filter(shot => visible(shot) && shotReview(episode, shot.id).plan !== 'approved')
      .map(shot => ({ shotId: shot.id, plan: 'approved' }))
    if (!shots.length || !window.confirm(t('approval.actions.approveVisibleConfirm', { count: shots.length }))) return
    for (let index = 0; index < shots.length; index += MAX_CHANGES) quiet(send({ shots: shots.slice(index, index + MAX_CHANGES) }))
  }
  const setMode = (value: SeriesProductionMode) => quiet(send({ mode: value }))
  return <div className="space-y-3 pb-10">
    <SeriesApprovalHeader summary={summary} render={render} busy={busy} cast={cast} onMode={setMode} onFilter={setFilter}
      onApproveVisible={approveVisible} onOpenFaceRig={onOpenFaceRig} onOpenResults={onOpenResults} />
    {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}
    <FilterBar filter={filter} counts={summary.filters} onFilter={setFilter} />
    {!episode.shots.length && <p className="text-xs text-text-muted">{t('approval.empty')}</p>}
    {groups.map(group => {
      const shots = group.shots.filter(visible)
      if (!shots.length) return null
      const approved = group.shots.filter(shot => matchesFilter('approved', shot, shotReview(episode, shot.id), mode)).length
      return <section key={group.sceneId} className="space-y-2">
        <SceneHeader group={group} series={series} approved={approved} />
        <div className="grid gap-3 2xl:grid-cols-2">{shots.map(shot => <SeriesApprovalCard key={shot.id} workspace={workspace} series={series} episode={episode}
          shot={shot} entry={shotReview(episode, shot.id)} mode={mode} renderLive={render.live || render.busy} actions={actions} saveNow={saveNow} />)}</div>
      </section>
    })}
  </div>
}
