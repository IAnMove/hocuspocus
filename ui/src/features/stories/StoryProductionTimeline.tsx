import { useEffect, useMemo, useRef, useState } from 'react'
import { Combine, ExternalLink, Film, Loader2, Play, Square } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import type { SavedPipelineState } from '../../types'
import type { StoryProduction } from './types'

const control = 'inline-flex items-center gap-1 rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] text-text-secondary hover:bg-bg-hover disabled:opacity-40'

export function StoryProductionTimeline({ production, initiallyOpen = false }: {
  production: StoryProduction
  initiallyOpen?: boolean
}) {
  const pipelineId = typeof production.targetSnapshot?.pipelineId === 'string'
    ? production.targetSnapshot.pipelineId : ''
  const [open, setOpen] = useState(initiallyOpen)
  const [pipeline, setPipeline] = useState<SavedPipelineState | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [playIndex, setPlayIndex] = useState(0)
  const [playingAll, setPlayingAll] = useState(false)
  const playerRef = useRef<HTMLVideoElement>(null)
  const pipelineLoadedRef = useRef(false)
  const setDashboardOpen = useStore(state => state.setDashboardOpen)
  const rejoinPipelineClips = useStore(state => state.rejoinPipelineClips)

  const playable = useMemo(() => (pipeline?.clips || [])
    .filter(clip => Boolean(clip.video_filename) && !clip.video_stale)
    .sort((left, right) => left.index - right.index), [pipeline])
  const current = playable[playIndex]

  useEffect(() => {
    if (!playingAll || !current?.video_filename || !playerRef.current) return
    playerRef.current.currentTime = 0
    void playerRef.current.play().catch(reason => {
      setPlayingAll(false); setError((reason as Error).message)
    })
  }, [current?.video_filename, playingAll])

  useEffect(() => {
    if (!open || !pipelineId) return
    let active = true
    const refresh = (initial = false) => {
      if (initial) setLoading(true)
      void api.fetchSavedPipeline(pipelineId).then(value => {
        if (active) {
          pipelineLoadedRef.current = true
          setPipeline(value)
        }
      }).catch(reason => {
        if (active) setError((reason as Error).message)
      }).finally(() => {
        if (active && initial) setLoading(false)
      })
    }
    refresh(!pipelineLoadedRef.current)
    const timer = window.setInterval(() => refresh(false), 3000)
    return () => { active = false; window.clearInterval(timer) }
  }, [open, pipelineId])

  if (!pipelineId) return <span className="text-[9px] text-text-muted">Open the staged target once to create its clip pipeline.</span>
  const finalOutput = pipeline?.final_output_filename || [...(pipeline?.output_files || [])].reverse()
    .find(filename => /(?:rejoin|multiclip|_movie)\.(?:mp4|webm|mkv|mov)$/i.test(filename))
  return <div className="mt-2 w-full">
    <button className={control} onClick={() => { setError(null); setOpen(value => !value) }}><Film size={11} />{open ? 'Hide ordered clips' : 'View ordered clips'}</button>
    {open && <div className="mt-2 rounded-xl border border-border bg-bg-secondary p-2">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-text-muted">Pipeline {pipelineId} · {playable.length}/{pipeline?.clips.length || 0} playable</span>
        <button className={control} disabled={!playable.length || playingAll} onClick={() => { setPlayIndex(0); setPlayingAll(true) }}><Play size={11} />Play all</button>
        {playingAll && <button className={control} onClick={() => { playerRef.current?.pause(); setPlayingAll(false); setPlayIndex(0) }}><Square size={11} />Stop</button>}
        <button className={control} disabled={playable.length < 2 || loading} onClick={() => { setLoading(true); setError(null); void rejoinPipelineClips(pipelineId).then(() => api.fetchSavedPipeline(pipelineId)).then(setPipeline).catch(reason => setError((reason as Error).message)).finally(() => setLoading(false)) }}>{loading ? <Loader2 size={11} className="animate-spin" /> : <Combine size={11} />}Join clips</button>
        <button className={control} onClick={() => setDashboardOpen(true, pipelineId)}><ExternalLink size={11} />Edit/regenerate clips</button>
        {finalOutput && <a className={control} href={api.getFileUrl(finalOutput, pipeline?.workspace)} target="_blank" rel="noreferrer">Open joined video</a>}
      </div>
      {error && <p className="mb-2 rounded border border-red-500/30 bg-red-500/10 p-2 text-[10px] text-red-300">{error}</p>}
      {loading && !pipeline && <div className="flex items-center gap-2 p-4 text-[10px] text-text-muted"><Loader2 size={12} className="animate-spin" />Loading clip history…</div>}
      {pipeline && <div className="grid min-h-72 overflow-hidden rounded-lg border border-border lg:grid-cols-[15rem_minmax(0,1fr)]">
        <div className="max-h-[32rem] overflow-y-auto border-b border-border p-2 lg:border-b-0 lg:border-r">{[...pipeline.clips].sort((left, right) => left.index - right.index).map(clip => <button key={clip.shot_id || clip.index} className={`mb-1.5 w-full rounded border p-2 text-left ${current?.index === clip.index ? 'border-violet-400 bg-violet-500/15' : 'border-border bg-bg-primary'}`} onClick={() => { const next = playable.findIndex(value => value.index === clip.index); if (next >= 0) { setPlayingAll(false); setPlayIndex(next) } }}><span className="text-[10px] font-medium text-text-primary">Clip {clip.index + 1}</span><span className="ml-2 text-[9px] text-text-muted">{clip.video_filename ? clip.video_stale ? 'stale' : 'ready' : 'missing'}</span><p className="mt-1 line-clamp-2 text-[9px] text-text-muted">{clip.video_prompt || clip.image_prompt}</p></button>)}</div>
        {current?.video_filename ? <div className="bg-black"><video key={current.video_filename} ref={playerRef} className="max-h-[32rem] w-full bg-black" src={api.getFileUrl(current.video_filename, pipeline.workspace)} controls autoPlay={playingAll} onEnded={() => { if (!playingAll) return; if (playIndex + 1 < playable.length) setPlayIndex(value => value + 1); else { setPlayingAll(false); setPlayIndex(0) } }} /><div className="bg-bg-primary p-2 text-[10px] text-text-muted">Clip {current.index + 1} · seed {current.seed ?? '—'} · {current.duration_seconds || 0}s</div></div> : <div className="flex items-center justify-center bg-black/80 p-6 text-[10px] text-text-muted">No playable clip selected.</div>}
      </div>}
    </div>}
  </div>
}
