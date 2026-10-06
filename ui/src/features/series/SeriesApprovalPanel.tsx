import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchSeriesProject } from '../../api/series'
import { useUiTranslation } from '../../i18n'
import { useSeriesStore } from './store'
import {
  episodeReview, groupShotsByScene, latestTake, matchesFilter, REVIEW_FILTERS, reviewSummary, shotCast, shotReview,
  type CastMember, type ReviewFilter, type SceneGroup,
} from './reviewModel'
import { SeriesApprovalHeader } from './SeriesApprovalHeader'
import type { ApprovalCardActions } from './SeriesApprovalCard'
import { useApprovalRender } from './useApprovalRender'
import { useShotEditSession } from './shotEditSession'
import { inspectorKey, openInspectorShot, useEpisodeInspector } from './inspector/inspectorStore'
import { SeriesShotInspector } from './inspector/SeriesShotInspector'
import { SeriesShotTile } from './inspector/SeriesShotTile'
import { forgetKitLibrary, useKitLibrary } from './inspector/useInspectorData'
import type { SeriesEdits } from './inspector/SetPart'
import type { SeriesProductionMode, SeriesProject, SeriesEpisode, SeriesShot, SeriesShotReviewChange } from './types'

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

/**
 * Series Lab → Validation: every shot of the episode as a tile, grouped by scene, each with Open; an opened shot shows
 * its take and all its parts in the shot inspector. Returning from an editor lands on the same shot.
 */
export function SeriesApprovalPanel({ workspace, series, episode, saveNow, onOpenFaceRig, onOpenResults }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; saveNow: () => Promise<unknown>
  onOpenFaceRig?: (characterId: string, poseId?: string, shotId?: string) => void; onOpenResults?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const saveReview = useSeriesStore(state => state.saveReview)
  const [filter, setFilter] = useState<ReviewFilter>('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // A finished render brings its takes in without reloading the page (a reload would close the open shot).
  const refresh = useCallback(async () => {
    await saveNow()
    useSeriesStore.getState().adoptRemoteSeries(await fetchSeriesProject(workspace, series.id))
  }, [saveNow, workspace, series.id])
  const render = useApprovalRender(workspace, series.id, episode.id, refresh)
  const kits = useKitLibrary(workspace)
  useEffect(() => () => forgetKitLibrary(workspace), [workspace])
  const { mode } = episodeReview(episode)
  const summary = useMemo(() => reviewSummary(episode), [episode])
  const groups = useMemo(() => groupShotsByScene(episode), [episode])
  const cast = useMemo(() => episodeCast(series, episode), [series, episode])
  const key = inspectorKey(workspace, series.id, episode.id)
  const inspector = useEpisodeInspector(key)
  const open = episode.shots.find(shot => shot.id === inspector.openShotId)
  const focusShotId = useShotEditSession(state => state.focusShotId)
  useEffect(() => {
    if (!focusShotId) return
    if (episode.shots.some(shot => shot.id === focusShotId)) openInspectorShot(key, focusShotId)
    useShotEditSession.setState({ focusShotId: '' })
  }, [focusShotId, key, episode.shots])
  const send = useCallback(async (change: Parameters<typeof saveReview>[1]) => {
    setBusy(true); setError('')
    try { return await saveReview(episode.id, change) } catch (reason) { setError((reason as Error).message); throw reason } finally { setBusy(false) }
  }, [episode.id, saveReview])
  const quiet = (task: Promise<unknown>) => { void task.catch(() => { /* shown in the panel */ }) }
  const actions: ApprovalCardActions = {
    review: async (shot, stage, status) => {
      const take = stage === 'preview' && status !== 'pending' ? latestTake(shot) : undefined
      quiet(send({ shots: [{ shotId: shot.id, ...(stage === 'plan' ? { plan: status } : { preview: status }), ...(take ? { attemptId: take.id } : {}) }] }))
    },
    saveNote: shot => note => send({ shots: [{ shotId: shot.id, note }] }),
    rerender: shot => { void (async () => { await saveNow(); await render.start([shot.id]) })() },
    openFaceRig: onOpenFaceRig && ((characterId, poseId) => onOpenFaceRig(characterId, poseId, inspector.openShotId || undefined)),
  }
  const edits: SeriesEdits = {
    updateSeries: useSeriesStore.getState().updateSeries, saveNow,
    onAssetImported: useSeriesStore.getState().acceptAssetImport,
  }
  const visible = (shot: SeriesShot) => matchesFilter(filter, shot, shotReview(episode, shot.id), mode)
  const ordered = useMemo(() => groups.flatMap(group => group.shots), [groups])
  const visibleOrder = ordered.filter(visible).map(shot => shot.id)
  const order = open && visibleOrder.includes(open.id) ? visibleOrder : ordered.map(shot => shot.id)
  const close = () => {
    const shotId = inspector.openShotId
    openInspectorShot(key, '')
    window.setTimeout(() => document.getElementById(`series-approval-${shotId}`)?.scrollIntoView?.({ block: 'center' }), 50)
  }
  const approveVisible = () => {
    const shots: SeriesShotReviewChange[] = episode.shots.filter(shot => visible(shot) && shotReview(episode, shot.id).plan !== 'approved')
      .map(shot => ({ shotId: shot.id, plan: 'approved' }))
    if (!shots.length || !window.confirm(t('approval.actions.approveVisibleConfirm', { count: shots.length }))) return
    for (let index = 0; index < shots.length; index += MAX_CHANGES) quiet(send({ shots: shots.slice(index, index + MAX_CHANGES) }))
  }
  const setMode = (value: SeriesProductionMode) => quiet(send({ mode: value }))
  if (open) {
    return <div className="space-y-2">
      {error && <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}
      <SeriesShotInspector key={open.id} workspace={workspace} series={series} episode={episode} shot={open} entry={shotReview(episode, open.id)} mode={mode}
        inspector={key} order={order} render={render} actions={actions} edits={edits} onClose={close} onNavigate={shotId => openInspectorShot(key, shotId)} />
    </div>
  }
  return <div className="@container space-y-3 pb-10">
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
        <div className="grid grid-cols-2 gap-2 @xl:grid-cols-3 @3xl:grid-cols-4 @6xl:grid-cols-6">{shots.map(shot => <SeriesShotTile key={shot.id} series={series}
          shot={shot} entry={shotReview(episode, shot.id)} mode={mode} kits={kits} actions={actions}
          unsaved={Object.keys(inspector.drafts[shot.id] || {}).length} onOpen={() => openInspectorShot(key, shot.id)} />)}</div>
      </section>
    })}
  </div>
}
