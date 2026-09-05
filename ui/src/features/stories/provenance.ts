import type { StoryMusicCandidate, StoryProduction, StoryProvenance } from './types'

export interface DirectorStoryHandoffIdentity {
  projectId: string
  productionId: string
  cueId?: string
  candidateId?: string
}

/** Build the browser-owned identity passed to a new Director pipeline. */
export function storyDirectorSubmissionProvenance(
  handoff: DirectorStoryHandoffIdentity | null,
): Record<string, string> | undefined {
  if (!handoff) return undefined
  return {
    actor: 'wizard',
    capability: 'start_director_production',
    project_id: handoff.projectId,
    production_id: handoff.productionId,
    ...(handoff.cueId ? { cue_id: handoff.cueId } : {}),
    ...(handoff.candidateId ? { candidate_id: handoff.candidateId } : {}),
  }
}

type RuntimeIds = {
  taskId?: string
  rootTaskId?: string
  jobId?: string
}

export function pendingSongProvenance(input: {
  outputFolder: string
  projectId: string
  cueId: string
  candidateId: string
  startedAt: string
  songVersion?: number
  actor?: StoryProvenance['actor']
}): StoryProvenance {
  return {
    outputFolder: input.outputFolder,
    projectId: input.projectId,
    cueId: input.cueId,
    candidateId: input.candidateId,
    startedAt: input.startedAt,
    songVersion: input.songVersion === undefined ? undefined : String(input.songVersion),
    actor: input.actor || 'wizard',
    tool: 'story_lab',
    capability: 'generate_story_song',
  }
}

export function generatedSongProvenance(input: RuntimeIds & {
  outputFolder: string
  projectId: string
  cueId: string
  candidateId: string
  startedAt: string
  completedAt: string
  songVersion?: number
  actor?: StoryProvenance['actor']
}): StoryProvenance {
  return {
    ...input,
    songVersion: input.songVersion === undefined ? undefined : String(input.songVersion),
    actor: input.actor || 'wizard',
    tool: 'story_lab',
    capability: 'generate_story_song',
  }
}

export function musicVideoProductionProvenance(input: {
  outputFolder: string
  projectId: string
  productionId: string
  cueId: string
  candidate: StoryMusicCandidate
}): StoryProvenance {
  const source = input.candidate.provenance
  return {
    outputFolder: input.outputFolder,
    projectId: input.projectId,
    productionId: input.productionId,
    cueId: input.cueId,
    candidateId: input.candidate.id,
    taskId: input.candidate.taskId || source?.taskId,
    rootTaskId: input.candidate.rootTaskId || source?.rootTaskId,
    jobId: source?.jobId,
    songVersion: input.candidate.version ? String(input.candidate.version) : source?.songVersion,
    actor: 'wizard',
    tool: 'story_lab',
    capability: 'stage_story_music_video',
  }
}

export function directorRunProvenance(
  source: StoryProvenance | undefined,
  outputFolder: string,
  projectId: string,
  productionId: string,
  pipelineId: string,
): StoryProvenance {
  return { ...source, outputFolder, projectId, productionId, pipelineId }
}

export function directorResultDetails(
  production: StoryProduction,
  outputFolder: string,
  projectId: string,
  pipelineId: string,
): Record<string, unknown> {
  return {
    destination: 'director',
    projectId,
    pipelineId,
    productionId: production.id,
    productionTitle: production.title,
    cueId: production.provenance?.cueId,
    candidateId: production.provenance?.candidateId,
    taskId: production.provenance?.taskId,
    rootTaskId: production.provenance?.rootTaskId,
    jobId: production.provenance?.jobId,
    provenance: directorRunProvenance(
      production.provenance, outputFolder, projectId, production.id, pipelineId,
    ),
  }
}
