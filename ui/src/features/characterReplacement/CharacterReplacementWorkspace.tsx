import { useRef } from 'react'
import { Camera, Check, Film, Loader2, Play, Sparkles, Square, UserRound } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../asset-picker/AssetInput'
import { useCharacterReplacement } from './useCharacterReplacement'

type Job = NonNullable<ReturnType<typeof useCharacterReplacement>['session']['imageJob']>
type Controller = ReturnType<typeof useCharacterReplacement>

const activeJob = (job: Job | null) => job?.status === 'submitting' || job?.status === 'running'
const buttonClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-cta px-5 py-3 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40'
const fieldClass = 'w-full rounded-xl border border-border bg-bg-secondary px-3 py-2.5 text-sm text-text-primary disabled:opacity-50'
const panelClass = 'rounded-2xl border border-border bg-bg-secondary/50 p-4 md:p-6'

function frameClock(value: number) {
  const time = Math.max(0, Number.isFinite(value) ? value : 0)
  return `${Math.floor(time / 60)}:${(time % 60).toFixed(1).padStart(4, '0')}`
}

function JobFeedback({ job, cancel }: { job: Job | null; cancel: () => void }) {
  const { t } = useUiTranslation('studio')
  if (!job) return null
  const running = activeJob(job)
  const progress = typeof job.progress === 'number' && Number.isFinite(job.progress)
    ? Math.round(Math.min(100, Math.max(0, job.progress))) : null
  return <div className="space-y-2 text-sm">
    <div role={job.status === 'failed' ? 'alert' : 'status'} className="flex flex-wrap items-center gap-2 text-text-secondary">
      {running && <Loader2 size={16} className="animate-spin" />}
      {job.status === 'completed' && <Check size={16} className="text-green-400" />}
      <span>{t(`characterReplacement.status.${job.status}`)}</span>
      {running && progress !== null && <span>{progress}%</span>}
      {running && <button type="button" onClick={cancel} disabled={!job.id} className="ml-auto inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3 py-2 hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40">
        <Square size={12} />{t('characterReplacement.cancel')}
      </button>}
    </div>
    {(job.error || job.message) && <p className={job.error ? 'break-words text-red-300' : 'break-words text-text-muted'}>{job.error || job.message}</p>}
  </div>
}

function SourceStep({ controller }: { controller: Controller }) {
  const { t } = useUiTranslation('studio')
  const { workspace, session, busy } = controller
  const video = useRef<HTMLVideoElement>(null)
  const locked = busy || session.extracting
  const seek = (time: number) => {
    if (video.current) video.current.currentTime = time
    controller.setFrameTime(time)
  }
  const capture = () => {
    video.current?.pause()
    void controller.captureFrame(video.current?.currentTime ?? session.frameTime)
  }

  return <section aria-labelledby="replacement-source-title" className={panelClass}>
      <div className="mb-5 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-blue/15 font-semibold text-accent-blue">1</span>
        <div><h2 id="replacement-source-title" className="text-lg font-semibold text-text-primary">{t('characterReplacement.sourceTitle')}</h2>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">{t('characterReplacement.frameHint')}</p></div>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <div className="min-w-0 space-y-4">
          <AssetInput key={`source-${workspace}`} label={t('characterReplacement.sourceVideo')} placeholder={t('characterReplacement.sourcePlaceholder')}
            items={[]} value={session.source || undefined} workspaceId={workspace} accept="video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v" optional
            constraints={{ kinds: ['video'], maxCount: 1, optional: true }} disabled={locked} onChoose={controller.setSource} />
          {session.source && <>
            <video key={session.source.url} ref={video} src={session.source.url} controls preload="metadata"
              aria-label={t('characterReplacement.sourceVideo')} className="max-h-[440px] w-full rounded-xl bg-black object-contain"
              onLoadedMetadata={event => {
                const element = event.currentTarget
                controller.setVideoMetadata({ duration: element.duration, width: element.videoWidth, height: element.videoHeight })
              }}
              onTimeUpdate={event => { if (!locked) controller.setFrameTime(event.currentTarget.currentTime) }} />
            <div className="space-y-3">
              <label className="flex items-center justify-between gap-3 text-sm text-text-secondary" htmlFor="replacement-frame-time">
                {t('characterReplacement.framePosition')}<span className="tabular-nums">{frameClock(session.frameTime)} / {frameClock(session.duration)}</span>
              </label>
              <input aria-label={t('characterReplacement.framePosition')} id="replacement-frame-time" type="range" min="0" max={Math.max(0, session.duration)} step="0.01" value={session.frameTime}
                disabled={locked || session.duration <= 0} onChange={event => seek(Number(event.target.value))} className="w-full accent-accent-blue" />
              <button type="button" onClick={capture} disabled={locked || session.duration <= 0} className={buttonClass}>
                {session.extracting ? <Loader2 size={17} className="animate-spin" /> : <Camera size={17} />}
                {t(session.extracting ? 'characterReplacement.capturing' : 'characterReplacement.useFrame')}
              </button>
              <p className="text-xs leading-relaxed text-text-muted">{t('characterReplacement.fullVideoHint')}</p>
            </div>
          </>}
        </div>
        <div className="min-w-0 space-y-3">
          <h3 className="text-sm font-medium text-text-primary">{t('characterReplacement.originalFrame')}</h3>
          {session.frame ? <>
            <img src={session.frame.url} alt={t('characterReplacement.originalFrame')} className="max-h-[440px] w-full rounded-xl bg-black object-contain" />
            <p className="text-sm text-text-secondary">{t('characterReplacement.frameSelected', { time: frameClock(session.frame.time) })}</p>
          </> : <div className="flex min-h-56 items-center justify-center gap-3 rounded-xl border border-dashed border-border p-6 text-center text-sm text-text-muted">
            <Camera size={24} className="shrink-0" />{t('characterReplacement.frameEmpty')}
          </div>}
        </div>
      </div>
    </section>
}

function ImageStep({ controller }: { controller: Controller }) {
  const { t } = useUiTranslation('studio')
  const { workspace, session, busy, imageModels } = controller
  const locked = busy || session.extracting
  const imageRunning = activeJob(session.imageJob)
  const readyToEdit = !!session.frame && !!session.character && !!session.prompt.trim()
    && imageModels.some(model => model.model_type === session.modelType)
  return <section aria-labelledby="replacement-image-title" className={panelClass}>
      <div className="mb-5 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-blue/15 font-semibold text-accent-blue">2</span>
        <div><h2 id="replacement-image-title" className="text-lg font-semibold text-text-primary">{t('characterReplacement.imageTitle')}</h2>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">{t('characterReplacement.imageHint')}</p></div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_1.5fr]">
        <div className="min-w-0 space-y-3">
          <AssetInput key={`character-${workspace}`} label={t('characterReplacement.characterImage')} placeholder={t('characterReplacement.characterPlaceholder')}
            items={[]} value={session.character || undefined} workspaceId={workspace} accept="image/*" optional
            constraints={{ kinds: ['image'], maxCount: 1, optional: true }} disabled={locked} onChoose={controller.setCharacter} />
          {session.character && <img src={session.character.url} alt={t('characterReplacement.characterImage')} className="max-h-80 w-full rounded-xl bg-black object-contain" />}
        </div>
        <div className="min-w-0 space-y-4">
          <label className="block space-y-2 text-sm text-text-secondary">
            <span>{t('characterReplacement.imageModel')}</span>
            <select aria-label={t('characterReplacement.imageModel')} value={session.modelType} disabled={locked || imageModels.length === 0} onChange={event => controller.setModel(event.target.value)} className={fieldClass}>
              {imageModels.length === 0 && <option value="">{t('characterReplacement.noImageModels')}</option>}
              {imageModels.map(model => <option key={model.model_type} value={model.model_type}>{model.name}</option>)}
            </select>
          </label>
          <label className="block space-y-2 text-sm text-text-secondary">
            <span>{t('characterReplacement.prompt')}</span>
            <textarea aria-label={t('characterReplacement.prompt')} value={session.prompt} rows={6} disabled={locked} onChange={event => controller.setPrompt(event.target.value)} className={`${fieldClass} min-h-40 resize-y leading-relaxed`} />
          </label>
          <p className="text-xs leading-relaxed text-text-muted">{t('characterReplacement.referencesHint')}</p>
          <button type="button" onClick={() => void controller.generateFrame()} disabled={locked || !readyToEdit} className={buttonClass}>
            {imageRunning ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}{t('characterReplacement.generateFrame')}
          </button>
          <JobFeedback job={session.imageJob} cancel={() => void controller.cancelImage()} />
        </div>
      </div>
      {session.replacement && <div className="mt-6 space-y-3 border-t border-border pt-5">
        <h3 className="text-sm font-medium text-text-primary">{t('characterReplacement.replacementFrame')}</h3>
        <img src={session.replacement.url} alt={t('characterReplacement.replacementFrame')} className="max-h-[520px] w-full rounded-xl bg-black object-contain" />
        <p className="text-sm leading-relaxed text-text-secondary">{t('characterReplacement.reviewHint')}</p>
      </div>}
    </section>
}

function VideoStep({ controller }: { controller: Controller }) {
  const { t } = useUiTranslation('studio')
  const { session, busy } = controller
  const locked = busy || session.extracting
  const videoRunning = activeJob(session.videoJob)
  return <section aria-labelledby="replacement-video-title" className={panelClass}>
      <div className="mb-5 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-blue/15 font-semibold text-accent-blue">3</span>
        <div><h2 id="replacement-video-title" className="text-lg font-semibold text-text-primary">{t('characterReplacement.videoTitle')}</h2>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">{t('characterReplacement.videoHint')}</p></div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2 text-sm"><p className="text-text-secondary">{t('characterReplacement.videoModel')}</p><p className="flex items-center gap-2 py-2.5 font-medium text-text-primary"><Film size={17} />Viggle-Animate Pruned 20B</p></div>
        <label className="block space-y-2 text-sm text-text-secondary"><span>{t('characterReplacement.quality')}</span>
          <select aria-label={t('characterReplacement.quality')} value={session.quality} disabled={locked} onChange={event => controller.setQuality(event.target.value as '480p' | '512p' | '704p')} className={fieldClass}>
            <option value="480p">480p</option><option value="512p">512p</option><option value="704p">704p</option>
          </select>
        </label>
        <label className="block space-y-2 text-sm text-text-secondary"><span>{t('characterReplacement.audio')}</span>
          <select aria-label={t('characterReplacement.audio')} value={session.audio} disabled={locked} onChange={event => controller.setAudio(event.target.value as 'source' | 'generated')} className={fieldClass}>
            <option value="source">{t('characterReplacement.sourceAudio')}</option><option value="generated">{t('characterReplacement.generatedAudio')}</option>
          </select>
        </label>
      </div>
      <div className="mt-5 space-y-3">
        <p className="text-xs leading-relaxed text-text-muted">{t('characterReplacement.downloadHint')}</p>
        <button type="button" onClick={() => void controller.generateVideo()} disabled={locked || !session.replacement} className={buttonClass}>
          {videoRunning ? <Loader2 size={17} className="animate-spin" /> : <Play size={17} />}{t('characterReplacement.generateVideo')}
        </button>
        <JobFeedback job={session.videoJob} cancel={() => void controller.cancelVideo()} />
      </div>
      {session.videoResult && <div className="mt-6 space-y-3 border-t border-border pt-5">
        <h3 className="text-sm font-medium text-text-primary">{t('characterReplacement.videoResult')}</h3>
        <video src={session.videoResult.url} controls preload="metadata" aria-label={t('characterReplacement.videoResult')} className="max-h-[620px] w-full rounded-xl bg-black object-contain" />
      </div>}
    </section>
}

export function CharacterReplacementWorkspace() {
  const { t } = useUiTranslation('studio')
  const controller = useCharacterReplacement()
  const { session } = controller
  return <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 md:p-8">
    <header className="space-y-2">
      <h1 className="flex items-center gap-3 text-2xl font-semibold text-text-primary"><UserRound size={26} />{t('characterReplacement.title')}</h1>
      <p className="max-w-3xl text-sm leading-relaxed text-text-secondary">{t('characterReplacement.intro')}</p>
    </header>
    {session.error && session.error !== session.imageJob?.error && session.error !== session.videoJob?.error
      && <p role="alert" className="rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-300">{session.error}</p>}
    <SourceStep controller={controller} />
    <ImageStep controller={controller} />
    <VideoStep controller={controller} />
  </div>
}
