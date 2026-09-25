import * as api from '../../api/client'
import type { GenerationReceiptLike } from '../../api/generationCommandClient'
import {
  newImageGenerationIntentId,
  submitImageGenerationCommand,
  type ImageGenerationReceipt,
  type StudioImageGenerationCommand,
} from '../../api/imageGenerationCommands'
import type { GenerationJob } from '../../types'
import { UNLOADED_LLM_STATUS } from '../../stores/llmSlice'
import { prependJob, updateJob, withJobs } from '../../stores/jobReducers'
import { finishStudioImageCommand, presentStudioImageCommand } from './imageCommandPresentation'
import {
  fetchCanonicalImageReferences,
  generationDetailsFromParams,
  normalizeStudioImageParams,
  prepareStudioImageCommand,
  resolveStudioImageMedia,
  snapshotStudioImageIntent,
  type ScheduledPromptSubmission,
  type StudioImageIntent,
  type StudioImageIntentSource,
  type StudioImageResolvePorts,
} from './prepareGeneration'
import type { GenerationSubmissionContext } from './generationProvenance'
import i18n from '../../i18n'
import { imageBatchPairs, MAX_IMAGE_BATCH_JOBS } from './imageBatch'
import { mergeVideoPromptLetters } from '../../lib/studioImageEdit'

export type { ScheduledPromptSubmission, StudioImageIntent, StudioImageIntentSource }

const inFlight = new Map<string, Promise<GenerationReceiptLike | void>>()

export type StudioImageJobStatus = {
  status: GenerationJob['status']
  progress: number
  step: number
  total_steps: number
  phase: string
  message: string
  output_files: string[]
  error: string | null
  oom_info?: GenerationJob['oomInfo']
  created_at?: number | null
  started_at?: number | null
  finished_at?: number | null
  queue_position?: number | null
  task_timings?: GenerationJob['taskTimings']
  h3_window_plan?: GenerationJob['h3WindowPlan']
  generation_details?: GenerationJob['generationDetails']
}

export type StudioImageSendPort = (
  command: StudioImageGenerationCommand,
  context?: GenerationSubmissionContext,
) => Promise<ImageGenerationReceipt>

export type StudioImagePorts = StudioImageResolvePorts & {
  unloadLlm: () => Promise<void>
  markLlmUnloaded?: () => void
  persistH3FirstFrame?: () => void
  send: StudioImageSendPort
  now: () => number
  prependJob: (job: GenerationJob) => void
  admitJob: (placeholder: GenerationJob, receipt: ImageGenerationReceipt) => void
  failJob: (placeholder: GenerationJob, message: string) => void
  startPolling?: (jobId: string) => void
  newIntentId: () => string
}

export type StudioImageStoreHost = {
  get: () => StudioImageIntentSource & {
    jobs?: GenerationJob[]
    maybeRefreshGallery?: (opts?: { message?: string; force?: boolean }) => void
    savedParamsPerMode?: Record<string, Record<string, unknown> | undefined>
    params?: Record<string, unknown>
  }
  set: (
    partial: object | ((state: {
      jobs: GenerationJob[]
      params: Record<string, unknown>
      savedParamsPerMode: Record<string, Record<string, unknown> | undefined>
    }) => object),
  ) => void
}

async function unloadLlmIfNeeded(intent: StudioImageIntent, ports: StudioImagePorts): Promise<void> {
  if (!intent.llmLoaded) return
  try {
    await ports.unloadLlm()
    ports.markLlmUnloaded?.()
  } catch { /* best-effort */ }
}

async function defaultSend(
  command: StudioImageGenerationCommand,
  context?: GenerationSubmissionContext,
): Promise<ImageGenerationReceipt> {
  try {
    const receipt = await submitImageGenerationCommand(command, {
      submissionContext: context,
      onSnapshotReady: frozen => presentStudioImageCommand(frozen),
    })
    finishStudioImageCommand(command.intent_id, receipt)
    return receipt
  } catch (error) {
    finishStudioImageCommand(
      command.intent_id,
      undefined,
      error instanceof Error ? error.message : String(error),
    )
    throw error
  }
}

function timestampMs(value: number | null | undefined): number | undefined {
  const timestamp = Number(value)
  if (!Number.isFinite(timestamp) || timestamp <= 0) return undefined
  return timestamp < 1_000_000_000_000 ? timestamp * 1000 : timestamp
}

export function jobTimingPatch(status: StudioImageJobStatus): Partial<GenerationJob> {
  const patch: Partial<GenerationJob> = {}
  if (status.created_at !== undefined) patch.createdAt = timestampMs(status.created_at)
  if (status.started_at !== undefined) patch.startedAt = timestampMs(status.started_at)
  if (status.finished_at !== undefined) patch.finishedAt = timestampMs(status.finished_at)
  if (status.queue_position !== undefined) patch.queuePosition = status.queue_position
  if (status.generation_details) patch.generationDetails = status.generation_details
  return patch
}

function submittingMessage(scheduledPrompt?: ScheduledPromptSubmission): string {
  return scheduledPrompt
    ? `Submitting ${scheduledPrompt.position}/${scheduledPrompt.total}...`
    : 'Submitting...'
}

function placeholderJob(
  params: Record<string, unknown>,
  intent: StudioImageIntent,
  ports: StudioImagePorts,
  scheduledPrompt?: ScheduledPromptSubmission,
): GenerationJob {
  return {
    id: '',
    status: 'queued',
    progress: 0,
    step: 0,
    totalSteps: 0,
    phase: '',
    message: submittingMessage(scheduledPrompt),
    outputFiles: [],
    error: null,
    createdAt: ports.now(),
    oomInfo: null,
    generationDetails: generationDetailsFromParams(params, intent.models),
  }
}

async function runStudioImageGeneration(
  intent: StudioImageIntent,
  ports: StudioImagePorts,
  scheduledPrompt?: ScheduledPromptSubmission,
  context?: GenerationSubmissionContext,
  prepared?: Awaited<ReturnType<typeof prepareStudioImageCommand>>,
): Promise<GenerationReceiptLike | void> {
  const prompt = String(scheduledPrompt?.prompt ?? intent.params.prompt ?? '').trim()
  if (!prompt) {
    throw new Error(i18n.t('studio:generate.addPromptHint'))
  }
  const intentId = context?.commandId || ports.newIntentId()
  const normalized = normalizeStudioImageParams(intent, scheduledPrompt, context)
  const job = placeholderJob(normalized.params, intent, ports, scheduledPrompt)
  let admitted = false
  let retrying: Promise<GenerationReceiptLike | void> | undefined
  job.retry = () => {
    if (retrying) return retrying
    // An acknowledged failed job needs a new command. An uncertain POST
    // replays the exact command/ID so a lost response cannot duplicate work.
    const retryContext = { ...context, actor: context?.actor ?? 'user' as const,
      commandId: admitted ? ports.newIntentId() : intentId }
    retrying = runStudioImageGeneration(
      intent, ports, scheduledPrompt, retryContext, admitted ? undefined : prepared,
    ).finally(() => { retrying = undefined })
    return retrying
  }
  // Publish synchronously, before unloading a model, uploading or resolving
  // images. Keep preparation failures on this same visible, retryable tile.
  ports.prependJob(job)
  try {
    await unloadLlmIfNeeded(intent, ports)
    if (normalized.persistH3FirstFrame) ports.persistH3FirstFrame?.()
    if (!prepared) {
      const errors = await resolveStudioImageMedia(intent, normalized.params, ports)
      prepared = await prepareStudioImageCommand(
        normalized.params, intentId, ports.resolveReferences, errors, intent.localImageFiles,
      )
    }
    const receipt = await ports.send(prepared.command, context)
    admitted = true
    ports.admitJob(job, receipt)
    ports.startPolling?.(receipt.result.job_id)
    return receipt
  } catch (error) {
    ports.failJob(job, error instanceof Error ? error.message : 'Generation failed')
  }
}

/** Snapshot-driven Studio image send. Live UI reads after this starts cannot mix the request. */
export function startStudioImageGeneration(
  intent: StudioImageIntent,
  ports: StudioImagePorts,
  scheduledPrompt?: ScheduledPromptSubmission,
  context?: GenerationSubmissionContext,
): Promise<GenerationReceiptLike | void> {
  const intentId = context?.commandId
  if (intentId) {
    const existing = inFlight.get(intentId)
    if (existing) return existing
  }
  const work = runStudioImageGeneration(intent, ports, scheduledPrompt, context)
  if (!intentId) return work
  inFlight.set(intentId, work)
  void work.finally(() => {
    if (inFlight.get(intentId) === work) inFlight.delete(intentId)
  })
  return work
}

function persistH3FirstFrame(host: StudioImageStoreHost): void {
  host.set(state => ({
    params: { ...state.params, h3_reference_mode: 'first_frame' },
    savedParamsPerMode: {
      ...state.savedParamsPerMode,
      video: {
        ...(state.savedParamsPerMode.video || {}),
        h3_reference_mode: 'first_frame',
        image_refs: undefined,
        h3_ref_videos: undefined,
        h3_ref_audios: undefined,
      },
    },
  }))
}

function applyPolledStatus(job: GenerationJob, status: StudioImageJobStatus): GenerationJob {
  return {
    ...job,
    status: status.status,
    progress: status.progress / 100,
    step: status.step,
    totalSteps: status.total_steps,
    phase: status.phase,
    message: status.message,
    outputFiles: status.output_files,
    error: status.error,
    oomInfo: status.oom_info ?? null,
    taskTimings: status.task_timings ?? [],
    h3WindowPlan: status.h3_window_plan ?? job.h3WindowPlan ?? null,
    ...jobTimingPatch(status),
  }
}

function handlePolledStatus(
  host: StudioImageStoreHost,
  jobId: string,
  status: StudioImageJobStatus,
  stop: () => void,
): void {
  host.set(state => ({
    jobs: state.jobs.map(job => job.id !== jobId ? job : applyPolledStatus(job, status)),
  }))
  if (status.status === 'running') void host.get().maybeRefreshGallery?.()
  if (status.status === 'completed') {
    stop()
    host.set(state => withJobs(state.jobs.filter(job => job.id !== jobId)))
    void host.get().maybeRefreshGallery?.({ message: 'New output ready' })
    return
  }
  if (status.status === 'failed' || status.status === 'cancelled') {
    stop()
    host.set(state => withJobs(state.jobs))
  }
}

async function pollStoreJobOnce(
  host: StudioImageStoreHost,
  jobId: string,
  stop: () => void,
): Promise<void> {
  if (!host.get().jobs?.find(job => job.id === jobId)) {
    stop()
    return
  }
  try {
    handlePolledStatus(host, jobId, await api.fetchJobStatus(jobId), stop)
  } catch (error) {
    console.error('Status poll error:', error)
  }
}

function startStorePolling(host: StudioImageStoreHost, jobId: string): void {
  const pollInterval = setInterval(() => {
    void pollStoreJobOnce(host, jobId, () => clearInterval(pollInterval))
  }, 2000)
}

function admitStoreJob(
  host: StudioImageStoreHost,
  placeholder: GenerationJob,
  receipt: ImageGenerationReceipt,
): void {
  host.set(state => ({
    jobs: state.jobs.map(job => job !== placeholder ? job : {
      ...job,
      id: receipt.result.job_id,
      taskId: receipt.result.task_id || undefined,
      rootTaskId: receipt.result.root_task_id || receipt.result.task_id || undefined,
      status: 'queued' as const,
      message: 'Queued...',
    }),
  }))
}

function failStoreJob(host: StudioImageStoreHost, placeholder: GenerationJob, message: string): void {
  host.set(state => updateJob(state.jobs, job => job === placeholder, job => ({
    ...job,
    id: job.id || `submit-fail-${Date.now()}`,
    status: 'failed',
    message,
    error: message,
  })))
}

export function createStoreImagePorts(host: StudioImageStoreHost): StudioImagePorts {
  return {
    unloadLlm: () => api.unloadLlm(),
    markLlmUnloaded: () => host.set({ llmStatus: UNLOADED_LLM_STATUS }),
    persistH3FirstFrame: () => persistH3FirstFrame(host),
    uploadImage: file => api.uploadImage(file),
    uploadAudio: file => api.uploadAudio(file),
    resolveReferences: fetchCanonicalImageReferences,
    persistDirectorVoicePath: path => host.set({ directorVoiceRefPath: path }),
    send: defaultSend,
    now: () => Date.now(),
    newIntentId: newImageGenerationIntentId,
    prependJob: job => host.set(state => prependJob(state.jobs, job)),
    admitJob: (placeholder, receipt) => admitStoreJob(host, placeholder, receipt),
    failJob: (placeholder, message) => failStoreJob(host, placeholder, message),
    startPolling: jobId => startStorePolling(host, jobId),
  }
}

/**
 * Compatible store entry for the Studio image family. Snapshots get() once
 * before any await so later UI edits cannot contaminate the sent request.
 */
export function startStudioImageGenerationFromStore(
  host: StudioImageStoreHost,
  scheduledPrompt?: ScheduledPromptSubmission,
  context?: GenerationSubmissionContext,
  portOverrides?: Partial<StudioImagePorts>,
): Promise<GenerationReceiptLike | void> {
  const source = host.get()
  const ports = { ...createStoreImagePorts(host), ...portOverrides }
  const batch = !scheduledPrompt && (source.imageBatch?.perLine || (source.imageStudioIntent === 'edit' && source.imageBatch?.enabled))
  if (batch) {
    const pairs = imageBatchPairs(String(source.params?.prompt || ''), source.imageBatch, source.imageStudioIntent === 'edit')
    if (!pairs.length || pairs.length > MAX_IMAGE_BATCH_JOBS) throw new Error(i18n.t('studio:imageBatch.limit', { count: MAX_IMAGE_BATCH_JOBS }))
    if (pairs.some(pair => pair.source) && source.params?.image_mask) throw new Error(i18n.t('studio:imageBatch.noMask'))
    // Freeze every combination before the first await: later form/workspace
    // edits must not alter the rest of an already submitted batch.
    const intents = pairs.map(pair => snapshotStudioImageIntent({ ...source, params: {
      ...source.params, prompt: pair.prompt, repeat_generation: 1, batch_size: 1, multi_prompts_gen_type: 2,
      ...(pair.source ? { image_guide: pair.source.url, image_mask: undefined,
        video_prompt_type: mergeVideoPromptLetters(String(source.params?.video_prompt_type || ''), 'V', 'VAG'),
      } : {}),
    } }))
    const batchId = context?.commandId || ports.newIntentId()
    const pending = inFlight.get(batchId)
    if (pending) return pending
    const work = (async () => {
      let result: GenerationReceiptLike | void = undefined
      let failed = 0
      for (let index = 0; index < intents.length; index++) {
        result = await startStudioImageGeneration(intents[index], ports, undefined, {
          ...context, actor: context?.actor ?? 'user', commandId: `${batchId}-${index + 1}`,
        })
        if (!result) failed++
      }
      if (failed) throw new Error(i18n.t('studio:imageBatch.failed', { count: failed, total: intents.length }))
      return result
    })()
    inFlight.set(batchId, work)
    void work.then(() => inFlight.delete(batchId), () => inFlight.delete(batchId))
    return work
  }
  const intent = snapshotStudioImageIntent(source)
  return startStudioImageGeneration(intent, ports, scheduledPrompt, context)
}
