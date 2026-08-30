import type { SeriesJobStatus } from '../series/types'
import type { SeriesAssemblyJob } from '../series/assemblyContract'

export type AgentStorySection = 'overview' | 'world' | 'characters' | 'relationships' | 'structure' | 'productions'
export type AgentSeriesSection = 'setup' | 'canon' | 'episode' | 'shots' | 'review'
export type AgentSeriesReviewView = 'assembly' | 'history' | 'finish'

const STORY_SECTION_EVENT = 'hocuspocus:story-section'
const SERIES_SECTION_EVENT = 'hocuspocus:series-section'
const STORY_DRAFT_EVENT = 'hocuspocus:story-draft-ready'
const SERIES_PLAN_JOB_EVENT = 'hocuspocus:series-plan-job'
const SERIES_RENDER_JOB_EVENT = 'hocuspocus:series-render-job'
const SERIES_ASSEMBLY_JOB_EVENT = 'hocuspocus:series-assembly-job'
const SERIES_REVIEW_VIEW_EVENT = 'hocuspocus:series-review-view'
let requestedStorySection: AgentStorySection | null = null
let requestedSeriesSection: AgentSeriesSection | null = null
let requestedSeriesPlanJob: SeriesJobStatus | null = null
let requestedSeriesRenderJob: SeriesJobStatus | null = null
let requestedSeriesAssemblyJob: SeriesAssemblyJob | null = null
let requestedSeriesReviewView: AgentSeriesReviewView | null = null

export interface AgentSceneRhythmRequest {
  sceneName: string
  layerName: string
  audioOutputName: string
  cueSource: 'beats' | 'downbeats'
  profile: 'pulse' | 'bounce' | 'peek' | 'camera-punch'
  intensity: number
}

interface PendingSceneRhythmRequest {
  request: AgentSceneRhythmRequest
  resolve: (message: string) => void
  reject: (error: Error) => void
}

const SCENE_RHYTHM_REQUEST_EVENT = 'hocuspocus:scene-rhythm-request'
const pendingSceneRhythmRequests: PendingSceneRhythmRequest[] = []

export function requestAgentSceneRhythm(request: AgentSceneRhythmRequest): Promise<string> {
  return new Promise((resolve, reject) => {
    const pending = { request, resolve, reject }
    pendingSceneRhythmRequests.push(pending)
    window.dispatchEvent(new CustomEvent(SCENE_RHYTHM_REQUEST_EVENT))
  })
}

export function listenForAgentSceneRhythm(
  listener: (request: AgentSceneRhythmRequest) => Promise<string>,
): () => void {
  let active = true
  const drain = async () => {
    while (active && pendingSceneRhythmRequests.length) {
      const pending = pendingSceneRhythmRequests.shift()
      if (!pending) continue
      try { pending.resolve(await listener(pending.request)) }
      catch (error) { pending.reject(error instanceof Error ? error : new Error(String(error))) }
    }
  }
  const handler = () => { void drain() }
  window.addEventListener(SCENE_RHYTHM_REQUEST_EVENT, handler)
  void drain()
  return () => { active = false; window.removeEventListener(SCENE_RHYTHM_REQUEST_EVENT, handler) }
}

export function openAgentStorySection(section: AgentStorySection): void {
  requestedStorySection = section
  window.dispatchEvent(new CustomEvent(STORY_SECTION_EVENT, { detail: { section } }))
}

export function openAgentSeriesSection(section: AgentSeriesSection): void {
  requestedSeriesSection = section
  window.dispatchEvent(new CustomEvent(SERIES_SECTION_EVENT, { detail: { section } }))
}

export function listenForAgentStorySection(
  listener: (section: AgentStorySection) => void,
): () => void {
  const handler = (event: Event) => {
    const section = (event as CustomEvent<{ section?: AgentStorySection }>).detail?.section
    if (section) listener(section)
  }
  window.addEventListener(STORY_SECTION_EVENT, handler)
  if (requestedStorySection) listener(requestedStorySection)
  return () => window.removeEventListener(STORY_SECTION_EVENT, handler)
}

export function listenForAgentSeriesSection(
  listener: (section: AgentSeriesSection) => void,
): () => void {
  const handler = (event: Event) => {
    const section = (event as CustomEvent<{ section?: AgentSeriesSection }>).detail?.section
    if (section) listener(section)
  }
  window.addEventListener(SERIES_SECTION_EVENT, handler)
  if (requestedSeriesSection) listener(requestedSeriesSection)
  return () => window.removeEventListener(SERIES_SECTION_EVENT, handler)
}

export function notifyAgentStoryDraft(projectId: string): void {
  window.dispatchEvent(new CustomEvent(STORY_DRAFT_EVENT, { detail: { projectId } }))
}

export function listenForAgentStoryDraft(listener: (projectId: string) => void): () => void {
  const handler = (event: Event) => {
    const projectId = (event as CustomEvent<{ projectId?: string }>).detail?.projectId
    if (projectId) listener(projectId)
  }
  window.addEventListener(STORY_DRAFT_EVENT, handler)
  return () => window.removeEventListener(STORY_DRAFT_EVENT, handler)
}

export function notifyAgentSeriesPlanJob(job: SeriesJobStatus): void {
  requestedSeriesPlanJob = job
  window.dispatchEvent(new CustomEvent(SERIES_PLAN_JOB_EVENT, { detail: { job, episodeId: job.episodeId } }))
}

export function clearAgentSeriesPlanJob(episodeId: string): void {
  if (requestedSeriesPlanJob?.episodeId === episodeId) requestedSeriesPlanJob = null
  window.dispatchEvent(new CustomEvent(SERIES_PLAN_JOB_EVENT, { detail: { job: null, episodeId } }))
}

export function listenForAgentSeriesPlanJob(
  listener: (job: SeriesJobStatus | null, episodeId: string) => void,
): () => void {
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<{ job?: SeriesJobStatus | null; episodeId?: string }>).detail
    if (detail?.episodeId) listener(detail.job || null, detail.episodeId)
  }
  window.addEventListener(SERIES_PLAN_JOB_EVENT, handler)
  if (requestedSeriesPlanJob) listener(requestedSeriesPlanJob, requestedSeriesPlanJob.episodeId)
  return () => window.removeEventListener(SERIES_PLAN_JOB_EVENT, handler)
}

export function notifyAgentSeriesRenderJob(job: SeriesJobStatus): void {
  requestedSeriesRenderJob = job
  window.dispatchEvent(new CustomEvent(SERIES_RENDER_JOB_EVENT, { detail: { job } }))
}

export function listenForAgentSeriesRenderJob(listener: (job: SeriesJobStatus) => void): () => void {
  const handler = (event: Event) => {
    const job = (event as CustomEvent<{ job?: SeriesJobStatus }>).detail?.job
    if (job) listener(job)
  }
  window.addEventListener(SERIES_RENDER_JOB_EVENT, handler)
  if (requestedSeriesRenderJob) listener(requestedSeriesRenderJob)
  return () => window.removeEventListener(SERIES_RENDER_JOB_EVENT, handler)
}

export function notifyAgentSeriesAssemblyJob(job: SeriesAssemblyJob): void {
  requestedSeriesAssemblyJob = job
  window.dispatchEvent(new CustomEvent(SERIES_ASSEMBLY_JOB_EVENT, { detail: { job } }))
}

export function listenForAgentSeriesAssemblyJob(listener: (job: SeriesAssemblyJob) => void): () => void {
  const handler = (event: Event) => {
    const job = (event as CustomEvent<{ job?: SeriesAssemblyJob }>).detail?.job
    if (job) listener(job)
  }
  window.addEventListener(SERIES_ASSEMBLY_JOB_EVENT, handler)
  if (requestedSeriesAssemblyJob) listener(requestedSeriesAssemblyJob)
  return () => window.removeEventListener(SERIES_ASSEMBLY_JOB_EVENT, handler)
}

export function openAgentSeriesReviewView(view: AgentSeriesReviewView): void {
  requestedSeriesReviewView = view
  window.dispatchEvent(new CustomEvent(SERIES_REVIEW_VIEW_EVENT, { detail: { view } }))
}

export function listenForAgentSeriesReviewView(listener: (view: AgentSeriesReviewView) => void): () => void {
  const handler = (event: Event) => {
    const view = (event as CustomEvent<{ view?: AgentSeriesReviewView }>).detail?.view
    if (view) listener(view)
  }
  window.addEventListener(SERIES_REVIEW_VIEW_EVENT, handler)
  if (requestedSeriesReviewView) listener(requestedSeriesReviewView)
  return () => window.removeEventListener(SERIES_REVIEW_VIEW_EVENT, handler)
}

const ACTIVITY_DETAILS_EVENT = 'hocuspocus:activity-details'
let requestedActivityDetails = false

export function openAgentActivityDetails(): void {
  requestedActivityDetails = true
  window.dispatchEvent(new CustomEvent(ACTIVITY_DETAILS_EVENT))
}

export function listenForAgentActivityDetails(listener: () => void): () => void {
  const handler = () => listener()
  window.addEventListener(ACTIVITY_DETAILS_EVENT, handler)
  if (requestedActivityDetails) listener()
  return () => window.removeEventListener(ACTIVITY_DETAILS_EVENT, handler)
}
