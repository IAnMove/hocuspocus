import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Check, FileText, Loader2, Play, Square } from 'lucide-react'
import * as api from '../../api/client'
import { Pill, SectionCard, SeriesField } from './components'
import { greenButton, inputClass, primaryButton, secondaryButton, textareaClass } from './styles'
import type { SeriesEpisode, SeriesJobStatus, SeriesProject } from './types'

export function SeriesEpisodePanel({
  workspace, series, episode, updateEpisode, saveNow, reload,
}: {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  updateEpisode: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  saveNow: () => Promise<unknown>
  reload: () => Promise<void>
}) {
  const [instruction, setInstruction] = useState('')
  const [job, setJob] = useState<SeriesJobStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.fetchSeriesPlanJob(job.jobId).then(value => {
        if (active) setJob(value)
      }).catch(reason => {
        if (active) setError((reason as Error).message)
      })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [job])

  const start = async (scope: 'outline' | 'script' | 'shots' | 'complete') => {
    setBusy(true); setError(null)
    try {
      await saveNow()
      setJob(await api.startSeriesPlan(workspace, series.id, episode.id, {
        scope, instruction,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const apply = async () => {
    if (!job) return
    setBusy(true); setError(null)
    try { await api.applySeriesPlanJob(job.jobId); await reload(); setJob(null) }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  return <div className="space-y-4 pb-10">
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
    <SectionCard title={`Episode ${episode.number} · ${episode.title}`} description={`Frozen canon revision ${episode.canonRevisionAtCreation}. Planning cannot mutate the current series canon.`}>
      <div className="grid gap-3 lg:grid-cols-2">
        <SeriesField label="Episode title"><input className={inputClass} value={episode.title} onChange={event => updateEpisode(current => ({ ...current, title: event.target.value }))} /></SeriesField>
        <SeriesField label="Target duration"><input className={inputClass} type="number" min={15} max={3600} value={episode.targetDurationSeconds} onChange={event => updateEpisode(current => ({ ...current, targetDurationSeconds: Number(event.target.value) }))} /></SeriesField>
        <SeriesField label="Episode premise" required><textarea className={textareaClass} value={episode.premise} onChange={event => updateEpisode(current => ({ ...current, premise: event.target.value }))} /></SeriesField>
        <SeriesField label="Logline"><textarea className={textareaClass} value={episode.logline} onChange={event => updateEpisode(current => ({ ...current, logline: event.target.value }))} /></SeriesField>
      </div>
    </SectionCard>

    <SectionCard title="Episode room" description="Generated material is a recoverable proposal. Apply is explicit and conflicts if you edited the episode while it was running.">
      <textarea className={textareaClass} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="Optional episode constraints, required beat, character focus…" />
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={secondaryButton} disabled={busy || Boolean(job && ['queued', 'running'].includes(job.status))} onClick={() => void start('outline')}><FileText size={13} />Generate outline only</button>
        <button className={primaryButton} disabled={busy || Boolean(job && ['queued', 'running'].includes(job.status))} onClick={() => void start('complete')}><Play size={13} />Generate script + 8–12 shots</button>
        <button className={secondaryButton} disabled={busy || !episode.script.length || Boolean(job && ['queued', 'running'].includes(job.status))} onClick={() => void start('shots')}><Play size={13} />Regenerate shot proposal only</button>
        {job && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(setJob)}><Square size={13} />Cancel after current LLM call</button>}
      </div>
      {job && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<Pill tone={job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : 'violet'}>{job.status}</Pill><span>{job.message}</span><span className="ml-auto">{job.current}/{job.total}</span></div>
        {job.error && <p className="mt-2 text-[11px] text-red-300">{job.error}</p>}
        {job.status === 'completed' && job.episodeResult && <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/5 p-3">
          <p className="text-[11px] font-semibold text-green-200">Generated proposal — review before applying</p>
          <div className="mt-2 grid gap-2 text-[10px] text-text-secondary sm:grid-cols-3"><span>Outline: {episode.outline.beats.length} → {job.episodeResult.outline.beats.length} beats</span><span>Script: {episode.script.length} → {job.episodeResult.script.length} scenes</span><span>Shots: {episode.shots.length} → {job.episodeResult.shots.length} ({job.episodeResult.shots.reduce((sum, shot) => sum + shot.durationSeconds, 0).toFixed(1)}s)</span></div>
          <details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">Inspect exact proposed outline, script and canon delta</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify({ outline: job.episodeResult.outline, script: job.episodeResult.script, shots: job.episodeResult.shots, continuityIssues: job.episodeResult.continuityIssues, proposedCanonDelta: job.episodeResult.proposedCanonDelta }, null, 2)}</pre></details>
          <button className={`mt-3 ${greenButton}`} onClick={() => void apply()} disabled={busy}><Check size={13} />Apply reviewed proposal</button>
        </div>}
        {(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(setJob)}>Resume completed stages</button>}
      </div>}
    </SectionCard>

    <SectionCard title="Outline" description={`${episode.outline.beats.length} saved beats`}>
      <div className="space-y-2">{episode.outline.beats.map((beat, index) => <div key={index} className="flex items-center gap-2"><span className="w-6 text-right text-[10px] text-text-muted">{index + 1}</span><input className={inputClass} value={beat} onChange={event => updateEpisode(current => ({ ...current, outline: { ...current.outline, beats: current.outline.beats.map((item, i) => i === index ? event.target.value : item) } }))} /></div>)}</div>
    </SectionCard>

    <SectionCard title="Script review" description="Reorder scenes and edit exact action/dialogue without regenerating the rest.">
      <div className="space-y-3">{episode.script.map((scene, sceneIndex) => <div key={scene.id} id={`series-scene-${scene.id}`} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2"><Pill tone="blue">Scene {sceneIndex + 1}</Pill><input className={inputClass} value={scene.purpose} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, purpose: event.target.value } : item) }))} /><button disabled={sceneIndex === 0} onClick={() => updateEpisode(current => { const script = [...current.script]; [script[sceneIndex - 1], script[sceneIndex]] = [script[sceneIndex], script[sceneIndex - 1]]; return { ...current, script: script.map((item, i) => ({ ...item, order: i + 1 })) } })}><ArrowUp size={14} /></button><button disabled={sceneIndex === episode.script.length - 1} onClick={() => updateEpisode(current => { const script = [...current.script]; [script[sceneIndex], script[sceneIndex + 1]] = [script[sceneIndex + 1], script[sceneIndex]]; return { ...current, script: script.map((item, i) => ({ ...item, order: i + 1 })) } })}><ArrowDown size={14} /></button></div>
        <div className="mt-2 grid gap-2 md:grid-cols-3"><select className={inputClass} value={scene.locationId} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, locationId: event.target.value } : item) }))}>{series.locations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className={inputClass} value={scene.time} placeholder="Time" onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, time: event.target.value } : item) }))} /><input className={inputClass} value={scene.exitState} placeholder="Exit state" onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, exitState: event.target.value } : item) }))} /></div>
        <div className="mt-3 space-y-2">{scene.dialogue.map((line, lineIndex) => <div key={line.id} className="grid gap-2 rounded-lg border border-border p-2 md:grid-cols-[160px_1fr_140px_140px]"><select className={inputClass} value={line.characterId} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, characterId: event.target.value } : dialogue) } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className={inputClass} value={line.text} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, text: event.target.value } : dialogue) } : item) }))} /><input className={inputClass} value={line.emotion} placeholder="Emotion" onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, emotion: event.target.value } : dialogue) } : item) }))} /><input className={inputClass} value={line.delivery} placeholder="Delivery" onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, delivery: event.target.value } : dialogue) } : item) }))} /></div>)}</div>
      </div>)}</div>
    </SectionCard>

    {episode.continuityIssues && <SectionCard title="Canon validation" description="Validation flags issues but never silently rewrites the script."><div className="space-y-2">{episode.continuityIssues.length ? episode.continuityIssues.map(issue => <a key={issue.id} href={issue.shotId ? `#series-shot-${issue.shotId}` : issue.sceneId ? `#series-scene-${issue.sceneId}` : undefined} className="block rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200"><Pill tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.kind}</Pill><span className="ml-2">{issue.message}</span></a>) : <p className="text-xs text-green-300">No structured continuity issue was reported.</p>}</div></SectionCard>}
  </div>
}
