import type { MiniMaxMusicJob } from '../../api/stories'
import { patchSongCandidateFailed, patchSongCandidateReady } from './musicWorkflowState'
import { isPendingStoryMusicCandidate } from './storySongRecovery'
import type { StoryMusicCandidate, StoryProject } from './types'

export function inFlightJobIds(projects: Record<string, StoryProject>): string[] {
  const ids = new Set<string>()
  Object.values(projects).forEach(project => {
    const rows = [
      ...project.music.cues.flatMap(cue => cue.candidates),
      ...project.music.candidates,
    ]
    rows.forEach(candidate => {
      if (!isPendingStoryMusicCandidate(candidate)) return
      const jobId = candidate.provenance?.jobId?.trim()
      if (jobId) ids.add(jobId)
    })
  })
  return [...ids]
}

function reservedCandidateId(job: MiniMaxMusicJob): string {
  return String(job.candidateId || '').trim()
}

function readyFromJob(candidate: StoryMusicCandidate, job: MiniMaxMusicJob): StoryMusicCandidate | null {
  const rendered = job.candidates?.[0]
  if (!rendered?.filename || !rendered.source) return null
  return patchSongCandidateReady(candidate, {
    filename: rendered.filename,
    source: rendered.source,
    durationSeconds: rendered.duration_seconds,
    taskId: rendered.taskId || rendered.task_id || job.taskId,
    rootTaskId: rendered.rootTaskId || rendered.root_task_id || job.rootTaskId,
    jobId: job.jobId,
  })
}

function applyInFlightJob(
  candidate: StoryMusicCandidate,
  job: MiniMaxMusicJob,
  workspace: string,
): StoryMusicCandidate {
  if (job.workspace && job.workspace !== workspace) return candidate
  const reserved = reservedCandidateId(job)
  if (reserved && reserved !== candidate.id) return candidate
  const ready = readyFromJob(candidate, job)
  if (ready) return ready
  if (job.status === 'failed' || job.status === 'cancelled' || job.status === 'interrupted') {
    return patchSongCandidateFailed(candidate)
  }
  if (candidate.taskId === (job.taskId || candidate.taskId)
    && candidate.rootTaskId === (job.rootTaskId || candidate.rootTaskId)
    && candidate.provenance?.jobId === job.jobId) {
    return candidate
  }
  return {
    ...candidate,
    taskId: job.taskId || candidate.taskId,
    rootTaskId: job.rootTaskId || candidate.rootTaskId,
    provenance: {
      ...candidate.provenance,
      jobId: job.jobId,
      taskId: job.taskId || candidate.provenance?.taskId,
    },
  }
}

function patchPendingWithJob(
  candidate: StoryMusicCandidate,
  jobs: Map<string, MiniMaxMusicJob>,
  claimedAudio: Set<string>,
  workspace: string,
): StoryMusicCandidate {
  if (!isPendingStoryMusicCandidate(candidate)) return candidate
  const jobId = candidate.provenance?.jobId?.trim()
  const job = jobId ? jobs.get(jobId) : undefined
  if (!job) return candidate
  const rendered = job.candidates?.[0]
  if (rendered?.filename && rendered.source && claimedAudio.has(job.jobId)) {
    return candidate
  }
  const patched = applyInFlightJob(candidate, job, workspace)
  if (patched !== candidate && patched.status === 'ready') claimedAudio.add(job.jobId)
  return patched
}

export function recoverInFlightStorySongs(
  projects: Record<string, StoryProject>,
  jobs: MiniMaxMusicJob[],
  context: { workspace: string },
): { projects: Record<string, StoryProject>; changed: boolean } {
  if (!jobs.length) return { projects, changed: false }
  const byId = new Map(jobs.map(job => [job.jobId, job]))
  const claimedAudio = new Set<string>()
  let changed = false
  const next: Record<string, StoryProject> = {}
  Object.entries(projects).forEach(([projectId, project]) => {
    const cues = project.music.cues.map(cue => ({
      ...cue,
      candidates: cue.candidates.map(candidate => (
        patchPendingWithJob(candidate, byId, claimedAudio, context.workspace)
      )),
    }))
    const globalCandidates = project.music.candidates.map(candidate => (
      patchPendingWithJob(candidate, byId, claimedAudio, context.workspace)
    ))
    const reallyChanged = project.music.cues.some((cue, index) => (
      cue.candidates.some((candidate, row) => candidate !== cues[index].candidates[row])
    )) || project.music.candidates.some((candidate, row) => candidate !== globalCandidates[row])
    next[projectId] = reallyChanged
      ? {
          ...project,
          music: { ...project.music, cues, candidates: globalCandidates },
          updatedAt: new Date().toISOString(),
        }
      : project
    if (reallyChanged) changed = true
  })
  return { projects: changed ? next : projects, changed }
}
