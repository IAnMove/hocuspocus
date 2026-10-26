import { animationRequest, postBody, type AnimationJobStatus } from './characterAnimationJobs'
import type { AnimationSetName } from '../lib/characterAnimations'

/** The server job that makes several animations of a saved character in turn (services/character_animation_set_job.py): the full walks of
 * the five directions. The «Crear andares completos» button, the characters.animation.make_set MCP tool and the Wizard start it. */
export type AnimationSetSheetStatus = 'waiting' | 'running' | 'completed' | 'skipped' | 'failed' | 'cancelled'
export type AnimationSetSheet = {
  animationId: string; status: AnimationSetSheetStatus
  /** The animation job that makes this sheet: its poses show in the card of the animation. */
  jobId?: string; reason?: string; reference?: string; reviewState?: string; error?: string
  /** «Modo un solo disparo»: the sheet's automatic checks ran; `failed` lists the ones that did not pass. */
  autoApproved?: boolean; failed?: string[]
}
export type AnimationSetJob = {
  jobId: string; kind: 'set'; workspace: string; kitId: string; set: AnimationSetName; title: string; model: string
  status: AnimationJobStatus; sheets: AnimationSetSheet[]; done: number; total: number
  error?: string; errorCode?: string; createdAt: number; updatedAt: number; finishedAt?: number
  autoApprove?: boolean; autoApproveNote?: string
}

export const isActiveSet = (job: Pick<AnimationSetJob, 'status'>): boolean => job.status === 'queued' || job.status === 'running' || job.status === 'cancelling'

export async function startAnimationSet(details: { workspace: string; kitId: string; set: AnimationSetName; model?: string; autoApprove?: boolean; method?: 'poses' | 'video' | 'puppet' }): Promise<AnimationSetJob> {
  return (await animationRequest<{ job: AnimationSetJob }>('/make-set', postBody(details), 'Could not start the set of animations')).job
}

/** The workspace's set jobs, newest first. */
export async function fetchAnimationSets(workspace: string, kitId?: string): Promise<AnimationSetJob[]> {
  const query = new URLSearchParams({ workspace, ...(kitId ? { kitId } : {}) })
  return (await animationRequest<{ jobs: AnimationSetJob[] }>(`/sets?${query}`, undefined, 'Could not read the sets of animations')).jobs
}

export async function cancelAnimationSet(workspace: string, jobId: string): Promise<AnimationSetJob> {
  return (await animationRequest<{ job: AnimationSetJob }>(`/sets/${encodeURIComponent(jobId)}/cancel`, postBody({ workspace }), 'Could not cancel the set of animations')).job
}
