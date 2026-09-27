import type { MusicVideoAdaptation } from './adaptations'
import { generatedSongProvenance, musicVideoProductionProvenance, pendingSongProvenance } from './provenance'
import type {
  StoryMusicCandidate,
  StoryMusicCue,
  StoryProduction,
  StoryProject,
  StoryProvenance,
} from './types'

function songCandidateLanguage(project: StoryProject, cue: StoryMusicCue): string {
  return cue.lyricsLanguage || project.language
}

export function buildPendingSongCandidate(input: {
  project: StoryProject
  cue: StoryMusicCue
  candidateId: string
  version: number
  model: StoryMusicCandidate['model']
  provider?: StoryMusicCandidate['provider']
  provenance: StoryProvenance
}): StoryMusicCandidate {
  const { project, cue } = input
  const language = songCandidateLanguage(project, cue)
  return {
    id: input.candidateId,
    displayName: `${cue.title} · ${language} · v${input.version}`,
    title: cue.title,
    language,
    version: input.version,
    name: '',
    source: '',
    prompt: cue.style,
    lyrics: cue.instrumental ? '' : cue.lyrics,
    provider: input.provider || 'local',
    model: input.model,
    durationSeconds: cue.durationSeconds,
    createdAt: new Date().toISOString(),
    status: 'pending',
    executionPhase: 'prepared',
    provenance: pendingSongProvenance({
      outputFolder: input.provenance.outputFolder || '',
      projectId: project.id,
      cueId: cue.id,
      candidateId: input.candidateId,
      startedAt: input.provenance.startedAt || new Date().toISOString(),
      songVersion: input.version,
      actor: input.provenance.actor,
    }),
  }
}

export function patchSongCandidateReady(
  candidate: StoryMusicCandidate,
  patch: {
    filename: string
    source: string
    durationSeconds?: number
    taskId?: string
    rootTaskId?: string
    jobId?: string
    completedAt?: string
    provenance?: StoryProvenance
  },
): StoryMusicCandidate {
  const completedAt = patch.completedAt || new Date().toISOString()
  const provenance = patch.provenance || generatedSongProvenance({
    outputFolder: candidate.provenance?.outputFolder || '',
    projectId: candidate.provenance?.projectId || '',
    cueId: candidate.provenance?.cueId || '',
    candidateId: candidate.id,
    startedAt: candidate.provenance?.startedAt || candidate.createdAt,
    completedAt,
    songVersion: candidate.version,
    actor: candidate.provenance?.actor,
    taskId: patch.taskId,
    rootTaskId: patch.rootTaskId,
    jobId: patch.jobId,
  })
  return {
    ...candidate,
    name: patch.filename,
    source: patch.source,
    durationSeconds: patch.durationSeconds ?? candidate.durationSeconds,
    status: 'ready',
    executionPhase: 'terminal',
    taskId: patch.taskId || candidate.taskId,
    rootTaskId: patch.rootTaskId || candidate.rootTaskId,
    provenance: {
      ...candidate.provenance,
      ...provenance,
      candidateId: candidate.id,
      completedAt,
    },
  }
}

export function patchSongCandidateFailed(candidate: StoryMusicCandidate): StoryMusicCandidate {
  return {
    ...candidate,
    status: 'failed',
    executionPhase: 'terminal',
    provenance: {
      ...candidate.provenance,
      candidateId: candidate.id,
      completedAt: new Date().toISOString(),
    },
  }
}

function keepSelectedCandidateId(current: string | undefined, candidateId: string): string {
  return current || candidateId
}

export function overlayCueMusicCandidate(
  project: StoryProject,
  cueId: string,
  candidate: StoryMusicCandidate,
): StoryProject {
  return {
    ...project,
    music: {
      ...project.music,
      cues: project.music.cues.map(item => item.id === cueId ? {
        ...item,
        candidates: item.candidates.some(existing => existing.id === candidate.id)
          ? item.candidates.map(existing => existing.id === candidate.id
            ? { ...existing, ...candidate, id: candidate.id }
            : existing)
          : [...item.candidates, candidate],
        selectedCandidateId: keepSelectedCandidateId(item.selectedCandidateId, candidate.id),
      } : item),
    },
  }
}

/** Keep every server cue row after a 409 rebase. Overlaying only the row this
 * persist wrote drops a sibling candidate the retry PUT already accepted, and
 * mapping over live cues cannot attach a cue the local snapshot never loaded. */
export function overlaySavedCueCandidates(
  live: StoryProject,
  saved: StoryProject,
): StoryProject {
  const liveCueIds = new Set(live.music.cues.map(cue => cue.id))
  const remoteOnlyCues = saved.music.cues.filter(cue => !liveCueIds.has(cue.id))
  const base = remoteOnlyCues.length === 0
    ? live
    : {
        ...live,
        music: {
          ...live.music,
          cues: [...live.music.cues, ...remoteOnlyCues],
        },
      }
  return saved.music.cues.reduce(
    (next, cue) => cue.candidates.reduce(
      (project, candidate) => overlayCueMusicCandidate(project, cue.id, candidate),
      next,
    ),
    base,
  )
}

export function upsertCueMusicCandidate(
  project: StoryProject,
  cueId: string,
  candidate: StoryMusicCandidate,
): StoryProject {
  return {
    ...project,
    revision: project.revision + 1,
    music: {
      ...project.music,
      selectedCandidateId: project.music.selectedCandidateId,
      cues: project.music.cues.map(item => item.id === cueId ? {
        ...item,
        candidates: item.candidates.some(existing => existing.id === candidate.id)
          ? item.candidates.map(existing => existing.id === candidate.id ? candidate : existing)
          : [...item.candidates, candidate],
        selectedCandidateId: keepSelectedCandidateId(item.selectedCandidateId, candidate.id),
      } : item),
    },
    updatedAt: new Date().toISOString(),
  }
}

export function buildGeneratedSongCandidate(input: {
  project: StoryProject
  cue: StoryMusicCue
  candidateId: string
  version: number
  filename: string
  source: string
  model: StoryMusicCandidate['model']
  taskId?: string
  rootTaskId?: string
  provenance: StoryProvenance
}): StoryMusicCandidate {
  return patchSongCandidateReady(buildPendingSongCandidate({
    project: input.project,
    cue: input.cue,
    candidateId: input.candidateId,
    version: input.version,
    model: input.model,
    provenance: input.provenance,
  }), {
    filename: input.filename,
    source: input.source,
    taskId: input.taskId,
    rootTaskId: input.rootTaskId,
    provenance: generatedSongProvenance({
      ...input.provenance,
      projectId: input.project.id,
      cueId: input.cue.id,
      candidateId: input.candidateId,
      songVersion: input.version,
    } as Parameters<typeof generatedSongProvenance>[0]),
  })
}

export function buildMusicVideoProduction(input: {
  id: string
  createdAt?: string
  project: StoryProject
  cue: StoryMusicCue
  candidate: StoryMusicCandidate
  adaptation: MusicVideoAdaptation
  pacing: string
  outputFolder: string
}): StoryProduction {
  const { project, cue, candidate, adaptation } = input
  const provenance = musicVideoProductionProvenance({
    outputFolder: input.outputFolder,
    projectId: project.id,
    productionId: input.id,
    cueId: cue.id,
    candidate,
  })
  return {
    id: input.id,
    kind: 'music_video',
    title: `${adaptation.focusLabel} · music video`,
    createdAt: input.createdAt || new Date().toISOString(),
    sourceVersion: project.revision,
    sourceSnapshot: { ...structuredClone(project), productions: [] },
    targetId: adaptation.focusTargetId,
    targetName: adaptation.focusLabel,
    targetSnapshot: {
      cueId: cue.id,
      cueTitle: cue.title,
      candidateId: candidate.id,
      candidateName: candidate.name,
      candidateSource: candidate.source,
      provider: candidate.provider,
      model: candidate.model,
      lyrics: cue.lyrics,
      focusKind: adaptation.focusKind,
      focusTargetId: adaptation.focusTargetId,
      sceneDescription: adaptation.sceneDescription,
      pacing: input.pacing,
      mode: 'full',
      imageModel: project.provider.imageModel,
      videoModel: project.videoOverride.model,
      resolution: project.videoOverride.resolution,
      aspectRatio: project.videoOverride.aspectRatio,
      generationMode: project.musicVideoGenerationMode,
      directVideoMasterPrompt: project.directVideoMasterPrompt,
      writingProvider: project.provider.writingProvider,
      writingModel: project.provider.writingModel,
      writingBaseUrl: project.provider.writingBaseUrl,
      provenance,
    },
    provenance,
    status: 'staged',
  }
}

export function validateMusicVideoStaging(
  project: StoryProject,
  adaptation: MusicVideoAdaptation,
): { directVideo: boolean; directReferences: boolean } {
  const directVideo = project.musicVideoGenerationMode === 'direct_video'
  const directReferences = project.musicVideoGenerationMode === 'direct_references'
  if (directReferences && !String(project.videoOverride.model || '').startsWith('minimax_h3')) {
    throw new Error('Las referencias directas de este videoclip requieren un modelo MiniMax H3 con Ref2VA.')
  }
  if (directReferences && !adaptation.characterReferences.length && !adaptation.locationReferences.length) {
    throw new Error('No hay referencias aprobadas para este cue. Aprueba una imagen de mundo, localización o personaje antes de preparar el videoclip.')
  }
  return { directVideo, directReferences }
}
