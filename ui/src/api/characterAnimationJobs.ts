import { BASE } from './http'

/** The server job that makes one animation of a saved character (services/character_animation_job.py): the Character Creator
 * panel, the characters.animation.* MCP tools and the Wizard all start it. */
export type AnimationTakeStatus = 'waiting' | 'reused' | 'generating' | 'keying' | 'ready' | 'failed'
export type AnimationTake = { id: string; status: AnimationTakeStatus; seed: number; raw?: string; keyed?: string; error?: string }
export type AnimationJobStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export type AnimationJob = {
  jobId: string; workspace: string; kitId: string; animationId: string; title: string; model: string
  status: AnimationJobStatus; stage: 'poses' | 'sheet'; takes: AnimationTake[]
  /** The pose being made again alone, when there is one. */
  remake?: string | null
  /** The words of an animation the author described: the job keeps them, so it can be shown and tried again from any page load. */
  custom?: CustomAnimationRequest
  error?: string; errorCode?: string; createdAt: number; updatedAt: number; finishedAt?: number
  result?: { animation: string; reviewState: string; sheet: string; count: number; frames: string[]; scaleBy: string }
}
/** An animation of the author's own: a name, a framing and the words of each pose (up to six). */
export type CustomAnimationRequest = { title: string; view: 'bust' | 'front' | 'side'; poses: string[] }

export const ACTIVE_STATUSES: AnimationJobStatus[] = ['queued', 'running', 'cancelling']
export const isActiveJob = (job: Pick<AnimationJob, 'status'>): boolean => ACTIVE_STATUSES.includes(job.status)

async function request<T>(path: string, init: RequestInit | undefined, fallback: string): Promise<T> {
  const response = await fetch(`${BASE}/api/v1/character-kits/animations${path}`, init)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: fallback }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : fallback)
  }
  return response.json()
}

const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export async function startAnimationJob(details: {
  workspace: string; kitId: string; animation: string; model?: string; pose?: string; custom?: CustomAnimationRequest
}): Promise<AnimationJob> {
  return (await request<{ job: AnimationJob }>('/make', post(details), 'Could not start the animation')).job
}

/** The workspace's animation jobs, newest first. */
export async function fetchAnimationJobs(workspace: string, kitId?: string): Promise<AnimationJob[]> {
  const query = new URLSearchParams({ workspace, ...(kitId ? { kitId } : {}) })
  return (await request<{ jobs: AnimationJob[] }>(`/jobs?${query}`, undefined, 'Could not read the animation jobs')).jobs
}

export async function fetchAnimationJob(workspace: string, jobId: string): Promise<AnimationJob> {
  return (await request<{ job: AnimationJob }>(`/jobs/${encodeURIComponent(jobId)}?${new URLSearchParams({ workspace })}`, undefined, 'Could not read the animation job')).job
}

export async function cancelAnimationJob(workspace: string, jobId: string): Promise<AnimationJob> {
  return (await request<{ job: AnimationJob }>(`/jobs/${encodeURIComponent(jobId)}/cancel`, post({ workspace }), 'Could not cancel the animation')).job
}
