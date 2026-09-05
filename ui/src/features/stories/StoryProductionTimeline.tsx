import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Combine, ExternalLink, Film, History, Loader2, Play, RefreshCw, Square } from 'lucide-react'
import * as api from '../../api/client'
import { reconcilePlaybackCursor } from '../../lib/orderedClipTimeline'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import type { PipelineClipState, PipelineVideoAttempt, SavedPipelineState } from '../../types'
import type { StoryProduction } from './types'
import {
  clearDirectorClipReplacementResult,
  directorClipCreatorMetadata,
  readDirectorClipReplacementResult,
  writeDirectorClipReplacementTarget,
} from './directorClipHandoff'

const control = 'inline-flex items-center gap-1 rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] text-text-secondary hover:bg-bg-hover disabled:opacity-40'
const TERMINAL_PIPELINE_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'crashed',
  'interrupted',
  'preview_ready',
])

function isTerminalPipelineStatus(status: string | undefined): boolean {
  return TERMINAL_PIPELINE_STATUSES.has((status || '').trim().toLowerCase())
}

function attemptsForClip(clip: PipelineClipState): PipelineVideoAttempt[] {
  if (clip.video_attempts?.length) return clip.video_attempts
  return clip.video_filename ? [{
    id: clip.video_filename,
    filename: clip.video_filename,
    created_at: 0,
    seed: clip.seed,
    prompt: clip.video_prompt,
    source: 'recovered',
  }] : []
}

function selectedAttempt(clip: PipelineClipState): PipelineVideoAttempt | null {
  const attempts = attemptsForClip(clip)
  const selected = clip.selected_video_filename || clip.video_filename
  return attempts.find(attempt => attempt.filename === selected)
    || attempts[attempts.length - 1]
    || null
}

export function StoryProductionTimeline({ production, initiallyOpen = false }: {
  production: StoryProduction
  initiallyOpen?: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  const pipelineId = typeof production.targetSnapshot?.pipelineId === 'string'
    ? production.targetSnapshot.pipelineId : ''
  const returnedSelection = useRef(readDirectorClipReplacementResult())
  const [open, setOpen] = useState(
    initiallyOpen || returnedSelection.current?.pipelineId === pipelineId,
  )
  const [pipeline, setPipeline] = useState<SavedPipelineState | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [playbackShotId, setPlaybackShotId] = useState<string | null>(null)
  const [playingAll, setPlayingAll] = useState(false)
  const [selectingAttempt, setSelectingAttempt] = useState<string | null>(null)
  const [preparingCreator, setPreparingCreator] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const playerRef = useRef<HTMLVideoElement>(null)
  const pipelineLoadedRef = useRef(false)
  const refreshRef = useRef<(() => void) | null>(null)
  const setDashboardOpen = useStore(state => state.setDashboardOpen)
  const rejoinPipelineClips = useStore(state => state.rejoinPipelineClips)

  const orderedClips = useMemo(() => [...(pipeline?.clips || [])]
    .sort((left, right) => left.index - right.index), [pipeline])
  const playable = useMemo(() => orderedClips.flatMap(clip => {
    const attempt = selectedAttempt(clip)
    if (!attempt || clip.video_stale) return []
    return [{
      shotId: clip.shot_id || `clip-index-${clip.index}`,
      clip,
      attempt,
      video_filename: attempt.filename,
      index: clip.index,
    }]
  }), [orderedClips])
  const playbackCursor = reconcilePlaybackCursor(playbackShotId, playable)
  const playIndex = playbackCursor.index
  const current = playIndex >= 0 ? playable[playIndex] : undefined

  useEffect(() => {
    if (!playingAll) return
    if (playbackCursor.outcome === 'stop' || !current?.video_filename) {
      setPlayingAll(false)
      setPlaybackShotId(null)
      setError(t('timeline.playAllStopped'))
      return
    }
    if (!playerRef.current) return
    playerRef.current.currentTime = 0
    void playerRef.current.play().catch(reason => {
      setPlayingAll(false); setError((reason as Error).message)
    })
  }, [current?.video_filename, playbackCursor.outcome, playingAll, t])

  useEffect(() => {
    if (!open || !pipelineId) return
    let active = true
    let inFlight = false
    let terminalSeen = false
    let timer: number | null = null

    const stopPolling = () => {
      if (timer !== null) window.clearTimeout(timer)
      timer = null
    }
    const scheduleNext = () => {
      if (!active || terminalSeen || timer !== null) return
      timer = window.setTimeout(() => {
        timer = null
        void refresh(false, false)
      }, 3000)
    }
    const refresh = async (initial = false, manual = false) => {
      if (inFlight) return
      inFlight = true
      if (initial) setLoading(true)
      if (manual) setRefreshing(true)
      try {
        const value = await api.fetchSavedPipeline(pipelineId)
        if (active) {
          pipelineLoadedRef.current = true
          setPipeline(value)
          setError(null)
          terminalSeen = isTerminalPipelineStatus(value.status)
          if (terminalSeen) stopPolling()
          else scheduleNext()
          const returned = returnedSelection.current
          if (returned?.pipelineId === pipelineId) {
            const matchingClip = [...value.clips]
              .sort((left, right) => left.index - right.index)
              .filter(clip => Boolean(selectedAttempt(clip)) && !clip.video_stale)
              .find(item => item.index === returned.clipIndex)
            if (matchingClip) {
              setPlaybackShotId(matchingClip.shot_id || `clip-index-${matchingClip.index}`)
            }
            returnedSelection.current = null
            clearDirectorClipReplacementResult()
          }
        }
      } catch (reason) {
        if (active) {
          setError((reason as Error).message)
          scheduleNext()
        }
      } finally {
        inFlight = false
        if (active && initial) setLoading(false)
        if (active && manual) setRefreshing(false)
      }
    }
    refreshRef.current = () => { void refresh(false, true) }
    void refresh(!pipelineLoadedRef.current)
    return () => {
      active = false
      stopPolling()
      refreshRef.current = null
    }
  }, [open, pipelineId])

  const chooseAttempt = async (clip: PipelineClipState, attempt: PipelineVideoAttempt) => {
    if (!pipeline || selectingAttempt) return
    setSelectingAttempt(attempt.filename)
    setError(null)
    setPlayingAll(false)
    playerRef.current?.pause()
    try {
      await api.selectPipelineClipVideo(pipeline.pipeline_id, clip.index, attempt.filename)
      const refreshed = await api.fetchSavedPipeline(pipeline.pipeline_id)
      setPipeline(refreshed)
      const matchingClip = [...refreshed.clips]
        .sort((left, right) => left.index - right.index)
        .filter(item => Boolean(selectedAttempt(item)) && !item.video_stale)
        .find(item => item.index === clip.index)
      if (matchingClip) {
        setPlaybackShotId(matchingClip.shot_id || `clip-index-${matchingClip.index}`)
      }
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSelectingAttempt(null)
    }
  }

  const remakeCurrentClip = async () => {
    if (!pipeline || !current || preparingCreator) return
    setPreparingCreator(true)
    setError(null)
    setPlayingAll(false)
    playerRef.current?.pause()
    try {
      const targetWorkspace = pipeline.workspace || 'default'
      const metadata = await api.fetchOutputMetadata(
        current.attempt.filename,
        targetWorkspace,
      )
      if (!metadata.params) {
        throw new Error(t('timeline.noReusableSettings'))
      }
      const prepared = directorClipCreatorMetadata(
        pipeline,
        current.clip,
        current.attempt,
        metadata,
      )
      const store = useStore.getState()
      if (store.activeWorkspace !== targetWorkspace) {
        await store.switchWorkspace(targetWorkspace)
        if (useStore.getState().activeWorkspace !== targetWorkspace) {
          throw new Error(t('timeline.couldNotSwitchWorkspace', { workspace: targetWorkspace }))
        }
      }
      store.setSidebarMode('studio')
      store.setGenerationMode('video')
      useStore.setState({ selectedOutputMeta: prepared, metadataLoading: false })
      await useStore.getState().loadSettingsFromOutput()
      useStore.getState().setGenerationMode('video')
      useStore.getState().setSidebarMode('studio')
      writeDirectorClipReplacementTarget({
        pipelineId: pipeline.pipeline_id,
        clipIndex: current.clip.index,
        workspace: targetWorkspace,
        sourceAttemptFilename: current.attempt.filename,
        requestedAt: Date.now(),
      })
      useStore.getState().setMediaFilter('videos')
    } catch (reason) {
      setError(t('timeline.couldNotOpenCreator', { message: (reason as Error).message }))
      setPreparingCreator(false)
    }
  }

  if (!pipelineId) return <span className="text-[9px] text-text-muted">{t('timeline.openOnce')}</span>
  const finalOutput = pipeline?.final_output_filename || [...(pipeline?.output_files || [])].reverse()
    .find(filename => /(?:rejoin|multiclip|_movie)\.(?:mp4|webm|mkv|mov)$/i.test(filename))
  return <div className="mt-2 w-full">
    <button className={control} onClick={() => { setError(null); setOpen(value => !value) }}><Film size={11} />{open ? t('timeline.hideOrdered') : t('timeline.viewOrdered')}</button>
    {open && <div className="mt-2 rounded-xl border border-border bg-bg-secondary p-2">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-text-muted">{t('timeline.pipelineMeta', { id: pipelineId, playable: playable.length, total: pipeline?.clips.length || 0 })}</span>
        <button className={control} disabled={loading || refreshing} onClick={() => refreshRef.current?.()}>{refreshing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}{t('timeline.refresh')}</button>
        <button className={control} disabled={!playable.length || playingAll} onClick={() => { setPlaybackShotId(playable[0].shotId); setPlayingAll(true) }}><Play size={11} />{t('timeline.playAll')}</button>
        {playingAll && <button className={control} onClick={() => { playerRef.current?.pause(); setPlayingAll(false); setPlaybackShotId(null) }}><Square size={11} />{t('timeline.stop')}</button>}
        <button className={control} disabled={playable.length < 2 || loading} onClick={() => { setLoading(true); setError(null); void rejoinPipelineClips(pipelineId).then(() => api.fetchSavedPipeline(pipelineId)).then(setPipeline).catch(reason => setError((reason as Error).message)).finally(() => setLoading(false)) }}>{loading ? <Loader2 size={11} className="animate-spin" /> : <Combine size={11} />}{t('timeline.joinClips')}</button>
        <button className={control} onClick={() => {
          useStore.getState().setMediaFilter('runs')
          void useStore.getState().loadPipelineList(pipelineId)
          void useStore.getState().loadSavedPipeline(pipelineId)
          setDashboardOpen(false)
        }}><ExternalLink size={11} />{t('timeline.editRegenerate')}</button>
        {finalOutput && <a className={control} href={api.getFileUrl(finalOutput, pipeline?.workspace)} target="_blank" rel="noreferrer">{t('timeline.openJoined')}</a>}
      </div>
      {error && <p className="mb-2 rounded border border-red-500/30 bg-red-500/10 p-2 text-[10px] text-red-300">{error}</p>}
      {loading && !pipeline && <div className="flex items-center gap-2 p-4 text-[10px] text-text-muted"><Loader2 size={12} className="animate-spin" />{t('timeline.loadingHistory')}</div>}
      {pipeline && <div className="grid min-h-72 overflow-hidden rounded-lg border border-border lg:grid-cols-[17rem_minmax(0,1fr)]">
        <div className="max-h-[40rem] overflow-y-auto border-b border-border p-2 lg:border-b-0 lg:border-r">{orderedClips.map(clip => {
          const attempt = selectedAttempt(clip)
          const attemptCount = attemptsForClip(clip).length
          return <button key={clip.shot_id || clip.index} className={`mb-1.5 w-full rounded border p-2 text-left ${current?.index === clip.index ? 'border-violet-400 bg-violet-500/15' : 'border-border bg-bg-primary'}`} onClick={() => { const next = playable.find(value => value.index === clip.index); if (next) { setPlayingAll(false); setPlaybackShotId(next.shotId) } }}>
            <span className="text-[10px] font-medium text-text-primary">{t('timeline.clipN', { n: clip.index + 1 })}</span>
            <span className="ml-2 text-[9px] text-text-muted">{attempt ? clip.video_stale ? t('timeline.stale') : t('timeline.ready') : t('timeline.missing')}</span>
            <span className="ml-2 text-[9px] text-violet-300">{t('timeline.version', { count: attemptCount })}</span>
            {attempt && <p className="mt-1 truncate font-mono text-[8px] text-emerald-300" title={attempt.filename}>{t('timeline.inAssembly', { filename: attempt.filename })}</p>}
            <p className="mt-1 line-clamp-2 text-[9px] text-text-muted">{clip.video_prompt || clip.image_prompt}</p>
          </button>
        })}</div>
        {current?.video_filename ? <div className="min-w-0 bg-bg-primary">
          <div className="bg-black"><video key={current.video_filename} ref={playerRef} className="max-h-[28rem] w-full bg-black" src={api.getFileUrl(current.video_filename, pipeline.workspace)} controls autoPlay={playingAll} onEnded={() => { if (!playingAll) return; if (playIndex + 1 < playable.length) setPlaybackShotId(playable[playIndex + 1].shotId); else { setPlayingAll(false); setPlaybackShotId(null) } }} /></div>
          <div className="flex flex-wrap items-center gap-2 border-b border-border p-2">
            <span className="mr-auto text-[10px] text-text-muted">{t('timeline.clipMeta', { n: current.index + 1, seed: current.attempt.seed ?? current.clip.seed ?? '—', seconds: current.clip.duration_seconds || 0 })}</span>
            <button className="inline-flex items-center gap-1 rounded border border-violet-400/50 bg-violet-500/15 px-2.5 py-1.5 text-[10px] font-medium text-violet-200 hover:bg-violet-500/25 disabled:opacity-40" disabled={preparingCreator || Boolean(selectingAttempt)} onClick={() => void remakeCurrentClip()}>
              {preparingCreator ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}{t('timeline.remakeClip')}
            </button>
          </div>
          <div className="p-2">
            <div className="mb-2 flex items-center gap-1 text-[10px] font-medium text-text-secondary"><History size={11} />{t('timeline.slotHistory')}</div>
            <div className="grid max-h-60 grid-cols-2 gap-2 overflow-y-auto xl:grid-cols-3">{attemptsForClip(current.clip).map((attempt, attemptIndex) => {
              const selected = attempt.filename === (current.clip.selected_video_filename || current.clip.video_filename)
              return <button key={attempt.id || attempt.filename} disabled={Boolean(selectingAttempt)} onClick={() => void chooseAttempt(current.clip, attempt)} className={`overflow-hidden rounded border text-left transition-colors disabled:opacity-50 ${selected ? 'border-emerald-400 bg-emerald-500/10' : 'border-border bg-bg-secondary hover:border-violet-400/60'}`}>
                <div className="relative aspect-video bg-black"><img src={api.getOutputThumbnailUrl(attempt.filename, pipeline.workspace)} alt={t('timeline.versionAlt', { version: attemptIndex + 1, clip: current.index + 1 })} className="h-full w-full object-contain" loading="lazy" />{selected && <span className="absolute right-1 top-1 inline-flex items-center gap-1 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[8px] text-white"><Check size={8} />{t('timeline.inAssemblyBadge')}</span>}{selectingAttempt === attempt.filename && <Loader2 size={16} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 animate-spin text-white" />}</div>
                <div className="p-1.5"><div className="truncate text-[9px] font-medium text-text-primary">{t('timeline.versionWithSource', { n: attemptIndex + 1, source: attempt.source || t('timeline.historical') })}</div><div className="mt-0.5 truncate text-[8px] text-text-muted">{t('timeline.seed', { seed: attempt.seed ?? '—' })}{attempt.created_at ? ` · ${new Date(attempt.created_at * 1000).toLocaleString()}` : ''}</div></div>
              </button>
            })}</div>
          </div>
        </div> : <div className="flex items-center justify-center bg-black/80 p-6 text-[10px] text-text-muted">{t('timeline.noPlayableClip')}</div>}
      </div>}
    </div>}
  </div>
}
