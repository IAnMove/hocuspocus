import { useEffect, useMemo, useState } from 'react'
import {
  Check, Combine, History, ImageIcon, Layers, Loader2,
  Pencil, Play, RefreshCw, Save,
} from 'lucide-react'
import * as api from '../../api/client'
import { getFileUrl } from '../../api/client'
import { useStore } from '../../stores/useStore'
import type { PipelineClipState, SavedPipelineState } from '../../types'
import {
  attemptsForClip, fileLabel, hydratePipelineQueue, pipelineBusy, pipelineCanLaunch,
  pipelineLabel, selectedAttempt, shotDuration, shotPrompt,
} from './queue'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-violet-400/50 bg-violet-500/15 px-2.5 py-1.5 text-xs text-violet-100 hover:bg-violet-500/25 disabled:opacity-40 disabled:cursor-not-allowed'

function formatDate(ts: number | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function statusTone(status: string): string {
  const value = status.toLowerCase()
  if (value === 'completed') return 'bg-green-500/20 text-indicator-success'
  if (['failed', 'crashed', 'cancelled'].includes(value)) return 'bg-red-500/20 text-red-300'
  if (['running', 'planning', 'queued', 'resuming'].includes(value)) return 'bg-blue-500/20 text-chip-blue'
  return 'bg-bg-tertiary text-text-muted'
}

function audioPlanLabel(clip: PipelineClipState): string {
  const plan = clip._director_audio_plan || (clip.planned_clip as { _director_audio_plan?: Record<string, unknown> } | null)?._director_audio_plan
  if (!plan) return '—'
  return [plan.mode, plan.timing_anchor, plan.lip_sync_critical ? 'lip-sync' : null]
    .filter(Boolean)
    .join(' · ') || '—'
}

export function WorkspacesPanel() {
  const pipelineList = useStore(s => s.dashboardPipelineList)
  const selectedPipeline = useStore(s => s.dashboardSelectedPipeline)
  const loading = useStore(s => s.dashboardLoading)
  const loadError = useStore(s => s.dashboardLoadError)
  const loadPipelineList = useStore(s => s.loadPipelineList)
  const loadPipeline = useStore(s => s.loadSavedPipeline)
  const retryLoad = useStore(s => s.retryDashboardLoad)
  const resumePipeline = useStore(s => s.resumePipeline)
  const rejoinClips = useStore(s => s.rejoinPipelineClips)
  const [actionError, setActionError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [rejoining, setRejoining] = useState(false)

  useEffect(() => {
    void loadPipelineList(selectedPipeline?.pipeline_id)
  }, [loadPipelineList, selectedPipeline?.pipeline_id])

  useEffect(() => {
    if (!selectedPipeline) return
    const live = pipelineBusy(selectedPipeline)
    if (!live) return
    const timer = window.setInterval(() => {
      void loadPipeline(selectedPipeline.pipeline_id)
      void loadPipelineList(selectedPipeline.pipeline_id)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [loadPipeline, loadPipelineList, selectedPipeline])

  const queue = selectedPipeline ? hydratePipelineQueue(selectedPipeline) : null
  const selectedId = queue?.pipeline_id || ''
  const readyVideos = queue?.clips.filter(clip => Boolean(selectedAttempt(clip)?.filename && !clip.video_stale)).length || 0

  const launch = async () => {
    if (!selectedPipeline) return
    setLaunching(true)
    setActionError(null)
    try {
      if (selectedPipeline.status === 'paused') {
        await api.continuePipeline(selectedPipeline.pipeline_id)
        await loadPipeline(selectedPipeline.pipeline_id)
      } else {
        await resumePipeline(selectedPipeline.pipeline_id)
      }
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLaunching(false)
    }
  }

  const rejoin = async () => {
    if (!selectedPipeline) return
    setRejoining(true)
    setActionError(null)
    try {
      await rejoinClips(selectedPipeline.pipeline_id)
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRejoining(false)
    }
  }

  return (
    <section aria-label="Workspaces" className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-primary md:flex-row">
      <aside aria-label="Generation threads" className="flex w-full shrink-0 flex-col border-b border-border bg-bg-secondary md:w-64 md:border-b-0 md:border-r xl:w-72">
        <div className="border-b border-border p-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Workspaces</h2>
              <p className="text-[10px] text-text-muted">Processing · song and video threads</p>
            </div>
            <button type="button" className={button} onClick={() => void loadPipelineList(selectedId || undefined)} title="Reload threads">
              <RefreshCw size={13} />
            </button>
          </div>
        </div>
        <nav aria-label="Saved threads" className="flex min-h-0 max-h-36 flex-1 gap-2 overflow-x-auto p-2 md:block md:max-h-none md:overflow-x-hidden md:overflow-y-auto">
          {pipelineList.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => void loadPipeline(item.id)}
              className={`mb-0 min-w-52 shrink-0 rounded-lg border p-2 text-left md:mb-1.5 md:w-full md:min-w-0 ${
                item.id === selectedId ? 'border-violet-500/40 bg-violet-500/10' : 'border-transparent hover:bg-bg-hover'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-medium text-text-primary">{pipelineLabel(item)}</span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] ${statusTone(item.status)}`}>{item.repair_status || item.status}</span>
              </div>
              <div className="mt-1 text-[10px] text-text-muted">{formatDate(item.created_at)} · {item.id === selectedId && queue ? queue.clips.length : item.clip_count} shots · {item.pipeline_type.replace(/_/g, ' ')}</div>
              {item.error && <p className="mt-1 line-clamp-2 text-[10px] text-red-300">{item.error}</p>}
            </button>
          ))}
          {!pipelineList.length && (
            <p className="min-w-64 p-3 text-[11px] leading-relaxed text-text-muted">
              Generate a song or Director video and the thread appears here with every prompt, reference and queued shot.
            </p>
          )}
        </nav>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="border-b border-border bg-bg-secondary px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold text-text-primary">
                {selectedPipeline ? pipelineLabel(selectedPipeline) : 'Processing'}
              </h2>
              <p className="text-[10px] text-text-muted">
                {queue
                  ? `${queue.image_model || 'no image model'} + ${queue.video_model || 'no video model'} · ${readyVideos}/${queue.clips.length} videos`
                  : 'Load a thread to inspect its queue'}
              </p>
            </div>
            {selectedPipeline && (
              <>
                <button type="button" className={primary} disabled={launching || !pipelineCanLaunch(queue)} onClick={() => void launch()}>
                  {launching ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  {queue?.status === 'paused' ? 'Continue videos' : 'Start / resume videos'}
                </button>
                <button type="button" className={button} disabled={rejoining || readyVideos < 2} onClick={() => void rejoin()}>
                  {rejoining ? <Loader2 size={13} className="animate-spin" /> : <Combine size={13} />}
                  Regenerar vídeo completo
                </button>
              </>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-3 md:p-4">
          {(loadError || actionError) && (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              <span className="min-w-0 flex-1">{actionError || loadError}</span>
              {loadError && <button type="button" className={button} onClick={() => void retryLoad()}>Retry</button>}
            </div>
          )}
          {loading && !selectedPipeline && (
            <div className="flex items-center justify-center gap-2 py-16 text-xs text-text-muted">
              <Loader2 size={16} className="animate-spin" /> Loading thread…
            </div>
          )}
          {!loading && !selectedPipeline && (
            <div className="mx-auto mt-16 max-w-lg rounded-2xl border border-violet-500/30 bg-violet-500/10 p-8 text-center">
              <Layers size={28} className="mx-auto text-violet-300" />
              <h3 className="mt-3 text-base font-semibold text-text-primary">Inspect the generation queue</h3>
              <p className="mt-2 text-xs leading-relaxed text-text-muted">
                After a song or music video writes its prompts, open the thread here to see every shot, reference and model, edit mid-run, pick takes and join the final video.
              </p>
            </div>
          )}
          {queue && <ProcessingView pipeline={queue} />}
        </div>
      </div>
    </section>
  )
}

function ProcessingView({ pipeline }: { pipeline: SavedPipelineState }) {
  const refs = [
    ...(pipeline.character_ref_paths || []).map(path => ({ kind: 'Character', path })),
    ...(pipeline.location_ref_paths || []).map(path => ({ kind: 'Location', path })),
    pipeline.reference_image_path ? { kind: 'Reference', path: pipeline.reference_image_path } : null,
  ].filter(Boolean) as Array<{ kind: string; path: string }>
  const finalOutput = pipeline.final_output_filename || [...(pipeline.output_files || [])]
    .reverse()
    .find(name => /(?:rejoin|multiclip|_movie)\.(?:mp4|webm|mkv|mov)$/i.test(name))

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-bg-secondary p-3">
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className={`rounded px-2 py-0.5 ${statusTone(pipeline.status)}`}>{pipeline.phase || pipeline.status}</span>
          <span className="text-text-muted">{pipeline.pipeline_type.replace(/_/g, ' ')}</span>
          {pipeline.queue_source && pipeline.queue_source !== 'clips' && (
            <span className="rounded bg-amber-500/15 px-2 py-0.5 text-amber-200">Queue from planned prompts</span>
          )}
        </div>
        {pipeline.error && <p className="mt-2 text-xs text-red-300">{pipeline.error}</p>}
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <MetaChip label="Image model" value={pipeline.image_model || '—'} />
          <MetaChip label="Video model" value={pipeline.video_model || '—'} />
          <MetaChip label="Shots in queue" value={String(pipeline.clips.length)} />
          <MetaChip label="Created" value={formatDate(pipeline.created_at)} />
        </div>
        {refs.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {refs.map(ref => (
              <div key={`${ref.kind}-${ref.path}`} className="flex items-center gap-2 rounded border border-border bg-bg-tertiary px-2 py-1">
                <img src={getFileUrl(ref.path)} alt="" className="h-10 w-10 rounded object-cover" />
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-muted">{ref.kind}</div>
                  <div className="max-w-40 truncate text-[10px] text-text-secondary">{fileLabel(ref.path)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {finalOutput && (
          <video src={getFileUrl(finalOutput)} controls preload="metadata" className="mt-3 max-h-64 w-full rounded bg-black object-contain" />
        )}
      </div>

      <div className="space-y-3">
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-text-secondary">
          Queue ({pipeline.clips.length})
        </h3>
        {pipeline.clips.map(clip => (
          <QueueShotCard key={`${pipeline.pipeline_id}-${clip.index}`} pipeline={pipeline} clip={clip} />
        ))}
        {!pipeline.clips.length && (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-text-muted">
            This thread has no planned shots yet.
          </p>
        )}
      </div>
    </div>
  )
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-bg-tertiary px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-text-muted">{label}</div>
      <div className="truncate text-xs text-text-primary" title={value}>{value}</div>
    </div>
  )
}

function QueueShotCard({ pipeline, clip }: { pipeline: SavedPipelineState; clip: PipelineClipState }) {
  const updateClipPrompt = useStore(s => s.updateClipPrompt)
  const rerunClipVideo = useStore(s => s.rerunClipVideo)
  const selectClipVideo = useStore(s => s.selectClipVideo)
  const busy = pipelineBusy(pipeline)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(shotPrompt(clip))
  const [saving, setSaving] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const attempt = selectedAttempt(clip)
  const attempts = useMemo(() => attemptsForClip(clip), [clip])
  const duration = shotDuration(clip)
  const subjects = clip._director_subjects_on_screen || []
  const beats = clip._director_dialogue_beats || []

  useEffect(() => {
    if (!editing) setDraft(shotPrompt(clip))
  }, [clip, editing])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await updateClipPrompt(pipeline.pipeline_id, clip.index, { video_prompt: draft })
      setEditing(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  const rerun = async () => {
    setRerunning(true)
    setError(null)
    try {
      await rerunClipVideo(pipeline.pipeline_id, clip.index, editing ? draft : undefined)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRerunning(false)
    }
  }

  return (
    <article className="rounded-xl border border-border bg-bg-secondary p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold text-text-primary">Shot {clip.index + 1}</h4>
        {duration != null && <span className="text-[10px] text-text-muted">{duration.toFixed(1)}s</span>}
        <span className="text-[10px] text-text-muted">{clip._director_h3_prompt_mode || pipeline.video_model}</span>
        <span className="text-[10px] text-text-muted">{audioPlanLabel(clip)}</span>
        <span className={`rounded px-1.5 py-0.5 text-[9px] ${attempt ? 'bg-green-500/15 text-indicator-success' : 'bg-bg-tertiary text-text-muted'}`}>
          {attempt ? `${attempts.length} take${attempts.length === 1 ? '' : 's'}` : 'placeholder'}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" className={button} onClick={() => { setEditing(value => !value); setDraft(shotPrompt(clip)) }}>
            <Pencil size={11} /> Edit
          </button>
          {editing && (
            <button type="button" className={primary} disabled={saving || busy} onClick={() => void save()}>
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />} Save prompt
            </button>
          )}
          <button type="button" className={button} disabled={rerunning || busy} onClick={() => void rerun()} title="Repeat this shot and keep previous takes">
            {rerunning ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Repeat
          </button>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-lg border border-border bg-black">
          {attempt?.filename ? (
            <video src={getFileUrl(attempt.filename)} controls preload="metadata" className="aspect-video w-full object-contain" />
          ) : clip.start_image_filename ? (
            <img src={getFileUrl(clip.start_image_filename)} alt={`Shot ${clip.index + 1}`} className="aspect-video w-full object-cover" />
          ) : (
            <div className="flex aspect-video flex-col items-center justify-center gap-1 text-text-muted">
              <ImageIcon size={18} />
              <span className="text-[10px]">Video placeholder</span>
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-2">
          {editing ? (
            <textarea
              value={draft}
              onChange={event => setDraft(event.target.value)}
              rows={7}
              className="w-full resize-y rounded-md border border-violet-400/50 bg-bg-primary px-2 py-1.5 text-[11px] text-text-primary focus:outline-none"
            />
          ) : (
            <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-text-secondary">{shotPrompt(clip) || 'No prompt yet'}</p>
          )}
          {(subjects.length > 0 || beats.length > 0 || clip.h3_references) && (
            <div className="rounded border border-cyan-500/20 bg-cyan-500/5 p-2 text-[10px] text-text-secondary">
              {subjects.length > 0 && <div>Subjects: {subjects.map(subject => String(subject.speaker_name || subject.character_id || 'subject')).join(', ')}</div>}
              {beats.length > 0 && <div>Dialogue beats: {beats.length}</div>}
              {clip.h3_references && (
                <div>
                  Refs: {[
                    ...clip.h3_references.image_references.map(fileLabel),
                    ...clip.h3_references.video_references.map(fileLabel),
                    ...clip.h3_references.audio_references.map(fileLabel),
                  ].filter(Boolean).join(', ') || clip.h3_references.mode}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {attempts.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center gap-1 text-[10px] font-medium text-text-secondary">
            <History size={11} /> Takes for this slot — choose which one stays in the cut
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">
            {attempts.map((item, index) => {
              const selected = item.filename === (clip.selected_video_filename || clip.video_filename)
              return (
                <button
                  key={item.id || item.filename}
                  type="button"
                  disabled={busy}
                  onClick={() => void selectClipVideo(pipeline.pipeline_id, clip.index, item.filename).catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))}
                  className={`overflow-hidden rounded border text-left ${selected ? 'border-emerald-400 bg-emerald-500/10' : 'border-border bg-bg-tertiary hover:border-violet-400/60'}`}
                >
                  <div className="relative aspect-video bg-black">
                    <video src={`${getFileUrl(item.filename)}#t=0.1`} muted playsInline preload="metadata" className="h-full w-full object-contain" />
                    {selected && <span className="absolute right-1 top-1 inline-flex items-center gap-1 rounded bg-emerald-600/90 px-1.5 py-0.5 text-[8px] text-white"><Check size={8} />In cut</span>}
                  </div>
                  <div className="p-1.5">
                    <div className="truncate text-[9px] text-text-primary">Take {index + 1} · {item.source || 'historical'}</div>
                    <div className="truncate text-[8px] text-text-muted">seed {item.seed ?? '—'}</div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
      {error && <p className="mt-2 text-[10px] text-red-300">{error}</p>}
    </article>
  )
}

export default WorkspacesPanel
