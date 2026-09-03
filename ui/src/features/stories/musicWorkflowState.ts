import type { MusicVideoAdaptation } from './adaptations'
import { generatedSongProvenance, musicVideoProductionProvenance } from './provenance'
import type {
  StoryMusicCandidate,
  StoryMusicCue,
  StoryProduction,
  StoryProject,
  StoryProvenance,
} from './types'

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
  const { project, cue } = input
  return {
    id: input.candidateId,
    displayName: `${cue.title} · ${cue.lyricsLanguage || project.language} · v${input.version}`,
    title: cue.title,
    language: cue.lyricsLanguage || project.language,
    version: input.version,
    name: input.filename,
    source: input.source,
    prompt: cue.style,
    lyrics: cue.instrumental ? '' : cue.lyrics,
    provider: 'local',
    model: input.model,
    durationSeconds: cue.durationSeconds,
    createdAt: new Date().toISOString(),
    taskId: input.taskId,
    rootTaskId: input.rootTaskId,
    provenance: generatedSongProvenance({
      ...input.provenance,
      projectId: project.id,
      cueId: cue.id,
      songVersion: input.version,
    } as Parameters<typeof generatedSongProvenance>[0]),
  }
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
