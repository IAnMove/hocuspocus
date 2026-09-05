import type { AssetCatalogItem } from '../../api/assets'
import type { OutputMetadata } from '../../types'
import type { StoryLibraryData } from './library'
import { patchSongCandidateReady } from './musicWorkflowState'
import type { StoryMusicCandidate, StoryProject } from './types'

export interface StorySongOutputRef {
  candidateId: string
  filename: string
  source: string
  projectId?: string
  cueId?: string
  outputFolder?: string
  taskId?: string
  rootTaskId?: string
  jobId?: string
  durationSeconds?: number
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function nestedRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = textValue(value)
    if (text) return text
  }
  return ''
}

function executionRecord(sidecar: Record<string, unknown>): Record<string, unknown> {
  return nestedRecord(sidecar.execution) || sidecar
}

export function storySongOutputRefFromSidecar(
  filename: string,
  source: string,
  sidecar: Record<string, unknown> | undefined,
): StorySongOutputRef | null {
  if (!sidecar) return null
  const execution = executionRecord(sidecar)
  const origin = nestedRecord(sidecar.origin)
  const params = nestedRecord(sidecar.params)
  const candidateId = firstText(execution.candidate_id, params?.candidate_id, sidecar.candidate_id)
  if (!candidateId) return null
  const project = nestedRecord(origin?.project)
  return {
    candidateId,
    filename: firstText(sidecar.filename, filename),
    source,
    projectId: firstText(project?.id, origin?.project_id, params?.project_id),
    cueId: firstText(execution.cue_id, params?.cue_id),
    outputFolder: firstText(origin?.output_folder, params?.output_folder),
    taskId: firstText(execution.task_id, params?.task_id),
    rootTaskId: firstText(execution.root_task_id, params?.root_task_id),
    jobId: firstText(execution.job_id, params?.job_id),
  }
}

function mergeSongRefs(
  filename: string,
  source: string,
  primary: StorySongOutputRef | null,
  extras: Record<string, unknown>,
): StorySongOutputRef | null {
  const candidateId = firstText(primary?.candidateId, extras.candidate_id)
  if (!candidateId) return null
  return {
    candidateId,
    filename,
    source,
    projectId: firstText(primary?.projectId, extras.project_id),
    cueId: firstText(primary?.cueId, extras.cue_id),
    outputFolder: firstText(primary?.outputFolder, extras.output_folder),
    taskId: firstText(primary?.taskId, extras.task_id),
    rootTaskId: primary?.rootTaskId,
    jobId: firstText(primary?.jobId, extras.job_id),
  }
}

export function storySongOutputRefFromAsset(asset: AssetCatalogItem): StorySongOutputRef | null {
  const fromManifest = storySongOutputRefFromSidecar(
    asset.filename,
    asset.url,
    nestedRecord(asset.manifest),
  )
  const execution = asset.execution as Record<string, unknown>
  const project = nestedRecord(asset.origin.project)
  return mergeSongRefs(asset.filename, asset.url, fromManifest, {
    candidate_id: execution.candidate_id,
    project_id: project?.id,
    cue_id: execution.cue_id,
    output_folder: asset.origin.output_folder,
    task_id: execution.task_id,
    job_id: execution.job_id,
  })
}

export function storySongOutputRefFromMetadata(
  filename: string,
  source: string,
  metadata: OutputMetadata | null | undefined,
): StorySongOutputRef | null {
  if (!metadata) return null
  const params = nestedRecord(metadata.params)
  return storySongOutputRefFromSidecar(filename, source, {
    ...params,
    params,
    execution: nestedRecord(params?.execution) || params,
    origin: nestedRecord(params?.origin),
    candidate_id: params?.candidate_id,
    filename,
  })
}

export function isPendingStoryMusicCandidate(candidate: StoryMusicCandidate): boolean {
  return candidate.status === 'pending' || (!candidate.source.trim() && candidate.status !== 'failed')
}

export function libraryHasPendingSongs(library: Pick<StoryLibraryData, 'projects'>): boolean {
  return Object.values(library.projects).some(project => (
    project.music.cues.some(cue => cue.candidates.some(isPendingStoryMusicCandidate))
    || project.music.candidates.some(isPendingStoryMusicCandidate)
  ))
}

function matchingOutput(
  project: StoryProject,
  cueId: string | undefined,
  candidate: StoryMusicCandidate,
  outputs: StorySongOutputRef[],
): StorySongOutputRef | undefined {
  return outputs.find(output => {
    if (output.candidateId !== candidate.id) return false
    if (output.projectId && output.projectId !== project.id) return false
    if (output.cueId && cueId && output.cueId !== cueId) return false
    return true
  })
}

export function recoverPendingStorySongs(
  projects: Record<string, StoryProject>,
  outputs: StorySongOutputRef[],
): { projects: Record<string, StoryProject>; changed: boolean } {
  if (!outputs.length) return { projects, changed: false }
  let changed = false
  const next: Record<string, StoryProject> = {}
  Object.entries(projects).forEach(([projectId, project]) => {
    let projectChanged = false
    const cues = project.music.cues.map(cue => {
      const candidates = cue.candidates.map(candidate => {
        if (!isPendingStoryMusicCandidate(candidate)) return candidate
        const output = matchingOutput(project, cue.id, candidate, outputs)
        if (!output?.source) return candidate
        projectChanged = true
        return patchSongCandidateReady(candidate, {
          filename: output.filename,
          source: output.source,
          durationSeconds: output.durationSeconds,
          taskId: output.taskId,
          rootTaskId: output.rootTaskId,
          jobId: output.jobId,
        })
      })
      return projectChanged ? { ...cue, candidates } : cue
    })
    const globalCandidates = project.music.candidates.map(candidate => {
      if (!isPendingStoryMusicCandidate(candidate)) return candidate
      const output = matchingOutput(project, undefined, candidate, outputs)
      if (!output?.source) return candidate
      projectChanged = true
      return patchSongCandidateReady(candidate, {
        filename: output.filename,
        source: output.source,
        durationSeconds: output.durationSeconds,
        taskId: output.taskId,
        rootTaskId: output.rootTaskId,
        jobId: output.jobId,
      })
    })
    next[projectId] = projectChanged
      ? {
          ...project,
          music: { ...project.music, cues, candidates: globalCandidates },
          updatedAt: new Date().toISOString(),
        }
      : project
    if (projectChanged) changed = true
  })
  return { projects: changed ? next : projects, changed }
}
