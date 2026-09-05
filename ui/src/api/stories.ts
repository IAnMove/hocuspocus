import { rememberPrompt } from '../lib/promptHistory'
import { BASE } from './http'

async function quickVideoBatchResponse(response: Promise<Response>, fallback: string) {
  const resolved = await response
  if (!resolved.ok) {
    const error = await resolved.json().catch(() => ({ detail: fallback }))
    throw new Error(error.detail || fallback)
  }
  return resolved.json()
}

const STORY_STATUS_RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000, 15_000]

export interface MiniMaxMusicCandidate {
  filename: string
  audio_path: string
  source: string
  duration_seconds: number
  provider: 'minimax'
  model: string
  task_id?: string
  root_task_id?: string
  taskId?: string
  rootTaskId?: string
}

export interface MiniMaxMusicJob {
  jobId: string
  taskId: string
  rootTaskId: string
  workspace: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  phase: string
  message: string
  current: number
  total: number
  progress: number
  provider: 'minimax'
  model: string
  candidates: MiniMaxMusicCandidate[]
  error?: string | null
  statusCode?: number
}

export interface StoryMusicCandidateRequest {
  prompt: string
  lyrics: string
  count: 1 | 2 | 3
  model?: 'music-3.0' | 'music-2.6' | 'music-cover' | 'minimax_music3' | 'ace_step_v1_5_xl_sft_lm_4b'
  reference_audio_filename?: string
  instrumental?: boolean
  workspace?: string
  provenance?: {
    actor?: 'user' | 'wizard' | 'system' | 'unknown'
    capability?: string
    project_id?: string
    cue_id?: string
    candidate_id?: string
    song_version?: string
  }
}

export async function startStoryMusicCandidatesJob(
  params: StoryMusicCandidateRequest,
): Promise<MiniMaxMusicJob> {
  const res = await fetch(`${BASE}/api/v1/stories/music-candidates/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music generation failed' }))
    throw new Error(error.detail || 'MiniMax Music generation failed')
  }
  return res.json()
}

export async function fetchStoryMusicCandidatesJob(jobId: string): Promise<MiniMaxMusicJob> {
  const res = await fetch(
    `${BASE}/api/v1/stories/music-candidates/jobs/${encodeURIComponent(jobId)}`,
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music job not found' }))
    throw new Error(error.detail || 'MiniMax Music job not found')
  }
  return res.json()
}

export async function cancelStoryMusicCandidatesJob(jobId: string): Promise<MiniMaxMusicJob> {
  const res = await fetch(
    `${BASE}/api/v1/stories/music-candidates/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST' },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music cancellation failed' }))
    throw new Error(error.detail || 'MiniMax Music cancellation failed')
  }
  return res.json()
}

export async function generateStoryMusicCandidates(
  params: StoryMusicCandidateRequest,
  options: {
    onJobSubmitted?: (job: MiniMaxMusicJob) => void
    onProgress?: (job: MiniMaxMusicJob) => void
  } = {},
): Promise<{
  candidates: MiniMaxMusicCandidate[]
  status: 'completed' | 'cancelled' | 'failed' | 'interrupted'
  jobId: string
  taskId: string
  message: string
}> {
  let job = await startStoryMusicCandidatesJob(params)
  options.onJobSubmitted?.(job)
  let pollFailures = 0
  while (!['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) {
    await new Promise(resolve => window.setTimeout(resolve, pollFailures ? Math.min(10_000, pollFailures * 1_500) : 1_000))
    try {
      job = await fetchStoryMusicCandidatesJob(job.jobId)
      pollFailures = 0
      options.onProgress?.(job)
    } catch (error) {
      pollFailures += 1
      if (pollFailures >= 20) {
        throw new Error(
          `Could not reconnect to MiniMax Music job ${job.jobId}; its ID was preserved: ${(error as Error).message}`,
        )
      }
    }
  }
  if (job.status === 'completed' || job.candidates.length > 0) {
    return {
      candidates: job.candidates,
      status: job.status as 'completed' | 'cancelled' | 'failed' | 'interrupted',
      jobId: job.jobId,
      taskId: job.taskId,
      message: job.message,
    }
  }
  throw new Error(
    `${job.statusCode ? `HTTP ${job.statusCode}: ` : ''}`
    + (job.error || job.message || `MiniMax Music job ${job.status}`),
  )
}

export async function translateStoryLyrics(params: {
  lyrics: string
  targetLanguage: string
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ lyrics: string; targetLanguage: string }> {
  const res = await fetch(`${BASE}/api/v1/stories/translate-lyrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Lyric translation failed' }))
    throw new Error(error.detail || 'Lyric translation failed')
  }
  return res.json()
}

export interface StoryAssetSuggestion {
  index: number
  kind: import('../features/stories/types').StoryAssetKind
  targetId: string
  name: string
  nameOriginal: string
  description: string
  visualPrompt: string
  confidence: number
  reason: string
  source: string
}

export async function analyzeStoryAssets(params: {
  assets: Array<{ name: string; path: string; url: string }>
  description: string
  project: import('../features/stories/types').StoryProject
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
  activity_id: string
}): Promise<{ assets: StoryAssetSuggestion[] }> {
  const response = await fetch(`${BASE}/api/v1/stories/assets/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Smart asset analysis failed' }))
    throw new Error(error.detail || 'Smart asset analysis failed')
  }
  return response.json()
}

export async function generateStorySection(params: {
  scope: import('../features/stories/types').StoryGenerationScope
  premise: string
  language: string
  genre: string
  tone: string
  audience: string
  instruction?: string
  project: import('../features/stories/types').StoryProject
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
  workspace?: string
}, onProgress?: (progress: {
  jobId: string
  status: string
  message: string
  stage: string
  current: number
  total: number
}) => void, signal?: AbortSignal): Promise<{ result: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/v1/stories/generate/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Story generation failed' }))
    throw new Error(err.detail || 'Story generation failed')
  }
  const accepted = await res.json()
  rememberPrompt({
    prompt: params.premise,
    mode: `story-${params.scope}`,
    model: params.writingModel || params.writingProvider,
    workspace: params.workspace,
    source: 'generation',
  })
  window.localStorage.setItem('maestro-last-story-plan-job', accepted.jobId)
  onProgress?.(accepted)
  const cancelRemote = () => {
    void fetch(
      `${BASE}/api/v1/stories/generate/cancel/${encodeURIComponent(accepted.jobId)}`,
      { method: 'POST', keepalive: true },
    )
  }
  signal?.addEventListener('abort', cancelRemote, { once: true })
  try {
    for (;;) {
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          window.clearTimeout(timer)
          reject(new DOMException('Story generation cancelled', 'AbortError'))
        }
        const timer = window.setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, 1000)
        signal?.addEventListener('abort', onAbort, { once: true })
      })
      const status = await getStoryGenerationStatusResilient(
        accepted.jobId,
        signal,
        (attempt, delayMs) => onProgress?.({
          ...accepted,
          status: 'running',
          stage: 'reconnecting',
          message: `Mobile connection interrupted; retrying in ${Math.round(delayMs / 1000)}s (attempt ${attempt})…`,
          current: 0,
          total: 0,
        }),
      )
      onProgress?.(status)
      if (status.status === 'failed' || status.status === 'cancelled') {
        throw new Error(`${status.error || status.message} Resume job: ${accepted.jobId}`)
      }
      if (status.status === 'completed') {
        const result = status.result?.result
        if (!result) throw new Error('Story Lab job completed without a draft')
        window.localStorage.setItem('maestro-last-story-plan-result', JSON.stringify({
          jobId: accepted.jobId,
          projectId: params.project.id,
          scope: params.scope,
          result,
        }))
        return { result }
      }
    }
  } finally {
    signal?.removeEventListener('abort', cancelRemote)
  }
}

export interface StoryLibraryPayload {
  version: 2
  revision: number
  activeId: string
  projects: Record<string, import('../features/stories/types').StoryProject>
}

export async function fetchStoryLibrary(workspace: string): Promise<StoryLibraryPayload> {
  const response = await fetch(
    `${BASE}/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Story Lab library' }))
    throw new Error(error.detail || 'Could not load Story Lab library')
  }
  return response.json()
}

export async function saveStoryLibrary(
  workspace: string,
  library: StoryLibraryPayload,
): Promise<StoryLibraryPayload> {
  const response = await fetch(`${BASE}/api/v1/stories/library`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision, library }),
  })
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (detail && typeof detail === 'object') {
        const conflict = detail as Record<string, unknown>
        if (
          conflict.code === 'story_library_revision_conflict'
          && typeof conflict.currentRevision === 'number'
        ) {
          throw new StoryLibraryRevisionError(
            typeof conflict.message === 'string' ? conflict.message : 'Story library changed in another tab',
            conflict.currentRevision,
          )
        }
      }
      if (typeof detail === 'string') throw new Error(detail)
    }
    throw new Error('Could not save Story Lab library')
  }
  return response.json()
}

export class StoryLibraryRevisionError extends Error {
  readonly currentRevision: number

  constructor(message: string, currentRevision: number) {
    super(message)
    this.name = 'StoryLibraryRevisionError'
    this.currentRevision = currentRevision
  }
}

export async function cancelStoryGeneration(jobId: string): Promise<void> {
  const response = await fetch(
    `${BASE}/api/v1/stories/generate/cancel/${encodeURIComponent(jobId)}`,
    { method: 'POST' },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not cancel Story Lab job' }))
    throw new Error(error.detail || 'Could not cancel Story Lab job')
  }
}

export interface StoryGenerationStatus {
  jobId: string
  taskId?: string | null
  rootTaskId?: string | null
  status: string
  message: string
  stage: string
  current: number
  total: number
  error?: string | null
  result?: { result?: Record<string, unknown> } | null
}

export interface QuickVideoBatchItem {
  index: number
  idea: string
  status: 'queued' | 'planning' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'skipped'
  stage: string
  message: string
  pipelineId?: string | null
  outputFiles: string[]
  finalOutput?: string | null
  error?: string | null
  createdAt: number
  startedAt?: number | null
  finishedAt?: number | null
  progressCurrent: number
  progressTotal: number
}

export interface QuickVideoBatchJob {
  jobId: string
  taskId: string
  workspace: string
  title: string
  status: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  stage: string
  current: number
  total: number
  message: string
  error?: string | null
  continueOnError: boolean
  settings: Record<string, unknown>
  items: QuickVideoBatchItem[]
  createdAt: number
  updatedAt: number
  finishedAt?: number | null
}

export interface QuickVideoBatchStart {
  workspace: string
  title: string
  ideas: string[]
  continueOnError: boolean
  settings: {
    durationSeconds: number
    generationMode: 'direct_video' | 'image_guided' | 'direct_references'
    videoModel: string
    imageModel: string
    resolution: string
    aspectRatio: string
    spokenLanguage: string
    visualStyle: string
    characterVisualStyle: string
    directVideoMasterPrompt: string
    allowClipText: boolean
    writingProvider: string
    writingModel: string
    writingBaseUrl: string
    characters: Array<Record<string, unknown>>
    references: Array<{ source: string; label: string; kind: string }>
  }
}

export async function startQuickVideoBatch(payload: QuickVideoBatchStart): Promise<QuickVideoBatchJob> {
  return quickVideoBatchResponse(fetch(`${BASE}/api/v1/stories/quick-video-batches/start`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }), 'Could not start Quick Video batch')
}

export async function listQuickVideoBatches(workspace: string): Promise<{ jobs: QuickVideoBatchJob[] }> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Quick Video batches')
}

export async function getQuickVideoBatch(jobId: string, workspace: string): Promise<QuickVideoBatchJob> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Quick Video batch')
}

export async function controlQuickVideoBatch(
  jobId: string,
  action: 'cancel' | 'resume' | 'retry-item' | 'skip-item' | 'discard',
  workspace: string,
  itemIndex?: number,
): Promise<QuickVideoBatchJob | { jobId: string; discarded: boolean; outputsPreserved: boolean }> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches/${encodeURIComponent(jobId)}/${action}`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, itemIndex }),
    },
  ), `Could not ${action} Quick Video batch`)
}

function isStoryStatusNetworkError(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof Error && error.name === 'TypeError')
}

function waitForStoryStatusRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Story generation cancelled', 'AbortError'))
      return
    }
    const onAbort = () => {
      window.clearTimeout(timer)
      reject(new DOMException('Story generation cancelled', 'AbortError'))
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, delayMs)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export async function getStoryGenerationStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<StoryGenerationStatus> {
  const response = await fetch(
    `${BASE}/api/v1/stories/generate/status/${encodeURIComponent(jobId)}`,
    { signal },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not read Story Lab job' }))
    throw new Error(error.detail || 'Could not read Story Lab job')
  }
  return response.json()
}

async function getStoryGenerationStatusResilient(
  jobId: string,
  signal?: AbortSignal,
  onRetry?: (attempt: number, delayMs: number) => void,
): Promise<StoryGenerationStatus> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await getStoryGenerationStatus(jobId, signal)
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Story generation cancelled', 'AbortError')
      if (!isStoryStatusNetworkError(error)) throw error
      if (attempt >= STORY_STATUS_RETRY_DELAYS_MS.length) {
        throw new Error(`Connection to HocusPocus is still unavailable. The job remains saved. Resume job: ${jobId}`)
      }
      const delayMs = STORY_STATUS_RETRY_DELAYS_MS[attempt]
      onRetry?.(attempt + 1, delayMs)
      await waitForStoryStatusRetry(delayMs, signal)
    }
  }
}

export async function resumeStoryGeneration(
  jobId: string,
  onProgress?: (progress: {
    jobId: string
    status: string
    message: string
    stage: string
    current: number
    total: number
  }) => void,
  writing?: {
    writingProvider: import('../features/stories/types').StoryWritingProvider
    writingModel?: string
    writingBaseUrl?: string
  },
): Promise<{ result: Record<string, unknown> }> {
  const resumed = await fetch(
    `${BASE}/api/v1/stories/generate/resume/${encodeURIComponent(jobId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(writing || {}),
    },
  )
  if (!resumed.ok) {
    const err = await resumed.json().catch(() => ({ detail: 'Could not resume Story Lab job' }))
    throw new Error(err.detail || 'Could not resume Story Lab job')
  }
  for (;;) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    const status = await getStoryGenerationStatusResilient(
      jobId,
      undefined,
      (attempt, delayMs) => onProgress?.({
        jobId,
        status: 'running',
        stage: 'reconnecting',
        message: `Mobile connection interrupted; retrying in ${Math.round(delayMs / 1000)}s (attempt ${attempt})…`,
        current: 0,
        total: 0,
      }),
    )
    onProgress?.(status)
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error || status.message)
    }
    if (status.status === 'completed') {
      if (!status.result?.result) throw new Error('Story Lab job completed without a draft')
      window.localStorage.setItem('maestro-last-story-plan-result', JSON.stringify({
        jobId,
        result: status.result.result,
      }))
      return { result: status.result.result }
    }
  }
}
