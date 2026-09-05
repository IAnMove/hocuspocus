import { ExternalLink, Loader2, Play, RefreshCcw, Square, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import type { StoryMusicVideoGenerationMode, StoryProject } from './types'

const control = 'inline-flex items-center justify-center gap-1 rounded-md border border-border bg-bg-tertiary px-2 py-1 text-[10px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40'
const activeStatuses = new Set(['queued', 'running', 'cancelling'])
const PER_IDEA_STYLE_CONTRACT = 'Each batch idea defines its own visual style. Follow the style stated in the current idea exactly and never carry over a style from another item. A recognizable named character keeps their signature silhouette, proportions, wardrobe, palette and native design language. In crossovers, preserve each character identity while harmonizing only lighting, camera and background finish; never turn them into generic lookalikes.'

interface Props {
  project: StoryProject
  workspace: string
  videoModel: string
  imageModel: string
  resolution: string
  aspectRatio: string
  durationSeconds: number
}

function attachedReferences(
  project: StoryProject,
  labels: { world: string; location: string; character: string },
) {
  const result = new Map<string, { source: string; label: string; kind: string }>()
  const add = (assetId: string, label: string, kind: string) => {
    const asset = project.assets[assetId]
    if (!asset || asset.approval !== 'approved') return
    result.set(assetId, { source: asset.source, label, kind })
  }
  project.world.referenceAssetIds.forEach(id => add(id, project.world.summary || labels.world, 'location'))
  project.world.locations.forEach(location => location.referenceAssetIds.forEach(id => add(id, location.name || labels.location, 'location')))
  project.characters.forEach(character => character.referenceAssetIds.forEach(id => add(id, character.name || labels.character, 'character')))
  return [...result.values()]
}

function itemTone(status: string): string {
  if (status === 'completed') return 'border-emerald-500/30 bg-emerald-500/5'
  if (status === 'failed') return 'border-red-500/30 bg-red-500/5'
  if (status === 'running' || status === 'planning') return 'border-violet-500/40 bg-violet-500/10'
  return 'border-border bg-bg-primary'
}

function safeBatchMode(
  mode: StoryMusicVideoGenerationMode,
  referenceCount: number,
): StoryMusicVideoGenerationMode {
  return mode === 'direct_references' && referenceCount === 0
    ? 'image_guided'
    : mode
}

export function QuickVideoBatchPanel({
  project, workspace, videoModel, imageModel, resolution, aspectRatio, durationSeconds,
}: Props) {
  const { t } = useUiTranslation('storyLab')
  const [ideas, setIdeas] = useState('')
  const [continueOnError, setContinueOnError] = useState(true)
  const [jobs, setJobs] = useState<api.QuickVideoBatchJob[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const references = useMemo(
    () => attachedReferences(project, {
      world: t('batch.world'),
      location: t('batch.location'),
      character: t('batch.character'),
    }),
    [project, t],
  )
  const inheritedGenerationMode = safeBatchMode(
    project.musicVideoGenerationMode,
    references.length,
  )
  const [generationMode, setGenerationMode] = useState<StoryMusicVideoGenerationMode>(
    inheritedGenerationMode,
  )

  const parsedIdeas = useMemo(() => {
    const seen = new Set<string>()
    return ideas.split(/\r?\n/).map(value => value.trim()).filter(value => {
      if (!value || value.startsWith('#')) return false
      const key = value.toLocaleLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [ideas])

  useEffect(() => {
    setGenerationMode(inheritedGenerationMode)
  }, [project.id, inheritedGenerationMode])

  const refresh = useCallback(async () => {
    try {
      const response = await api.listQuickVideoBatches(workspace)
      setJobs(current => {
        const localById = new Map(current.map(job => [job.jobId, job]))
        return response.jobs.map(server => {
          const local = localById.get(server.jobId)
          if (local?.status === 'cancelling' && (server.status === 'queued' || server.status === 'running')) {
            return { ...server, status: 'cancelling' as const }
          }
          return server
        })
      })
      setError('')
    } catch (reason) {
      setError((reason as Error).message)
    }
  }, [workspace])

  useEffect(() => { void refresh() }, [refresh])
  const hasActiveJobs = jobs.some(job => activeStatuses.has(job.status))
  useSerializedPoll({
    enabled: hasActiveJobs,
    intervalMs: 2500,
    ownerKey: workspace,
    poll: async () => {
      const response = await api.listQuickVideoBatches(workspace)
      return response.jobs
    },
    onValue: serverJobs => {
      setJobs(current => {
        const localById = new Map(current.map(job => [job.jobId, job]))
        return serverJobs.map(server => {
          const local = localById.get(server.jobId)
          if (local?.status === 'cancelling' && (server.status === 'queued' || server.status === 'running')) {
            return { ...server, status: 'cancelling' as const }
          }
          return server
        })
      })
      setError('')
    },
    onError: reason => setError((reason as Error).message),
  })

  const start = async () => {
    if (!parsedIdeas.length || busy) return
    setBusy(true)
    setError('')
    try {
      const created = await api.startQuickVideoBatch({
        workspace,
        title: t('batch.titleTemplate', { title: project.title || t('batch.quickVideos') }),
        ideas: parsedIdeas,
        continueOnError,
        settings: {
          durationSeconds,
          generationMode,
          videoModel,
          imageModel,
          resolution,
          aspectRatio,
          spokenLanguage: project.spokenLanguage,
          visualStyle: project.visualStyle,
          characterVisualStyle: project.characterVisualStyle,
          directVideoMasterPrompt: generationMode === 'direct_video'
            ? project.directVideoMasterPrompt.trim() || project.visualStyle.trim() || PER_IDEA_STYLE_CONTRACT
            : project.directVideoMasterPrompt,
          allowClipText: project.allowClipText,
          writingProvider: project.provider.writingProvider,
          writingModel: project.provider.writingModel,
          writingBaseUrl: project.provider.writingBaseUrl,
          characters: project.characters.map(character => ({
            name: character.name,
            description: [character.appearance, character.wardrobe, character.personality, character.voice]
              .filter(Boolean).join('. '),
          })),
          references,
        },
      })
      setJobs(current => [created, ...current.filter(job => job.jobId !== created.jobId)])
      setIdeas('')
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const action = async (
    job: api.QuickVideoBatchJob,
    command: 'cancel' | 'resume' | 'retry-item' | 'skip-item' | 'discard',
    itemIndex?: number,
  ) => {
    if (command === 'discard' && !window.confirm(t('batch.discardConfirm'))) return
    setError('')
    if (command === 'cancel') {
      setJobs(current => current.map(value => value.jobId === job.jobId ? { ...value, status: 'cancelling' } : value))
    }
    try {
      const result = await api.controlQuickVideoBatch(job.jobId, command, workspace, itemIndex)
      if ('discarded' in result) {
        setJobs(current => current.filter(value => value.jobId !== job.jobId))
      } else {
        setJobs(current => current.map(value => value.jobId === result.jobId ? result : value))
      }
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const directReferencesMissing = generationMode === 'direct_references'
    && references.length === 0
  const statusLabel = (status: string): string => {
    if (status === 'queued') return t('batch.statusQueued')
    if (status === 'running') return t('batch.statusRunning')
    if (status === 'cancelling') return t('batch.statusCancelling')
    if (status === 'completed') return t('batch.statusCompleted')
    if (status === 'failed') return t('batch.statusFailed')
    if (status === 'cancelled') return t('batch.statusCancelled')
    if (status === 'interrupted') return t('batch.statusInterrupted')
    if (status === 'planning') return t('batch.statusPlanning')
    if (status === 'skipped') return t('batch.statusSkipped')
    return status
  }

  return (
    <div className="rounded-lg border border-fuchsia-500/25 bg-fuchsia-500/5 p-3 space-y-3">
      <div>
        <h4 className="text-xs font-semibold text-fuchsia-100">{t('batch.title')}</h4>
        <p className="mt-1 text-[10px] leading-relaxed text-text-muted">
          {t('batch.description')}
        </p>
      </div>
      <textarea
        className="min-h-28 w-full rounded-md border border-border bg-bg-tertiary px-2 py-2 text-xs text-text-primary focus:border-fuchsia-400 focus:outline-none"
        value={ideas}
        onChange={event => setIdeas(event.target.value)}
        placeholder={t('batch.placeholder')}
        aria-label={t('batch.ideasAria')}
      />
      <fieldset className="space-y-1.5">
        <legend className="text-[10px] font-medium text-text-secondary">{t('batch.howToGenerate')}</legend>
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
          {([
            ['image_guided', t('batch.modeStartImage'), t('batch.modeStartImageDetail')],
            ['direct_video', t('batch.modeTextToVideo'), t('batch.modeTextToVideoDetail')],
            ['direct_references', t('batch.modeReferences'), t('batch.modeReferencesDetail')],
          ] as const).map(([mode, label, detail]) => (
            <button
              key={mode}
              type="button"
              aria-pressed={generationMode === mode}
              className={`${control} flex-col ${generationMode === mode ? 'border-fuchsia-400/70 bg-fuchsia-500/15 text-fuchsia-100' : ''}`}
              onClick={() => setGenerationMode(mode)}
            >
              <span>{label}</span>
              <span className="text-[9px] text-text-muted">{detail}</span>
            </button>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-text-muted">
        <span>{t('batch.ideasCount', { count: parsedIdeas.length })}</span>
        <span>{t('batch.durationEach', { seconds: durationSeconds })}</span>
        <span>· {generationMode === 'direct_video' ? t('batch.modeT2v') : generationMode === 'direct_references' ? t('batch.modeDirectRefs') : t('batch.modeStartImages')}</span>
        <label className="ml-auto flex items-center gap-1.5">
          <input type="checkbox" checked={continueOnError} onChange={event => setContinueOnError(event.target.checked)} />
          {t('batch.continueOnError')}
        </label>
      </div>
      {directReferencesMissing && <p className="text-[10px] text-amber-300">{t('batch.directRefsMissing')}</p>}
      {generationMode === 'direct_video' && !project.directVideoMasterPrompt.trim() && !project.visualStyle.trim() && (
        <p className="text-[10px] text-fuchsia-200/80">{t('batch.perIdeaStyle')}</p>
      )}
      <button
        className={`${control} w-full border-fuchsia-400/50 bg-fuchsia-500/10 text-fuchsia-100`}
        disabled={!parsedIdeas.length || busy || directReferencesMissing}
        onClick={() => void start()}
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
        {parsedIdeas.length ? t('batch.queue', { count: parsedIdeas.length }) : t('batch.queueEmpty')}
      </button>
      {error && <p className="rounded border border-red-500/30 bg-red-500/10 p-2 text-[10px] text-red-200">{error}</p>}

      <div className="space-y-2">
        {jobs.slice(0, 8).map(job => (
          <details key={job.jobId} className="rounded-md border border-border bg-bg-secondary p-2" open={activeStatuses.has(job.status)}>
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[10px]">
              {activeStatuses.has(job.status) && <Loader2 size={11} className="animate-spin text-fuchsia-300" />}
              <span className="min-w-0 flex-1 truncate font-medium text-text-primary">{job.title}</span>
              <span className="text-text-muted">{job.current}/{job.total}</span>
              <span className="uppercase text-text-muted">{statusLabel(job.status)}</span>
            </summary>
            <p className="mt-1 text-[9px] text-text-muted">{job.message}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {activeStatuses.has(job.status) && <button className={control} onClick={() => void action(job, 'cancel')}><Square size={10} />{t('batch.cancel')}</button>}
              {['failed', 'cancelled', 'interrupted'].includes(job.status) && <button className={control} onClick={() => void action(job, 'resume')}><RefreshCcw size={10} />{t('batch.resume')}</button>}
              {!activeStatuses.has(job.status) && <button className={control} onClick={() => void action(job, 'discard')}><Trash2 size={10} />{t('batch.discardHistory')}</button>}
            </div>
            <div className="mt-2 space-y-1.5">
              {job.items.map(item => (
                <div key={item.index} className={`rounded border p-2 ${itemTone(item.status)}`}>
                  <div className="flex items-start gap-2 text-[10px]">
                    <span className="text-text-muted">#{item.index + 1}</span>
                    <span className="min-w-0 flex-1 text-text-primary">{item.idea}</span>
                    <span className="shrink-0 uppercase text-[9px] text-text-muted">{statusLabel(item.status)}</span>
                  </div>
                  <p className="mt-1 text-[9px] text-text-muted">{item.message}</p>
                  {item.error && <p className="mt-1 text-[9px] text-red-300">{item.error}</p>}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {item.finalOutput && <a className={control} href={api.getFileUrl(item.finalOutput, workspace)} target="_blank" rel="noreferrer"><ExternalLink size={10} />{t('batch.viewVideo')}</a>}
                    {['failed', 'cancelled', 'skipped'].includes(item.status) && !activeStatuses.has(job.status) && <button className={control} onClick={() => void action(job, 'retry-item', item.index)}><RefreshCcw size={10} />{t('batch.retry')}</button>}
                    {['queued', 'interrupted'].includes(item.status) && <button className={control} onClick={() => void action(job, 'skip-item', item.index)}>{t('batch.skip')}</button>}
                  </div>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}
