import { useEffect, useMemo, useState } from 'react'
import { Check, ExternalLink, Film, Loader2, Play, RotateCcw, Square, X } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { Pill, SectionCard } from './components'
import { greenButton, primaryButton, secondaryButton } from './styles'
import type { SeriesEpisode, SeriesJobStatus, SeriesProject, SeriesRenderAttempt } from './types'

function AttemptPreview({ series, attempt, approved, onApprove, onReject }: {
  series: SeriesProject; attempt: SeriesRenderAttempt; approved: boolean; onApprove: () => void; onReject: () => void
}) {
  const [open, setOpen] = useState(false)
  const asset = attempt.outputAssetIds.map(id => series.assets[id]).find(Boolean)
  const filename = asset?.uri.replace(/^outputs\//, '')
  const url = filename ? api.getFileUrl(filename) : ''
  return <div className={`rounded-lg border p-2 ${approved ? 'border-green-500/40 bg-green-500/10' : 'border-border bg-bg-primary'}`}>
    <div className="flex items-center gap-2"><Pill tone={attempt.status === 'completed' ? 'green' : attempt.status === 'failed' ? 'red' : 'violet'}>{attempt.status}</Pill>{attempt.reviewDecision && <Pill tone={attempt.reviewDecision === 'approved' ? 'green' : 'red'}>{attempt.reviewDecision}</Pill>}<span className="text-[10px] text-text-muted">seed {attempt.seed ?? 'random'} · {(attempt.elapsedMs / 1000).toFixed(1)}s · {attempt.model}</span></div>
    {url && (open ? <video className="mt-2 max-h-64 w-full rounded bg-black" src={url} controls autoPlay preload="metadata" /> : <button className="relative mt-2 flex h-28 w-full items-center justify-center overflow-hidden rounded bg-black/70 text-xs text-white" onClick={() => setOpen(true)}><img src={api.getOutputThumbnailUrl(filename || '')} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover opacity-70" /><span className="relative flex items-center rounded-full bg-black/70 px-3 py-2"><Play size={18} className="mr-2" />Load video preview</span></button>)}
    {attempt.error && <p className="mt-2 text-[10px] text-red-300">{attempt.error}</p>}
    <details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">Exact generation metadata</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify({ prompt: attempt.prompt, negativePrompt: attempt.negativePrompt, model: attempt.model, seed: attempt.seed, settings: attempt.settings, references: attempt.referenceManifest, createdAt: attempt.createdAt, submittedAt: attempt.submittedAt, completedAt: attempt.completedAt, elapsedMs: attempt.elapsedMs }, null, 2)}</pre></details>
    {attempt.status === 'completed' && !approved && <div className="mt-2 flex gap-2"><button className={greenButton} onClick={onApprove}><Check size={12} />Approve this attempt</button><button className={secondaryButton} onClick={onReject}><X size={12} />Reject</button></div>}
  </div>
}

export function SeriesReviewPanel({
  workspace, series, episode, job, setJob, reload, startRender,
}: {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  job: SeriesJobStatus | null
  setJob: (job: SeriesJobStatus | null) => void
  reload: () => Promise<void>
  startRender: (mode: 'selected' | 'missing' | 'failed' | 'all', shotIds?: string[]) => Promise<void>
}) {
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const [error, setError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, 'pending' | 'accepted' | 'rejected'>>({})
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.fetchSeriesRenderJob(job.jobId).then(async value => {
        if (!active) return
        setJob(value)
        if (['completed', 'failed', 'cancelled'].includes(value.status)) await reload()
      }).catch(reason => { if (active) setError((reason as Error).message) })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [job, reload, setJob])
  const approved = useMemo(() => episode.shots.flatMap(shot => {
    const attempt = shot.attempts.find(item => item.id === shot.approvedAttemptId)
    const asset = attempt?.outputAssetIds.map(id => series.assets[id]).find(Boolean)
    return attempt && asset ? [{ shot, attempt, asset }] : []
  }).sort((left, right) => left.shot.order - right.shot.order), [episode.shots, series.assets])
  const openEditor = () => {
    const quality = String(series.provider.videoSettings.resolution || '480p').includes('720') ? '720p' : '480p'
    const portrait = series.provider.videoSettings.orientation === 'portrait'
    const resolution = quality === '720p'
      ? { label: portrait ? 'Portrait 720p' : 'Landscape 720p', width: portrait ? 720 : 1280, height: portrait ? 1280 : 720 }
      : { label: portrait ? 'Portrait 480p' : 'Landscape 480p', width: portrait ? 480 : 864, height: portrait ? 864 : 480 }
    const clips = approved.map(({ shot, asset }) => ({
      name: `${episode.title} · Shot ${shot.order}`,
      url: api.getFileUrl(asset.uri.replace(/^outputs\//, '')),
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
    <SectionCard title="Durable render queue" description="Completed shots survive cancellation and restart. Approved shots are never included in bulk missing/failed runs.">
      <div className="flex flex-wrap gap-2"><button className={primaryButton} disabled={Boolean(job && ['queued', 'running'].includes(job.status))} onClick={() => void startRender('missing')}><Film size={13} />Generate missing</button><button className={secondaryButton} disabled={Boolean(job && ['queued', 'running'].includes(job.status))} onClick={() => void startRender('failed')}><RotateCcw size={13} />Retry failed</button>{job && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesRenderJob(job.jobId).then(setJob)}><Square size={13} />Cancel generation</button>}</div>
      {job && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3"><div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<Pill tone={job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : 'violet'}>{job.status}</Pill><span>{job.message}</span><span className="ml-auto">{job.current}/{job.total}</span></div>{job.items && <div className="mt-2 flex flex-wrap gap-1">{job.items.map(item => <Pill key={item.attemptId} tone={item.status === 'completed' ? 'green' : item.status === 'failed' ? 'red' : item.status === 'running' ? 'violet' : 'neutral'}>{item.shotId} · {item.status}</Pill>)}</div>}{job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}{(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-2 ${secondaryButton}`} onClick={() => void api.resumeSeriesRenderJob(job.jobId).then(setJob)}>Resume incomplete queue</button>}</div>}
    </SectionCard>

    <SectionCard title="Shot attempts" description="Attempts are append-only. Preview loads video only when requested.">
      <div className="space-y-4">{episode.shots.map(shot => <div key={shot.id} className="rounded-xl border border-border p-3"><div className="mb-2 flex items-center gap-2"><Pill tone="blue">Shot {shot.order}</Pill><span className="text-xs text-text-secondary">{shot.action}</span>{shot.approvedAttemptId && <Pill tone="green">approved</Pill>}{!shot.approvedAttemptId && shot.attempts.some(attempt => attempt.reviewDecision === 'rejected') && <button className={`ml-auto ${secondaryButton}`} onClick={() => void startRender('selected', [shot.id])}><RotateCcw size={12} />Regenerate rejected shot</button>}</div><div className="grid gap-2 xl:grid-cols-2">{shot.attempts.map(attempt => <AttemptPreview key={attempt.id} series={series} attempt={attempt} approved={shot.approvedAttemptId === attempt.id} onApprove={() => void approve(shot.id, attempt.id)} onReject={() => void reject(shot.id, attempt.id)} />)}</div>{!shot.attempts.length && <p className="text-[10px] text-text-muted">No render attempt yet.</p>}</div>)}</div>
    </SectionCard>

    <SectionCard title="Video Editor hand-off" description={`${approved.length}/${episode.shots.length} shots have an approved output. The editor opens with the saved Series resolution and orientation.`}>
      <button className={greenButton} disabled={!approved.length} onClick={openEditor}><ExternalLink size={13} />Open approved sequence in Video Editor</button>
    </SectionCard>

    <SectionCard title="Proposed canon delta" description="Only accepted items affect future episode snapshots. Rejected/pending items never mutate canon.">
      <div className="space-y-2">{deltas.map(item => <div key={item.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2"><span className="flex-1 text-xs text-text-secondary">{item.label}</span>{(['pending', 'accepted', 'rejected'] as const).map(decision => <button key={decision} className={`rounded px-2 py-1 text-[10px] ${decisions[item.id] === decision || (!decisions[item.id] && decision === 'pending') ? 'bg-violet-500/20 text-violet-200' : 'bg-bg-tertiary text-text-muted'}`} onClick={() => setDecisions(current => ({ ...current, [item.id]: decision }))}>{decision}</button>)}</div>)}</div>
      {!deltas.length && <p className="text-xs text-text-muted">No continuity change was proposed.</p>}
      {deltas.length > 0 && <button className={`mt-3 ${greenButton}`} onClick={() => void commit()}><Check size={13} />Commit selected canon changes</button>}
    </SectionCard>
  </div>
}
