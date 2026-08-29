import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Download, Edit3, ExternalLink, Film, Loader2, Play, RotateCcw, Save, Square, X } from 'lucide-react'
import * as api from '../../api/client'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import { useStore } from '../../stores/useStore'
import { orderedTimelineShots, reconcilePlaybackCursor, safeTimelineAttempt, seriesEditorCanvas } from '../../lib/orderedClipTimeline'
import { Pill, SectionCard } from './components'
import { SeriesShotDurationControl } from './SeriesShotDurationControl'
import { greenButton, primaryButton, secondaryButton } from './styles'
import type { SeriesAssemblyJob, SeriesEpisode, SeriesJobStatus, SeriesProject, SeriesRenderAttempt, SeriesShot } from './types'

function AttemptPreview({ series, attempt, approved, onApprove, onReject }: {
  series: SeriesProject; attempt: SeriesRenderAttempt; approved: boolean; onApprove: () => void; onReject: () => void
}) {
  const [open, setOpen] = useState(false)
  const asset = attempt.outputAssetIds.map(id => series.assets[id]).find(Boolean)
  const filename = asset?.uri.replace(/^outputs\//, '')
  const url = filename ? api.getFileUrl(filename, asset?.workspaceId) : ''
  return <div className={`rounded-lg border p-2 ${approved ? 'border-green-500/40 bg-green-500/10' : 'border-border bg-bg-primary'}`}>
    <div className="flex items-center gap-2"><Pill tone={attempt.status === 'completed' ? 'green' : attempt.status === 'failed' ? 'red' : 'violet'}>{attempt.status}</Pill>{attempt.reviewDecision && <Pill tone={attempt.reviewDecision === 'approved' ? 'green' : 'red'}>{attempt.reviewDecision}</Pill>}<span className="text-[10px] text-text-muted">seed {attempt.seed ?? 'random'} · {(Number(attempt.elapsedMs || 0) / 1000).toFixed(1)}s · {attempt.model}</span></div>
    {url && (open ? <video className="mt-2 max-h-64 w-full rounded bg-black" src={url} controls autoPlay preload="metadata" /> : <button className="relative mt-2 flex h-28 w-full items-center justify-center overflow-hidden rounded bg-black/70 text-xs text-white" onClick={() => setOpen(true)}><img src={api.getOutputThumbnailUrl(filename || '', asset?.workspaceId)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover opacity-70" /><span className="relative flex items-center rounded-full bg-black/70 px-3 py-2"><Play size={18} className="mr-2" />Load video preview</span></button>)}
    {attempt.error && <p className="mt-2 text-[10px] text-red-300">{attempt.error}</p>}
    <details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">Saved generation request and result metadata</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify({ prompt: attempt.prompt, negativePrompt: attempt.negativePrompt, model: attempt.model, seed: attempt.seed, settings: attempt.settings, references: attempt.referenceManifest, createdAt: attempt.createdAt, submittedAt: attempt.submittedAt, completedAt: attempt.completedAt, elapsedMs: attempt.elapsedMs }, null, 2)}</pre></details>
    {attempt.status === 'completed' && !approved && <div className="mt-2 flex gap-2"><button className={greenButton} onClick={onApprove}><Check size={12} />Approve this attempt</button><button className={secondaryButton} onClick={onReject}><X size={12} />Reject</button></div>}
  </div>
}

export function SeriesReviewPanel({
  workspace, series, episode, job, setJob, reload, startRender, updateEpisode, saveNow,
}: {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  job: SeriesJobStatus | null
  setJob: (job: SeriesJobStatus | null) => void
  reload: () => Promise<void>
  startRender: (mode: 'selected' | 'missing' | 'failed' | 'all', shotIds?: string[], seed?: number) => Promise<void>
  updateEpisode: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  saveNow: () => Promise<SeriesProject | null>
}) {
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const [error, setError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, 'pending' | 'accepted' | 'rejected'>>({})
  const [approvalProgress, setApprovalProgress] = useState<{ current: number; total: number } | null>(null)
  const [playbackShotId, setPlaybackShotId] = useState<string | null>(null)
  const [playingAll, setPlayingAll] = useState(false)
  const [focusShotId, setFocusShotId] = useState(episode.shots[0]?.id || '')
  const [previewAttemptByShot, setPreviewAttemptByShot] = useState<Record<string, string>>({})
  const [editingShotId, setEditingShotId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<Pick<SeriesShot,
    'durationSeconds' | 'framing' | 'action' | 'camera' | 'prompt' | 'negativePrompt'
    | 'dialogueBeats' | 'dialogueDuration' | 'renderStrategy'> | null>(null)
  const [editSeed, setEditSeed] = useState('')
  const [editBusy, setEditBusy] = useState(false)
  const [assemblyJob, setAssemblyJob] = useState<SeriesAssemblyJob | null>(null)
  const [reviewView, setReviewView] = useState<'assembly' | 'history' | 'finish'>('assembly')
  const playerRef = useRef<HTMLVideoElement>(null)
  const lastPlayerRef = useRef<HTMLVideoElement>(null)
  const activeJobId = job?.jobId
  const activeJobStatus = job?.status
  const assemblyJobId = assemblyJob?.jobId
  const assemblyJobStatus = assemblyJob?.status
  const episodeIdRef = useRef(episode.id)
  episodeIdRef.current = episode.id
  const lastRenderCurrentRef = useRef<number | null>(null)
  const previousEpisodeId = useRef(episode.id)
  const episodeChanged = previousEpisodeId.current !== episode.id
  useEffect(() => {
    if (!episodeChanged) return
    previousEpisodeId.current = episode.id
    const activePlayer = playerRef.current || lastPlayerRef.current
    activePlayer?.pause()
    lastPlayerRef.current = null
    setError(null)
    setDecisions({})
    setApprovalProgress(null)
    setPlaybackShotId(null)
    setPlayingAll(false)
    setFocusShotId(episode.shots[0]?.id || '')
    setPreviewAttemptByShot({})
    setEditingShotId(null)
    setEditDraft(null)
    setEditSeed('')
    setEditBusy(false)
    setAssemblyJob(null)
    setReviewView('assembly')
    lastRenderCurrentRef.current = null
  }, [episode.id, episode.shots, episodeChanged])
  useSerializedPoll({
    enabled: Boolean(activeJobId && activeJobStatus && ['queued', 'running', 'cancelling'].includes(activeJobStatus)),
    intervalMs: 1000,
    ownerKey: `${episode.id}:${activeJobId || ''}`,
    poll: () => api.fetchSeriesRenderJob(activeJobId!),
    onValue: value => {
      if (episodeIdRef.current !== episode.id) return
      const previous = lastRenderCurrentRef.current
      lastRenderCurrentRef.current = value.current
      setJob(value)
      const terminal = ['completed', 'failed', 'cancelled'].includes(value.status)
      if (terminal || (previous !== null && value.current !== previous)) void reload()
    },
    onError: reason => {
      if (episodeIdRef.current === episode.id) setError((reason as Error).message)
    },
  })
  useSerializedPoll({
    enabled: Boolean(assemblyJobId && assemblyJobStatus && ['queued', 'running', 'cancelling'].includes(assemblyJobStatus)),
    intervalMs: 1000,
    ownerKey: `${episode.id}:${assemblyJobId || ''}`,
    poll: () => api.fetchSeriesEpisodeAssembly(assemblyJobId!, workspace),
    onValue: value => {
      if (episodeIdRef.current !== episode.id) return
      setAssemblyJob(value)
      if (value.status === 'completed') void reload()
    },
    onError: reason => {
      if (episodeIdRef.current === episode.id) setError((reason as Error).message)
    },
  })
  const approved = useMemo(() => episode.shots.flatMap(shot => {
    const attempt = shot.attempts.find(item => item.id === shot.approvedAttemptId)
    const asset = attempt?.outputAssetIds.map(id => series.assets[id]).find(Boolean)
    return attempt && asset ? [{ shot, attempt, asset }] : []
  }).sort((left, right) => left.shot.order - right.shot.order), [episode.shots, series.assets])
  const playable = useMemo(() => episode.shots
    .slice()
    .sort((left, right) => left.order - right.order)
    .flatMap(shot => {
      const selected = safeTimelineAttempt(shot, id => Boolean(series.assets[id]))
      const asset = selected?.outputAssetIds.map(id => series.assets[id]).find(Boolean)
      return selected && asset ? [{ shotId: shot.id, shot, attempt: selected, asset }] : []
    }), [episode.shots, series.assets])
  const approvable = useMemo(() => episode.shots
    .slice()
    .sort((left, right) => left.order - right.order)
    .flatMap(shot => {
      const attempt = [...shot.attempts].reverse().find(item => (
        item.status === 'completed'
        && item.reviewDecision !== 'rejected'
        && item.outputAssetIds.some(id => Boolean(series.assets[id]))
      ))
      return attempt && attempt.id !== shot.approvedAttemptId
        ? [{ shotId: shot.id, attemptId: attempt.id }] : []
    }), [episode.shots, series.assets])
  const playbackCursor = reconcilePlaybackCursor(playbackShotId, playable)
  const playIndex = playbackCursor.index
  const currentPlayback = playIndex >= 0 ? playable[playIndex] : undefined
  const sortedShots = useMemo(() => orderedTimelineShots(episode.shots), [episode.shots])
  const focusShot = sortedShots.find(shot => shot.id === focusShotId) || sortedShots[0]
  const focusAttempt = focusShot && (
    focusShot.attempts.find(attempt => attempt.id === previewAttemptByShot[focusShot.id])
    || [...focusShot.attempts].reverse().find(attempt => attempt.status === 'completed'
      && attempt.reviewDecision !== 'rejected'
      && attempt.outputAssetIds.some(id => Boolean(series.assets[id])))
    || focusShot.attempts.find(attempt => attempt.id === focusShot.approvedAttemptId)
  )
  const focusAsset = focusAttempt?.outputAssetIds.map(id => series.assets[id]).find(Boolean)
  const focusedPlayback = focusShot && focusAttempt && focusAsset
    ? { shot: focusShot, attempt: focusAttempt, asset: focusAsset } : undefined
  const displayPlayback = playingAll ? currentPlayback : focusedPlayback
  const currentPlaybackAttemptId = displayPlayback?.attempt.id
  useEffect(() => {
    if (episodeChanged) return
    if (!playingAll) return
    if (playbackCursor.outcome === 'stop' || !currentPlaybackAttemptId) {
      setPlayingAll(false)
      setPlaybackShotId(null)
      setError('Play all stopped because the active shot is no longer playable.')
      return
    }
    if (!playerRef.current) return
    playerRef.current.currentTime = 0
    void playerRef.current.play().catch(reason => {
      setPlayingAll(false)
      setError(`Play all could not continue: ${(reason as Error).message}`)
    })
  }, [currentPlaybackAttemptId, episodeChanged, playbackCursor.outcome, playingAll])
  useEffect(() => {
    if (!focusShotId && sortedShots[0]) setFocusShotId(sortedShots[0].id)
  }, [focusShotId, sortedShots])
  const openEditor = () => {
    if (approved.length !== episode.shots.length) return
    const resolution = seriesEditorCanvas(
      series.provider.videoSettings.resolution,
      series.provider.videoSettings.orientation,
    )
    const clips = approved.map(({ shot, asset }) => ({
      name: `${episode.title} · Shot ${shot.order}`,
      url: api.getFileUrl(asset.uri.replace(/^outputs\//, ''), asset.workspaceId),
    }))
    window.localStorage.setItem('maestro-video-editor-pending-sequence', JSON.stringify({
      projectName: `${series.title} · ${episode.title}`, resolution, clips,
    }))
    setMediaFilter('videoeditor')
  }
  const approve = async (shotId: string, attemptId: string) => {
    setError(null)
    try { await api.approveSeriesAttempt(workspace, series.id, episode.id, shotId, attemptId); await reload() }
    catch (reason) { setError((reason as Error).message) }
  }
  const approveAll = async () => {
    if (!approvable.length || approvalProgress) return
    setError(null)
    setApprovalProgress({ current: 0, total: approvable.length })
    try {
      await api.approveSeriesAttemptsBulk(workspace, series.id, episode.id, approvable)
      setApprovalProgress({ current: approvable.length, total: approvable.length })
      await reload()
    } catch (reason) {
      setError(`Approve all did not change any shot: ${(reason as Error).message}`)
    } finally {
      setApprovalProgress(null)
    }
  }
  const stopPlayAll = () => {
    playerRef.current?.pause()
    setPlayingAll(false)
    setPlaybackShotId(null)
  }
  const startPlayAll = () => {
    if (!playable.length || playingAll) return
    setError(null)
    setPlaybackShotId(playable[0].shotId)
    setPlayingAll(true)
    if (playerRef.current) {
      playerRef.current.currentTime = 0
      void playerRef.current.play().catch(reason => {
        setPlayingAll(false)
        setError(`Play all could not start: ${(reason as Error).message}`)
      })
    }
  }
  const advancePlayAll = () => {
    if (playIndex + 1 < playable.length) {
      setPlaybackShotId(playable[playIndex + 1].shotId)
      return
    }
    setPlayingAll(false)
    setPlaybackShotId(null)
  }
  const focusSlot = (shotId: string) => {
    setPlayingAll(false)
    setFocusShotId(shotId)
    if (playable.some(item => item.shotId === shotId)) setPlaybackShotId(shotId)
  }
  const beginEdit = (shot: SeriesShot) => {
    setEditingShotId(shot.id)
    setEditSeed('')
    setEditDraft({
      durationSeconds: shot.durationSeconds, framing: shot.framing,
      action: shot.action, camera: shot.camera, prompt: shot.prompt,
      negativePrompt: shot.negativePrompt,
      dialogueBeats: structuredClone(shot.dialogueBeats),
      dialogueDuration: structuredClone(shot.dialogueDuration),
      renderStrategy: shot.renderStrategy,
    })
  }
  const regenerateEdited = async () => {
    if (!editingShotId || !editDraft || editBusy) return
    setEditBusy(true); setError(null)
    try {
      updateEpisode(current => ({
        ...current,
        shots: current.shots.map(shot => shot.id === editingShotId ? { ...shot, ...editDraft } : shot),
      }))
      await saveNow()
      const parsedSeed = editSeed.trim() ? Number(editSeed) : undefined
      if (parsedSeed !== undefined && !Number.isInteger(parsedSeed)) throw new Error('Seed must be an integer')
      setPreviewAttemptByShot(current => {
        const next = { ...current }
        delete next[editingShotId]
        return next
      })
      setFocusShotId(editingShotId)
      await startRender('selected', [editingShotId], parsedSeed)
      setEditingShotId(null); setEditDraft(null)
    } catch (reason) { setError((reason as Error).message) }
    finally { setEditBusy(false) }
  }
  const joinApproved = async () => {
    setError(null)
    try { setAssemblyJob(await api.startSeriesEpisodeAssembly(workspace, series.id, episode.id)) }
    catch (reason) { setError((reason as Error).message) }
  }
  const reject = async (shotId: string, attemptId: string) => {
    setError(null)
    try { await api.rejectSeriesAttempt(workspace, series.id, episode.id, shotId, attemptId); await reload() }
    catch (reason) { setError((reason as Error).message) }
  }
  const commit = async () => {
    setError(null)
    try {
      await api.commitSeriesCanon(
        workspace, series.id, episode.id, episode.proposedCanonDelta.baseRevision, decisions,
      )
      await reload()
    } catch (reason) { setError((reason as Error).message) }
  }
  const deltas = [
    ...episode.proposedCanonDelta.add.map(item => ({ id: item.id, label: `Add · ${item.description}` })),
    ...episode.proposedCanonDelta.change.map(item => ({ id: item.id, label: `Change · ${item.description}` })),
    ...episode.proposedCanonDelta.retire.map(item => ({ id: item.factId, label: `Retire · ${item.factId}` })),
  ]
  return <div className="space-y-4 pb-10">
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
    <div className="sticky top-0 z-10 flex flex-wrap gap-2 rounded-xl border border-border bg-bg-secondary/95 p-2 shadow-lg backdrop-blur">
      {([
        ['assembly', 'Montaje ordenado', `${playable.length}/${episode.shots.length}`],
        ['history', 'Historial e intentos', `${episode.shots.reduce((total, shot) => total + shot.attempts.length, 0)}`],
        ['finish', 'Finalizar y canon', `${approved.length}/${episode.shots.length}`],
      ] as const).map(([id, label, count]) => <button key={id} className={`rounded-lg border px-3 py-2 text-xs ${reviewView === id ? 'border-violet-400 bg-violet-500/20 text-violet-100' : 'border-border bg-bg-primary text-text-muted hover:bg-bg-hover'}`} onClick={() => setReviewView(id)}>{label}<span className="ml-2 rounded bg-black/20 px-1.5 py-0.5 text-[9px]">{count}</span></button>)}
    </div>
    <SectionCard title="Durable render queue" description="Completed shots survive cancellation and restart. Approved shots are never included in bulk missing/failed runs.">
      <div className="flex flex-wrap gap-2"><button className={primaryButton} disabled={Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))} onClick={() => void startRender('missing')}><Film size={13} />Generate missing</button><button className={secondaryButton} disabled={Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))} onClick={() => void startRender('failed')}><RotateCcw size={13} />Retry failed</button>{job && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => {
        const episodeId = episode.id
        const jobId = job.jobId
        void api.cancelSeriesRenderJob(jobId).then(value => {
          if (episodeIdRef.current === episodeId && value.jobId === jobId) setJob(value)
        })
      }}><Square size={13} />Cancel generation</button>}</div>
      {job && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3"><div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<Pill tone={job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : 'violet'}>{job.status}</Pill><span>{job.message}</span><span className="ml-auto">{job.current}/{job.total}</span></div>{job.items && <div className="mt-2 flex flex-wrap gap-1">{job.items.map(item => <Pill key={item.attemptId} tone={item.status === 'completed' ? 'green' : item.status === 'failed' ? 'red' : item.status === 'running' || item.status === 'cancelling' ? 'violet' : 'neutral'}>{item.shotId} · {item.status}</Pill>)}</div>}{job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}{(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-2 ${secondaryButton}`} onClick={() => {
        const episodeId = episode.id
        const jobId = job.jobId
        void api.resumeSeriesRenderJob(jobId).then(value => {
          if (episodeIdRef.current === episodeId && value.jobId === jobId) setJob(value)
        })
      }}>Resume incomplete queue</button>}</div>}
    </SectionCard>

    {reviewView === 'history' && <SectionCard title="Shot attempt history" description="Each shot keeps its immutable generation history. The latest completed alternative occupies the same ordered slot; approving it changes the final export.">
      <div className="space-y-3">{sortedShots.map(shot => { const latest = [...shot.attempts].reverse()[0]; const approvedAttempt = shot.attempts.find(attempt => attempt.id === shot.approvedAttemptId); const primaryAttempts = [approvedAttempt, latest].filter((attempt, index, values): attempt is SeriesRenderAttempt => Boolean(attempt) && values.findIndex(value => value?.id === attempt?.id) === index); const history = shot.attempts.filter(attempt => !primaryAttempts.some(primary => primary.id === attempt.id)); return <div key={shot.id} className="rounded-xl border border-border p-3"><div className="mb-2 flex flex-wrap items-center gap-2"><Pill tone="blue">Shot {shot.order}</Pill><span className="min-w-0 flex-1 text-xs text-text-secondary">{shot.action}</span>{shot.approvedAttemptId && <Pill tone="green">approved</Pill>}<button className={secondaryButton} onClick={() => beginEdit(shot)}><Edit3 size={12} />Edit & regenerate</button></div><div className="grid gap-2 xl:grid-cols-2">{primaryAttempts.map(attempt => <AttemptPreview key={attempt.id} series={series} attempt={attempt} approved={shot.approvedAttemptId === attempt.id} onApprove={() => void approve(shot.id, attempt.id)} onReject={() => void reject(shot.id, attempt.id)} />)}</div>{history.length > 0 && <details className="mt-2"><summary className="cursor-pointer text-[10px] text-text-muted">Show {history.length} older attempt{history.length === 1 ? '' : 's'}</summary><div className="mt-2 grid gap-2 xl:grid-cols-2">{history.map(attempt => <AttemptPreview key={attempt.id} series={series} attempt={attempt} approved={false} onApprove={() => void approve(shot.id, attempt.id)} onReject={() => void reject(shot.id, attempt.id)} />)}</div></details>}{!shot.attempts.length && <p className="text-[10px] text-text-muted">No render attempt yet.</p>}</div> })}</div>
    </SectionCard>}

    {reviewView === 'assembly' && <SectionCard title="Montaje ordenado del episodio" description={`${playable.length}/${episode.shots.length} posiciones tienen vídeo. Al terminar una regeneración correcta, el nuevo intento sustituye automáticamente al anterior en esta posición; el antiguo queda en Historial.`}>
      <div className="flex flex-wrap gap-2">
        <button className={greenButton} disabled={!approvable.length || Boolean(approvalProgress)} onClick={() => void approveAll()}>
          {approvalProgress ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
          {approvalProgress ? `Approving ${approvalProgress.current}/${approvalProgress.total}` : `Approve all (${approvable.length})`}
        </button>
        <button className={primaryButton} disabled={!playable.length || playingAll} onClick={startPlayAll}><Play size={13} />Play all</button>
        {playingAll && <button className={secondaryButton} onClick={stopPlayAll}><Square size={13} />Stop</button>}
        <button className={greenButton} disabled={approved.length !== episode.shots.length || Boolean(assemblyJob && ['queued', 'running', 'cancelling'].includes(assemblyJob.status))} onClick={() => void joinApproved()}>{assemblyJob && ['queued', 'running', 'cancelling'].includes(assemblyJob.status) ? <Loader2 size={13} className="animate-spin" /> : <Film size={13} />}Join clips</button>
      </div>
      <p className="mt-2 text-[10px] text-text-muted">Approve all skips incomplete and explicitly rejected attempts. Existing approvals are kept.</p>
      <div className="mt-3 grid min-h-[28rem] overflow-hidden rounded-xl border border-border lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="max-h-[70vh] overflow-y-auto border-b border-border bg-bg-secondary p-2 lg:border-b-0 lg:border-r">{sortedShots.map(shot => { const safe = playable.find(item => item.shot.id === shot.id); const queuedItem = job?.items?.find(item => item.shotId === shot.id && ['queued', 'running', 'cancelling'].includes(item.status)); const selected = displayPlayback?.shot.id === shot.id; return <button key={shot.id} onClick={() => focusSlot(shot.id)} className={`mb-2 w-full rounded-lg border p-2 text-left ${selected ? 'border-violet-400 bg-violet-500/20' : 'border-border bg-bg-primary hover:bg-bg-hover'}`}><div className="flex items-center gap-2"><Pill tone={selected && playingAll ? 'violet' : shot.approvedAttemptId ? 'green' : safe ? 'blue' : 'neutral'}>Shot {shot.order}</Pill>{queuedItem && <Pill tone="violet">{queuedItem.status}</Pill>}<span className="ml-auto text-[9px] text-text-muted">{shot.durationSeconds}s · {shot.attempts.length} tries</span></div><p className="mt-1 line-clamp-2 text-[10px] text-text-secondary">{shot.action || shot.prompt || 'Empty shot'}</p><div className="mt-2 flex gap-1"><span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[9px] text-text-muted">{safe ? 'playable' : 'missing'}</span>{shot.approvedAttemptId && <span className="rounded bg-green-500/15 px-1.5 py-0.5 text-[9px] text-green-300">final</span>}{queuedItem && <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[9px] text-violet-200">will replace this slot</span>}</div></button> })}</div>
      {displayPlayback ? <div className="min-w-0 bg-black">
        <video
          key={displayPlayback.attempt.id}
          ref={node => {
            playerRef.current = node
            if (node) lastPlayerRef.current = node
          }}
          className="max-h-[70vh] w-full bg-black"
          src={api.getFileUrl(displayPlayback.asset.uri.replace(/^outputs\//, ''), displayPlayback.asset.workspaceId)}
          controls
          preload="metadata"
          autoPlay={playingAll}
          onEnded={() => { if (playingAll) advancePlayAll() }}
          onError={() => {
            setError(`Shot ${displayPlayback.shot.order} could not be played${playingAll ? '; continuing with the next available shot.' : '.'}`)
            if (playingAll) advancePlayAll()
          }}
        />
        <div className="flex flex-wrap items-center gap-2 bg-bg-primary px-3 py-2 text-xs text-text-secondary">
          <Pill tone={playingAll ? 'violet' : 'neutral'}>{playingAll ? 'playing sequence' : 'ready'}</Pill>
          <span>Shot {displayPlayback.shot.order}{playingAll ? ` · ${playIndex + 1}/${playable.length}` : ''}</span>
          <span className="text-text-muted">{displayPlayback.shot.action}</span>
          <button className={`ml-auto ${secondaryButton}`} onClick={() => beginEdit(displayPlayback.shot)}><Edit3 size={12} />Edit</button>
        </div>
        <div className="border-t border-border bg-bg-primary p-3"><div className="mb-2 text-[10px] font-medium text-text-secondary">Attempts in this slot</div><div className="flex flex-wrap gap-1">{displayPlayback.shot.attempts.map(attempt => <button key={attempt.id} className={`rounded px-2 py-1 text-[9px] ${attempt.id === displayPlayback.attempt.id ? 'bg-violet-500/25 text-violet-100' : attempt.reviewDecision === 'rejected' ? 'bg-red-500/10 text-red-300' : 'bg-bg-tertiary text-text-muted'}`} onClick={() => setPreviewAttemptByShot(current => ({ ...current, [displayPlayback.shot.id]: attempt.id }))}>try {attempt.retryCount + 1}{attempt.id === displayPlayback.shot.approvedAttemptId ? ' · final' : ''}</button>)}</div></div>
      </div> : <div className="flex items-center justify-center bg-black/80 p-8 text-center text-xs text-text-muted">This slot does not have a playable video yet.</div>}
      </div>
      {editingShotId && editDraft && (() => {
        const sourceShot = sortedShots.find(item => item.id === editingShotId)
        if (!sourceShot) return null
        return <div className="mt-3 rounded-xl border border-violet-500/30 bg-violet-500/10 p-3">
          <div className="flex items-center">
            <h4 className="text-xs font-semibold text-violet-100">Edit source data · shot {sourceShot.order}</h4>
            <button className={`ml-auto ${secondaryButton}`} onClick={() => { setEditingShotId(null); setEditDraft(null) }}><X size={12} />Close</button>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <SeriesShotDurationControl
              workspace={workspace}
              series={series}
              shot={{ ...sourceShot, ...editDraft }}
              onChange={planned => setEditDraft(current => current && ({
                ...current,
                durationSeconds: planned.durationSeconds,
                dialogueDuration: planned.dialogueDuration,
              }))}
            />
            <label className="text-[10px] text-text-muted">Render strategy<select className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.renderStrategy} onChange={event => setEditDraft(current => current && ({ ...current, renderStrategy: event.target.value as SeriesShot['renderStrategy'] }))}><option value="auto">Automatic</option><option value="direct">Direct</option><option value="first_frame">First frame</option><option value="references">References</option><option value="first_last">First + last frame</option></select></label>
            <label className="text-[10px] text-text-muted">Framing<input className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.framing} onChange={event => setEditDraft(current => current && ({ ...current, framing: event.target.value }))} /></label>
            <label className="text-[10px] text-text-muted">Seed override (optional)<input className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editSeed} onChange={event => setEditSeed(event.target.value)} inputMode="numeric" /></label>
            <label className="text-[10px] text-text-muted">Action<textarea className="mt-1 min-h-20 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.action} onChange={event => setEditDraft(current => current && ({ ...current, action: event.target.value }))} /></label>
            <label className="text-[10px] text-text-muted">Camera<textarea className="mt-1 min-h-20 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.camera} onChange={event => setEditDraft(current => current && ({ ...current, camera: event.target.value }))} /></label>
            <label className="text-[10px] text-text-muted md:col-span-2">Prompt<textarea className="mt-1 min-h-28 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.prompt} onChange={event => setEditDraft(current => current && ({ ...current, prompt: event.target.value }))} /></label>
            <label className="text-[10px] text-text-muted md:col-span-2">Negative prompt<textarea className="mt-1 min-h-20 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={editDraft.negativePrompt} onChange={event => setEditDraft(current => current && ({ ...current, negativePrompt: event.target.value }))} /></label>
            {editDraft.dialogueBeats.map((beat, index) => <div key={beat.id} className="grid gap-2 rounded border border-border p-2 md:col-span-2 md:grid-cols-2"><label className="text-[10px] text-text-muted md:col-span-2">Dialogue {index + 1}<textarea className="mt-1 min-h-16 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={beat.text} onChange={event => setEditDraft(current => current && ({ ...current, dialogueBeats: current.dialogueBeats.map(item => item.id === beat.id ? { ...item, text: event.target.value } : item) }))} /></label><label className="text-[10px] text-text-muted">Emotion<input className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={beat.emotion} onChange={event => setEditDraft(current => current && ({ ...current, dialogueBeats: current.dialogueBeats.map(item => item.id === beat.id ? { ...item, emotion: event.target.value } : item) }))} /></label><label className="text-[10px] text-text-muted">Delivery<input className="mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs text-text-primary" value={beat.delivery} onChange={event => setEditDraft(current => current && ({ ...current, dialogueBeats: current.dialogueBeats.map(item => item.id === beat.id ? { ...item, delivery: event.target.value } : item) }))} /></label></div>)}
          </div>
          <button className={`mt-3 ${greenButton}`} disabled={editBusy} onClick={() => void regenerateEdited()}>{editBusy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}Save and regenerate in this slot</button>
        </div>
      })()}
      {assemblyJob && <div className={`mt-3 rounded-lg border p-3 text-xs ${['failed', 'interrupted'].includes(assemblyJob.status) ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-green-500/30 bg-green-500/10 text-green-200'}`}><div className="flex flex-wrap items-center gap-2">{['queued', 'running', 'cancelling'].includes(assemblyJob.status) && <Loader2 size={13} className="animate-spin" />}<span>{assemblyJob.message}</span>{assemblyJob.filename && <a className={`ml-auto ${greenButton}`} href={api.getFileUrl(assemblyJob.filename, workspace)} download><Download size={13} />Download joined episode</a>}{['queued', 'running'].includes(assemblyJob.status) && <button className={secondaryButton} onClick={() => {
              const episodeId = episode.id
              const jobId = assemblyJob.jobId
              void api.cancelSeriesEpisodeAssembly(jobId, workspace).then(value => {
                if (episodeIdRef.current === episodeId && value.jobId === jobId) setAssemblyJob(value)
              })
            }}><Square size={13} />Cancel join</button>}{['failed', 'cancelled', 'interrupted'].includes(assemblyJob.status) && <button className={secondaryButton} onClick={() => {
              const episodeId = episode.id
              const jobId = assemblyJob.jobId
              void api.resumeSeriesEpisodeAssembly(jobId, workspace).then(value => {
                if (episodeIdRef.current === episodeId && value.jobId === jobId) setAssemblyJob(value)
              })
            }}><RotateCcw size={13} />Resume join</button>}{['failed', 'cancelled', 'interrupted'].includes(assemblyJob.status) && <button className={secondaryButton} onClick={() => {
              const episodeId = episode.id
              void api.discardSeriesEpisodeAssembly(assemblyJob.jobId, workspace).then(() => {
                if (episodeIdRef.current === episodeId) setAssemblyJob(null)
              })
            }}><X size={12} />Discard checkpoint</button>}</div>{assemblyJob.error && <p className="mt-1 text-[10px]">{assemblyJob.error}</p>}</div>}
    </SectionCard>}

    {reviewView === 'finish' && <><SectionCard title="Video Editor hand-off" description={`${approved.length}/${episode.shots.length} shots have an approved output. The editor opens with the saved Series resolution and orientation.`}>
      <button className={greenButton} disabled={!episode.shots.length || approved.length !== episode.shots.length} onClick={openEditor}><ExternalLink size={13} />Open complete approved sequence in Video Editor</button>
      {approved.length > 0 && approved.length < episode.shots.length && <p className="mt-2 text-[10px] text-amber-300">Approve every shot before opening the final sequence. This prevents an accidental partial export.</p>}
    </SectionCard>

    <SectionCard title="Proposed canon delta" description="Only accepted items affect future episode snapshots. Rejected/pending items never mutate canon.">
      <div className="space-y-2">{deltas.map(item => <div key={item.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2"><span className="flex-1 text-xs text-text-secondary">{item.label}</span>{(['pending', 'accepted', 'rejected'] as const).map(decision => <button key={decision} className={`rounded px-2 py-1 text-[10px] ${decisions[item.id] === decision || (!decisions[item.id] && decision === 'pending') ? 'bg-violet-500/20 text-violet-200' : 'bg-bg-tertiary text-text-muted'}`} onClick={() => setDecisions(current => ({ ...current, [item.id]: decision }))}>{decision}</button>)}</div>)}</div>
      {!deltas.length && <p className="text-xs text-text-muted">No continuity change was proposed.</p>}
      {deltas.length > 0 && <button className={`mt-3 ${greenButton}`} onClick={() => void commit()}><Check size={13} />Commit selected canon changes</button>}
    </SectionCard></>}
  </div>
}
