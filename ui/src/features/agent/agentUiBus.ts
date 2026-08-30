import type { SeriesJobStatus } from '../series/types'

export type AgentStorySection = 'overview' | 'world' | 'characters' | 'relationships' | 'structure' | 'productions'
export type AgentSeriesSection = 'setup' | 'canon' | 'episode' | 'shots' | 'review'

const STORY_SECTION_EVENT = 'hocuspocus:story-section'
const SERIES_SECTION_EVENT = 'hocuspocus:series-section'
const STORY_DRAFT_EVENT = 'hocuspocus:story-draft-ready'
const SERIES_PLAN_JOB_EVENT = 'hocuspocus:series-plan-job'
let requestedStorySection: AgentStorySection | null = null
let requestedSeriesSection: AgentSeriesSection | null = null
let requestedSeriesPlanJob: SeriesJobStatus | null = null

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
  window.dispatchEvent(new CustomEvent(SERIES_PLAN_JOB_EVENT, { detail: { job } }))
}

export function listenForAgentSeriesPlanJob(listener: (job: SeriesJobStatus) => void): () => void {
  const handler = (event: Event) => {
    const job = (event as CustomEvent<{ job?: SeriesJobStatus }>).detail?.job
    if (job) listener(job)
  }
  window.addEventListener(SERIES_PLAN_JOB_EVENT, handler)
  if (requestedSeriesPlanJob) listener(requestedSeriesPlanJob)
  return () => window.removeEventListener(SERIES_PLAN_JOB_EVENT, handler)
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
