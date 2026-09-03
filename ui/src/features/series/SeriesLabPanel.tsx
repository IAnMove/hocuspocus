import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookOpen, Copy, Film, Loader2, Plus, RefreshCw, Trash2, Upload } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useSeriesStore } from './store'
import { SeriesSetupPanel } from './SeriesSetupPanel'
import { SeriesCanonPanel } from './SeriesCanonPanel'
import { SeriesEpisodePanel } from './SeriesEpisodePanel'
import { SeriesShotsPanel } from './SeriesShotsPanel'
import { SeriesReviewPanel } from './SeriesReviewPanel'
import { Pill, seriesFormatLabel } from './components'
import { primaryButton, secondaryButton } from './styles'
import { stageSeriesComic } from './adapters'
import type { SeriesJobStatus, SeriesProject } from './types'
import { listenForAgentSeriesRenderJob, listenForAgentSeriesSection } from '../../lib/uiBus'
import { useUiTranslation } from '../../i18n'

type LabTab = 'setup' | 'canon' | 'episode' | 'shots' | 'review'
type SetupGap = 'title' | 'premise' | 'visualStyle'

export function SeriesLabPanel() {
  const { t } = useUiTranslation('seriesLab')
  const tabs: Array<{ id: LabTab; label: string }> = [
    { id: 'setup', label: t('tabs.setup') }, { id: 'canon', label: t('tabs.canon') },
    { id: 'episode', label: t('tabs.episode') }, { id: 'shots', label: t('tabs.shots') },
    { id: 'review', label: t('tabs.review') },
  ]
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const productionProfile = useStore(state => state.productionProfile)
  const {
    workspace, library, activeSeriesId, activeEpisodeId, hydrated, loading, dirty, saving, error,
    planRecovery, renderRecovery, loadWorkspace, reload, openSeries, openEpisode,
    updateSeries, updateEpisode, adoptRemoteSeries, saveNow, newSeries, duplicateSeries,
    deleteSeries, importStory, createEpisode, deleteEpisode, refreshRecovery,
  } = useSeriesStore()
  const [tab, setTab] = useState<LabTab>('setup')
  useEffect(() => listenForAgentSeriesSection(setTab), [])
  const [storyOptions, setStoryOptions] = useState<Array<{ id: string; title: string }>>([])
  const [storyId, setStoryId] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [renderJob, setRenderJob] = useState<SeriesJobStatus | null>(null)
  useEffect(() => listenForAgentSeriesRenderJob(job => {
    setRenderJob(job)
    setTab('review')
  }), [])
  const [canonJob, setCanonJob] = useState<SeriesJobStatus | null>(null)

  useEffect(() => { void loadWorkspace(activeWorkspace || 'default') }, [activeWorkspace, loadWorkspace])
  const series = library.seriesById[activeSeriesId] || null
  useEffect(() => {
    if (!series?.provider.useGlobalProfile) return
    const next = {
      writingProvider: (productionProfile.text.provider === 'local' || productionProfile.text.provider === 'anthropic'
        ? 'maestro'
        : productionProfile.text.provider === 'remote' ? 'openai-compatible' : productionProfile.text.provider) as SeriesProject['provider']['writingProvider'],
      writingModel: productionProfile.text.model,
      writingBaseUrl: productionProfile.text.base_url || (
        productionProfile.text.provider === 'minimax' ? 'https://api.minimax.io/v1'
          : productionProfile.text.provider === 'grok' ? 'https://api.x.ai/v1'
            : productionProfile.text.provider === 'ollama' ? 'http://127.0.0.1:11434'
              : ''
      ),
      imageProvider: productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
      imageModel: productionProfile.image.model,
      videoModel: productionProfile.video.model,
      resolution: productionProfile.video.settings.resolution,
      orientation: productionProfile.video.settings.aspectRatio === '9:16' || productionProfile.video.settings.aspectRatio === '3:4'
        ? 'portrait' as const : 'landscape' as const,
      numInferenceSteps: productionProfile.video.settings.steps,
    }
    if (
      series.provider.writingProvider === next.writingProvider
      && series.provider.writingModel === next.writingModel
      && series.provider.imageProvider === next.imageProvider
      && series.provider.imageModel === next.imageModel
      && series.provider.videoModel === next.videoModel
      && series.provider.videoSettings.resolution === next.resolution
      && series.provider.videoSettings.orientation === next.orientation
      && series.provider.videoSettings.numInferenceSteps === next.numInferenceSteps
    ) return
    updateSeries(current => ({
      ...current,
      provider: {
        ...current.provider,
        writingProvider: next.writingProvider,
        writingModel: next.writingModel,
        writingBaseUrl: next.writingBaseUrl,
        imageProvider: next.imageProvider,
        imageModel: next.imageModel,
        videoModel: next.videoModel,
        videoSettings: {
          ...current.provider.videoSettings,
          resolution: next.resolution,
          orientation: next.orientation,
          numInferenceSteps: next.numInferenceSteps,
          flowShift: productionProfile.video.settings.flowShift,
          audioShift: productionProfile.video.settings.audioShift,
          modelProfile: productionProfile.video.settings.profile,
        },
      },
    }))
  }, [productionProfile, series, updateSeries])
  const episode = series?.episodesById[activeEpisodeId] || null
  useEffect(() => {
    setRenderJob(current => current
      && current.workspace === workspace
      && current.seriesId === series?.id
      && current.episodeId === episode?.id ? current : null)
    setCanonJob(current => current
      && current.workspace === workspace
      && current.seriesId === series?.id ? current : null)
  }, [episode?.id, series?.id, workspace])
  const episodes = useMemo(() => series ? series.seasons.flatMap(season =>
    season.episodeOrder.map(id => series.episodesById[id]).filter(Boolean)) : [], [series])
  const setupMissing: SetupGap[] = series ? (
    [
      !series.title.trim() ? 'title' as const : null,
      !series.premise.trim() ? 'premise' as const : null,
      !series.visualStyle.trim() ? 'visualStyle' as const : null,
    ].filter((item): item is SetupGap => item !== null)
  ) : []
  const missingList = setupMissing.map(key => t(`blockers.missing.${key}`)).join(', ')
  const saveStatus = saving
    ? t('library.saving')
    : dirty
      ? t('library.unsaved')
      : series
        ? t('library.saved', { revision: series.revision })
        : t('library.noSeries')
  const createEpisodeAction = () => {
    if (!series) return
    if (setupMissing.length) {
      setActionError(t('blockers.completeSetupFirst', { list: missingList })); setTab('setup'); return
    }
    if (series.canon.approval !== 'approved') {
      setActionError(t('blockers.reviewApproveFirst')); setTab('canon'); return
    }
    void runAction(createEpisode)
  }
  const openImport = async () => {
    setImportOpen(true); setActionError(null)
    try {
      const stories = await api.fetchStoryLibrary(workspace)
      const options = Object.values(stories.projects).map(item => ({ id: item.id, title: item.title }))
      setStoryOptions(options); setStoryId(options[0]?.id || '')
    } catch (reason) { setActionError((reason as Error).message) }
  }
  const runAction = async (action: () => Promise<void>) => {
    setActionBusy(true); setActionError(null)
    try { await action() } catch (reason) { setActionError((reason as Error).message) }
    finally { setActionBusy(false) }
  }
  const adaptEpisodeToComic = async () => {
    if (!series || !episode || actionBusy) return
    const { useComicStore } = await import('../comics/store')
    if (useComicStore.getState().dirty && !window.confirm(t('episode.adaptToComicConfirm'))) return
    await runAction(async () => {
      await stageSeriesComic({ seriesId: series.id, episodeId: episode.id, confirm: true })
    })
  }
  const startRender = useCallback(async (
    mode: 'selected' | 'missing' | 'failed' | 'all', shotIds?: string[], seed?: number,
  ) => {
    if (!series || !episode) return
    setActionBusy(true); setActionError(null)
    try {
      await saveNow()
      const current = useSeriesStore.getState().library.seriesById[series.id]
      setRenderJob(await api.startSeriesRender(workspace, series.id, episode.id, {
        mode, shotIds, seed,
        settings: current?.provider.videoSettings || series.provider.videoSettings,
      }))
      setTab('review')
    } catch (reason) { setActionError((reason as Error).message) }
    finally { setActionBusy(false) }
  }, [episode, saveNow, series, workspace])
  const handleRecovery = async (job: SeriesJobStatus, kind: 'plan' | 'render', discard = false) => {
    await runAction(async () => {
      if (discard) {
        if (kind === 'plan') await api.discardSeriesPlanJob(job.jobId)
        else await api.discardSeriesRenderJob(job.jobId)
      } else {
        if (job.seriesId) await openSeries(job.seriesId)
        if (job.episodeId) useSeriesStore.getState().openEpisode(job.episodeId)
      }
      if (!discard && kind === 'plan') {
        const resumed = await api.resumeSeriesPlanJob(job.jobId)
        if (job.jobType === 'canon') {
          setCanonJob({ ...job, ...resumed, jobType: 'canon' }); setTab('setup')
        } else setTab('episode')
      } else if (!discard) {
        setRenderJob(await api.resumeSeriesRenderJob(job.jobId))
        setTab('review')
      }
      await refreshRecovery()
    })
  }

  if (loading || (!hydrated && !error)) return <div className="flex h-full items-center justify-center gap-2 text-xs text-text-muted"><Loader2 size={18} className="animate-spin" />{t('library.loading')}</div>
  return <section aria-label={t('library.workspaceAria')} className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-primary md:flex-row">
    <aside aria-label={t('library.libraryAria')} className="flex w-full shrink-0 flex-col border-b border-border bg-bg-secondary md:w-56 md:border-b-0 md:border-r xl:w-64">
      <div className="border-b border-border p-3"><div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold text-text-primary">{t('library.title')}</h2><p className="text-[10px] text-text-muted">{t('library.schema', { workspace })}</p></div><button className={secondaryButton} onClick={() => void reload()} title={t('library.reload')}><RefreshCw size={13} /></button></div><div className="mt-3 grid grid-cols-2 gap-2"><button className={primaryButton} disabled={actionBusy} onClick={() => void runAction(newSeries)}><Plus size={13} />{t('library.new')}</button><button className={secondaryButton} disabled={actionBusy} onClick={() => void openImport()}><Upload size={13} />{t('library.story')}</button></div></div>
      <nav aria-label={t('library.projectsAria')} className="flex min-h-0 max-h-32 flex-1 gap-2 overflow-x-auto p-2 md:block md:max-h-none md:overflow-x-hidden md:overflow-y-auto">{library.seriesOrder.map(id => { const item = library.seriesById[id]; return <button key={id} onClick={() => void openSeries(id)} className={`mb-0 min-w-44 shrink-0 rounded-lg border p-2 text-left md:mb-1 md:w-full md:min-w-0 ${id === activeSeriesId ? 'border-violet-500/40 bg-violet-500/10' : 'border-transparent hover:bg-bg-hover'}`}><div className="truncate text-xs font-medium text-text-primary">{item.title}</div><div className="mt-1 flex gap-1"><Pill>{seriesFormatLabel(t, item.format)}</Pill><Pill tone="violet">{t('library.canonRevision', { revision: item.canon.revision })}</Pill></div></button>})}{!library.seriesOrder.length && <p className="min-w-64 p-3 text-[11px] leading-relaxed text-text-muted">{t('library.empty')}</p>}</nav>
      {series && <div className="flex gap-1 border-t border-border p-2"><button className={secondaryButton} onClick={() => void runAction(() => duplicateSeries(series.id))} title={t('library.duplicate')}><Copy size={13} /></button><button className={secondaryButton} onClick={() => { if (window.confirm(t('library.deleteConfirm', { title: series.title }))) void runAction(() => deleteSeries(series.id)) }} title={t('library.delete')}><Trash2 size={13} className="text-red-400" /></button></div>}
    </aside>

    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="border-b border-border bg-bg-secondary px-3 py-2">
        <div role="group" aria-label={t('library.episodeControlsAria')} className="flex flex-wrap items-center gap-2 sm:gap-3"><div className="min-w-0 basis-full flex-1 sm:basis-auto"><h2 className="truncate text-sm font-semibold text-text-primary">{series?.title || t('library.title')}</h2><p className="text-[10px] text-text-muted">{saveStatus}</p></div>{episode && <select className="min-w-0 flex-1 rounded-lg border border-border bg-bg-primary px-2 py-1.5 text-xs text-text-secondary sm:max-w-56" value={episode.id} onChange={event => openEpisode(event.target.value)}>{episodes.map(item => <option key={item.id} value={item.id}>{t('library.episodeOption', { number: item.number, title: item.title })}</option>)}</select>}{episode && <button className={secondaryButton} title={t('library.deleteEpisode')} onClick={() => { if (window.confirm(t('library.deleteConfirm', { title: episode.title }))) void runAction(() => deleteEpisode(episode.id)) }}><Trash2 size={13} className="text-red-400" /></button>}{series && <button className={secondaryButton} onClick={createEpisodeAction}><Plus size={13} />{t('library.episode')}</button>}</div>
        {series && <nav className="mt-2 flex gap-1 overflow-x-auto">{tabs.map(item => <button key={item.id} onClick={() => setTab(item.id)} className={`shrink-0 rounded-lg px-3 py-1.5 text-[11px] ${tab === item.id ? 'bg-violet-500/20 text-violet-200' : 'text-text-muted hover:bg-bg-hover'}`}>{item.label}</button>)}</nav>}
      </header>

      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        {(error || actionError) && <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{actionError || error}</div>}
        {series && (setupMissing.length > 0 || series.canon.approval !== 'approved') && <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 p-3 text-[11px] text-violet-100"><span className="mr-auto">{t('blockers.message')}</span>{setupMissing.length > 0 && <button className={secondaryButton} onClick={() => setTab('setup')}>{t('blockers.completeSetup', { list: missingList })}</button>}{series.canon.approval !== 'approved' && <button className={secondaryButton} onClick={() => setTab('canon')}>{t('blockers.reviewApprove')}</button>}</div>}
        {(planRecovery.length > 0 || renderRecovery.length > 0) && <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3"><h3 className="text-xs font-semibold text-amber-200">{t('recovery.title')}</h3><div className="mt-2 space-y-2">{planRecovery.map(job => { const owner = library.seriesById[job.seriesId]; const ownerEpisode = owner?.episodesById[job.episodeId]; return <div key={job.jobId} className="flex flex-wrap items-center gap-2 text-[10px] text-amber-100"><BookOpen size={12} /><span className="flex-1">{owner?.title || job.seriesId}{ownerEpisode ? t('recovery.episodeSuffix', { number: ownerEpisode.number, title: ownerEpisode.title }) : ''} · {job.jobType === 'canon' ? t('recovery.canonPreparation') : t('recovery.episodePlanning')} · {job.message}</span><button className={secondaryButton} onClick={() => void handleRecovery(job, 'plan')}>{t('chrome.resume')}</button><button className={secondaryButton} onClick={() => void handleRecovery(job, 'plan', true)}>{t('chrome.discardState')}</button></div> })}{renderRecovery.map(job => { const owner = library.seriesById[job.seriesId]; const ownerEpisode = owner?.episodesById[job.episodeId]; return <div key={job.jobId} className="flex flex-wrap items-center gap-2 text-[10px] text-amber-100"><Film size={12} /><span className="flex-1">{t('recovery.renderLine', { series: owner?.title || job.seriesId, episode: ownerEpisode ? t('recovery.renderEpisode', { number: ownerEpisode.number, title: ownerEpisode.title }) : job.episodeId, current: job.current, total: job.total, message: job.message })}</span><button className={secondaryButton} onClick={() => void handleRecovery(job, 'render')}>{t('chrome.resume')}</button><button className={secondaryButton} onClick={() => void handleRecovery(job, 'render', true)}>{t('chrome.discardState')}</button></div> })}</div></div>}
        {importOpen && <div className="mb-4 rounded-xl border border-violet-500/30 bg-violet-500/10 p-3"><h3 className="text-xs font-semibold text-violet-200">{t('storyImport.title')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('storyImport.description')}</p><div className="mt-2 flex gap-2"><select className="min-w-0 flex-1 rounded-lg border border-border bg-bg-primary px-2 py-2 text-xs" value={storyId} onChange={event => setStoryId(event.target.value)}>{storyOptions.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select><button className={primaryButton} disabled={!storyId || actionBusy} onClick={() => void runAction(async () => { await importStory(storyId); setImportOpen(false) })}>{t('chrome.import')}</button><button className={secondaryButton} onClick={() => setImportOpen(false)}>{t('chrome.cancel')}</button></div></div>}
        {!series ? <div className="mx-auto mt-20 max-w-lg rounded-2xl border border-violet-500/30 bg-violet-500/10 p-8 text-center"><BookOpen size={28} className="mx-auto text-violet-300" /><h3 className="mt-3 text-base font-semibold text-text-primary">{t('library.emptyTitle')}</h3><p className="mt-2 text-xs leading-relaxed text-text-muted">{t('library.emptyBody')}</p><button className={`mt-4 ${primaryButton}`} onClick={() => void runAction(newSeries)}><Plus size={13} />{t('library.createOriginal')}</button></div> : <>
          {tab === 'setup' && <SeriesSetupPanel workspace={workspace} series={series} update={updateSeries} saveNow={saveNow} replaceSeries={adoptRemoteSeries} job={canonJob} setJob={setCanonJob} />}
          {tab === 'canon' && <SeriesCanonPanel series={series} workspace={workspace} update={updateSeries} replaceSeries={adoptRemoteSeries} saveNow={saveNow} />}
          {tab === 'episode' && (episode ? <SeriesEpisodePanel workspace={workspace} series={series} episode={episode} updateEpisode={updater => updateEpisode(episode.id, updater)} saveNow={saveNow} reload={reload} onAdaptToComic={adaptEpisodeToComic} /> : <div className="rounded-xl border border-violet-500/30 bg-violet-500/10 p-6 text-center text-xs text-violet-200"><button className={primaryButton} onClick={createEpisodeAction}><Plus size={13} />{t('library.createFirstEpisode')}</button></div>)}
          {tab === 'shots' && (episode ? <SeriesShotsPanel workspace={workspace} series={series} episode={episode} updateEpisode={updater => updateEpisode(episode.id, updater)} replaceSeries={adoptRemoteSeries} saveNow={saveNow} onAcknowledgeLipSync={async () => { updateSeries(current => ({ ...current, bestEffortLipSyncAcknowledged: true })); await saveNow() }} onRender={(mode, ids) => void startRender(mode, ids)} /> : <p className="text-xs text-text-muted">{t('library.createEpisodeFirst')}</p>)}
          {tab === 'review' && (episode ? <SeriesReviewPanel workspace={workspace} series={series} episode={episode} job={renderJob} setJob={setRenderJob} reload={reload} startRender={startRender} updateEpisode={updater => updateEpisode(episode.id, updater)} saveNow={saveNow} /> : <p className="text-xs text-text-muted">{t('library.createEpisodeFirst')}</p>)}
        </>}
      </div>
    </div>
  </section>
}

export default SeriesLabPanel
