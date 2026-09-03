import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, FileText, Loader2, Play, Square } from 'lucide-react'
import * as api from '../../api/client'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import { Pill, SectionCard, SeriesField, seriesStatusLabel } from './components'
import { SeriesEpisodeProposalReview } from './SeriesEpisodeProposalReview'
import { inputClass, primaryButton, secondaryButton, textareaClass } from './styles'
import type { SeriesEpisode, SeriesJobStatus, SeriesProject } from './types'
import { listenForAgentSeriesPlanJob } from '../../lib/uiBus'
import { useUiTranslation } from '../../i18n'

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
  const { t } = useUiTranslation('seriesLab')
  const [instruction, setInstruction] = useState('')
  const [job, setJob] = useState<SeriesJobStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const episodeIdRef = useRef(episode.id)
  const activeJob = job
    && job.episodeId === episode.id
    && ['queued', 'running', 'cancelling'].includes(job.status)
    ? job : null
  const jobBusy = Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))

  useEffect(() => {
    episodeIdRef.current = episode.id
    setJob(current => current?.episodeId === episode.id ? current : null)
    setBusy(false)
    setError(null)
  }, [episode.id])

  useEffect(() => listenForAgentSeriesPlanJob((value, episodeId) => {
    if (episodeId === episodeIdRef.current) setJob(value)
  }), [])

  useSerializedPoll({
    enabled: Boolean(activeJob),
    intervalMs: 1000,
    ownerKey: activeJob ? `${episode.id}:${activeJob.jobId}` : null,
    immediate: false,
    poll: signal => api.fetchSeriesPlanJob(activeJob?.jobId || '', signal),
    onValue: value => {
      if (
        episodeIdRef.current === episode.id
        && value.jobId === activeJob?.jobId
        && value.episodeId === episode.id
      ) setJob(value)
    },
    onError: reason => {
      if (episodeIdRef.current === episode.id) setError((reason as Error).message)
    },
  })

  const start = async (scope: 'outline' | 'script' | 'shots' | 'complete') => {
    const episodeId = episode.id
    setBusy(true); setError(null)
    try {
      await saveNow()
      const started = await api.startSeriesPlan(workspace, series.id, episodeId, {
        scope, instruction,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
      })
      if (episodeIdRef.current === episodeId && started.episodeId === episodeId) setJob(started)
    } catch (reason) {
      if (episodeIdRef.current === episodeId) setError((reason as Error).message)
    }
    finally {
      if (episodeIdRef.current === episodeId) setBusy(false)
    }
  }
  const apply = async (proposal: SeriesEpisode) => {
    if (!job || job.episodeId !== episode.id || proposal.id !== episode.id) return
    const episodeId = episode.id
    setBusy(true); setError(null)
    try {
      await api.applySeriesPlanJob(job.jobId, proposal)
      await reload()
      if (episodeIdRef.current === episodeId) setJob(null)
    }
    catch (reason) {
      if (episodeIdRef.current === episodeId) setError((reason as Error).message)
    }
    finally {
      if (episodeIdRef.current === episodeId) setBusy(false)
    }
  }

  return <div className="space-y-4 pb-10">
    {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
    <SectionCard title={t('episode.heading', { number: episode.number, title: episode.title })} description={t('episode.frozen', { revision: episode.canonRevisionAtCreation })}>
      <div className="grid gap-3 lg:grid-cols-2">
        <SeriesField label={t('episode.title')}><input className={inputClass} value={episode.title} onChange={event => updateEpisode(current => ({ ...current, title: event.target.value }))} /></SeriesField>
        <SeriesField label={t('episode.duration')}><input className={inputClass} type="number" min={15} max={3600} value={episode.targetDurationSeconds} onChange={event => updateEpisode(current => ({ ...current, targetDurationSeconds: Number(event.target.value) }))} /></SeriesField>
        <SeriesField label={t('episode.premise')} required><textarea className={textareaClass} value={episode.premise} onChange={event => updateEpisode(current => ({ ...current, premise: event.target.value }))} /></SeriesField>
        <SeriesField label={t('episode.logline')}><textarea className={textareaClass} value={episode.logline} onChange={event => updateEpisode(current => ({ ...current, logline: event.target.value }))} /></SeriesField>
      </div>
    </SectionCard>

    <SectionCard title={t('episode.roomTitle')} description={t('episode.roomDescription')}>
      <textarea className={textareaClass} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder={t('episode.instructionPlaceholder')} />
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={secondaryButton} disabled={busy || jobBusy} onClick={() => void start('outline')}><FileText size={13} />{t('episode.generateOutline')}</button>
        <button className={primaryButton} disabled={busy || jobBusy} onClick={() => void start('complete')}><Play size={13} />{t('episode.generateComplete')}</button>
        <button className={secondaryButton} disabled={busy || !episode.script.length || jobBusy} onClick={() => void start('shots')}><Play size={13} />{t('episode.regenerateShots')}</button>
        {job && job.episodeId === episode.id && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(value => {
          if (episodeIdRef.current === episode.id && value.episodeId === episode.id) setJob(value)
        })}><Square size={13} />{t('episode.cancelJob')}</button>}
      </div>
      {job && job.episodeId === episode.id && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<Pill tone={job.status === 'completed' ? 'green' : job.status === 'failed' ? 'red' : 'violet'}>{seriesStatusLabel(t, job.status)}</Pill><span>{job.message}</span><span className="ml-auto">{job.current}/{job.total}</span></div>
        {job.error && <p className="mt-2 text-[11px] text-red-300">{job.error}</p>}
        {job.status === 'completed' && job.episodeResult && <SeriesEpisodeProposalReview key={job.jobId} workspace={workspace} currentEpisode={episode} proposal={job.episodeResult} series={series} busy={busy} onApply={apply} />}
        {(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(value => {
          if (episodeIdRef.current === episode.id && value.episodeId === episode.id) setJob(value)
        })}>{t('episode.resumeStages')}</button>}
      </div>}
    </SectionCard>

    <SectionCard title={t('episode.outline')} description={t('episode.savedBeats', { count: episode.outline.beats.length })}>
      <div className="space-y-2">{episode.outline.beats.map((beat, index) => <div key={index} className="flex items-center gap-2"><span className="w-6 text-right text-[10px] text-text-muted">{index + 1}</span><input className={inputClass} value={beat} onChange={event => updateEpisode(current => ({ ...current, outline: { ...current.outline, beats: current.outline.beats.map((item, i) => i === index ? event.target.value : item) } }))} /></div>)}</div>
    </SectionCard>

    <SectionCard title={t('episode.scriptTitle')} description={t('episode.scriptDescription')}>
      <div className="space-y-3">{episode.script.map((scene, sceneIndex) => <div key={scene.id} id={`series-scene-${scene.id}`} className="rounded-xl border border-border bg-bg-primary p-3">
        <div className="flex items-center gap-2"><Pill tone="blue">{t('episode.scene', { number: sceneIndex + 1 })}</Pill><input className={inputClass} value={scene.purpose} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, purpose: event.target.value } : item) }))} /><button disabled={sceneIndex === 0} onClick={() => updateEpisode(current => { const script = [...current.script]; [script[sceneIndex - 1], script[sceneIndex]] = [script[sceneIndex], script[sceneIndex - 1]]; return { ...current, script: script.map((item, i) => ({ ...item, order: i + 1 })) } })}><ArrowUp size={14} /></button><button disabled={sceneIndex === episode.script.length - 1} onClick={() => updateEpisode(current => { const script = [...current.script]; [script[sceneIndex], script[sceneIndex + 1]] = [script[sceneIndex + 1], script[sceneIndex]]; return { ...current, script: script.map((item, i) => ({ ...item, order: i + 1 })) } })}><ArrowDown size={14} /></button></div>
        <div className="mt-2 grid gap-2 md:grid-cols-3"><select className={inputClass} value={scene.locationId} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, locationId: event.target.value } : item) }))}>{series.locations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className={inputClass} value={scene.time} placeholder={t('episode.time')} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, time: event.target.value } : item) }))} /><input className={inputClass} value={scene.exitState} placeholder={t('episode.exitState')} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, exitState: event.target.value } : item) }))} /></div>
        <div className="mt-3 space-y-2">{scene.dialogue.map((line, lineIndex) => <div key={line.id} className="grid gap-2 rounded-lg border border-border p-2 md:grid-cols-[160px_1fr_140px_140px]"><select className={inputClass} value={line.characterId} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, characterId: event.target.value } : dialogue) } : item) }))}>{series.characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input className={inputClass} value={line.text} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, text: event.target.value } : dialogue) } : item) }))} /><input className={inputClass} value={line.emotion} placeholder={t('episode.emotion')} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, emotion: event.target.value } : dialogue) } : item) }))} /><input className={inputClass} value={line.delivery} placeholder={t('episode.delivery')} onChange={event => updateEpisode(current => ({ ...current, script: current.script.map((item, i) => i === sceneIndex ? { ...item, dialogue: item.dialogue.map((dialogue, j) => j === lineIndex ? { ...dialogue, delivery: event.target.value } : dialogue) } : item) }))} /></div>)}</div>
      </div>)}</div>
    </SectionCard>

    {episode.continuityIssues && <SectionCard title={t('episode.validationTitle')} description={t('episode.validationDescription')}><div className="space-y-2">{episode.continuityIssues.length ? episode.continuityIssues.map(issue => <a key={issue.id} href={issue.shotId ? `#series-shot-${issue.shotId}` : issue.sceneId ? `#series-scene-${issue.sceneId}` : undefined} className="block rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200"><Pill tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.kind}</Pill><span className="ml-2">{issue.message}</span></a>) : <p className="text-xs text-green-300">{t('episode.noIssues')}</p>}</div></SectionCard>}
  </div>
}
