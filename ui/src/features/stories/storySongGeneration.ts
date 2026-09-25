import { compileProviderPrompt } from '../../lib/languageIntent'
import * as api from '../../api/client'
import type { MiniMaxMusicJob } from '../../api/stories'
import { clampStoryMusicDuration, isLocalMusicModel } from './musicModel'
import {
  buildPendingSongCandidate,
  patchSongCandidateFailed,
  patchSongCandidateReady,
  overlaySavedCueCandidates,
  upsertCueMusicCandidate,
} from './musicWorkflowState'
import { pendingSongProvenance } from './provenance'
import { songProviderLanguageIntent } from './songLanguage'
import { compiledMusicCuePrompt, musicCueBlock, musicPromptLimit, nextMusicCandidateVersion } from './storyLabMusic'
import {
  patchSongCandidateJob,
  reusableInFlightSongCandidate,
  songJobIdentityChanged,
} from './storySongJobPhases'
import {
  commitStoryProjectMutation,
  normalizeStoryProject,
  noteStoryLibraryPersisted,
  storyId,
  useStoryStore,
} from './store'
import type { StoryMusicCandidate, StoryMusicCue, StoryProject } from './types'

export interface GenerateStoryCueSongInput {
  workspace: string
  projectId: string
  cueId: string
  actor: 'user' | 'wizard'
  capability?: string
  onJobSubmitted?: (job: MiniMaxMusicJob) => void | Promise<void>
  onProgress?: (job: MiniMaxMusicJob) => void | Promise<void>
}

export interface GenerateStoryCueSongResult {
  project: StoryProject
  cueId: string
  candidate: StoryMusicCandidate
  candidateId: string
  version: number
  filename?: string
  taskId?: string
  rootTaskId?: string
  jobId?: string
}

const inflightCueSongs = new Map<string, Promise<GenerateStoryCueSongResult>>()

type ReadySongPatch = {
  filename: string
  source: string
  durationSeconds?: number
  taskId?: string
  rootTaskId?: string
  jobId?: string
}

export function storySongIdempotencyKey(
  workspace: string,
  projectId: string,
  cueId: string,
  candidateId: string,
): string {
  return `story-song:${workspace}:${projectId}:${cueId}:${candidateId}`
}

function songGenerationProvenance(
  input: GenerateStoryCueSongInput,
  candidateId: string,
  version: number,
) {
  return {
    actor: input.actor,
    capability: input.capability || 'generate_story_song',
    project_id: input.projectId,
    cue_id: input.cueId,
    candidate_id: candidateId,
    song_version: String(version),
  }
}

function cueCandidate(project: StoryProject, cueId: string, candidateId: string): StoryMusicCandidate | undefined {
  return project.music.cues.find(item => item.id === cueId)
    ?.candidates.find(item => item.id === candidateId)
}

function requireSavedCandidate(
  project: StoryProject,
  cueId: string,
  candidateId: string,
  version: number,
  filename?: string,
  jobId?: string,
): GenerateStoryCueSongResult {
  const candidate = cueCandidate(project, cueId, candidateId)
  if (!candidate) throw new Error('Story Lab guardó la canción sin devolver el candidato generado.')
  return {
    project,
    cueId,
    candidate,
    candidateId,
    version: candidate.version || version,
    filename,
    taskId: candidate.taskId,
    rootTaskId: candidate.rootTaskId,
    jobId: candidate.provenance?.jobId || jobId,
  }
}

async function persistCueCandidate(
  workspace: string,
  projectId: string,
  cueId: string,
  candidateId: string,
  patch: (source: StoryProject) => StoryMusicCandidate,
): Promise<StoryProject> {
  const before = useStoryStore.getState()
  const library = await commitStoryProjectMutation(
    workspace,
    before,
    projectId,
    source => {
      const latestCue = source.music.cues.find(item => item.id === cueId)
      if (!latestCue) throw new Error('El cue desapareció mientras se generaba el audio.')
      const existing = latestCue.candidates.find(item => item.id === candidateId)
      const candidate = patch(source)
      const next = upsertCueMusicCandidate(
        source,
        cueId,
        existing ? { ...existing, ...candidate, id: candidateId } : candidate,
      )
      return normalizeStoryProject(next)
    },
  )
  const saved = library.projects[projectId]
  const latest = useStoryStore.getState()
  if (latest.workspace !== workspace) return saved
  // A 409 rebase PUTs remote-only siblings — extra stories, extra cues, and
  // extra song rows on this story. Overlaying only this persist's candidate
  // onto a stale snapshot leaves the next persist (ready/job) to rewrite the
  // library without those rows.
  let merged = saved
  useStoryStore.setState(current => {
    if (current.workspace !== workspace) return {}
    const remoteOnly = Object.fromEntries(
      Object.entries(library.projects).filter(([id]) => !current.projects[id]),
    )
    const live = current.projects[projectId] || before.projects[projectId] || saved
    merged = overlaySavedCueCandidates(live, saved)
    const visibleId = current.project.id
    const visible = visibleId === projectId
      ? overlaySavedCueCandidates(current.project, saved)
      : current.project
    return {
      project: visible,
      projects: {
        ...current.projects,
        ...remoteOnly,
        [projectId]: merged,
        [visibleId]: visible,
      },
      libraryRevision: library.revision,
      dirty: current.dirty,
      hydrated: true,
      loading: false,
      saveError: null,
      libraryConflicts: current.libraryConflicts,
    }
  })
  noteStoryLibraryPersisted({ onlyIfClean: true })
  return merged
}

function requireOpenCue(project: StoryProject | undefined, cueId: string): { project: StoryProject; cue: StoryMusicCue } {
  if (!project) throw new Error('La historia activa desapareció antes de generar la canción.')
  const cue = project.music.cues.find(item => item.id === cueId)
  if (!cue) throw new Error(`No existe el cue con ID “${cueId}” en “${project.title}”.`)
  if (!cue.style.trim()) throw new Error(`“${cue.title}” necesita un estilo musical antes de generarse.`)
  if (!cue.instrumental && !cue.lyrics.trim()) {
    throw new Error(`“${cue.title}” necesita letra antes de generarse.`)
  }
  const blocked = musicCueBlock(cue, project.music.model)
  if (blocked?.key === 'music.promptOverLimit') {
    throw new Error(
      `“${cue.title}” supera el límite de ${musicPromptLimit(project.music.model)} caracteres del modelo seleccionado.`,
    )
  }
  if (blocked?.key === 'notice.needsSectionTags') {
    throw new Error(`“${cue.title}” necesita etiquetas de sección compatibles con MiniMax antes de generarse.`)
  }
  return { project, cue }
}

function mintPendingCandidate(
  input: GenerateStoryCueSongInput,
  project: StoryProject,
  cue: StoryMusicCue,
): { pending: StoryMusicCandidate; candidateId: string; version: number } {
  const candidateId = storyId('song')
  const version = nextMusicCandidateVersion(
    cue.candidates,
    cue.lyricsLanguage || project.language,
    project.language,
  )
  const pending = buildPendingSongCandidate({
    project,
    cue,
    candidateId,
    version,
    model: project.music.model,
    provider: isLocalMusicModel(project.music.model) ? 'local' : 'minimax',
    provenance: pendingSongProvenance({
      outputFolder: input.workspace,
      projectId: project.id,
      cueId: cue.id,
      candidateId,
      startedAt: new Date().toISOString(),
      songVersion: version,
      actor: input.actor,
    }),
  })
  return { pending, candidateId, version }
}

async function persistReadyCandidate(
  input: GenerateStoryCueSongInput,
  pending: StoryMusicCandidate,
  patch: ReadySongPatch,
): Promise<StoryProject> {
  return persistCueCandidate(
    input.workspace,
    input.projectId,
    input.cueId,
    pending.id,
    source => patchSongCandidateReady(cueCandidate(source, input.cueId, pending.id) || pending, patch),
  )
}

async function generateLocalStorySong(
  input: GenerateStoryCueSongInput,
  project: StoryProject,
  cue: StoryMusicCue,
  pending: StoryMusicCandidate,
  version: number,
): Promise<GenerateStoryCueSongResult> {
  const rendered = await api.generateMusic({
    style: compileProviderPrompt(
      cue.style.trim(),
      songProviderLanguageIntent(
        project.languageIntent,
        cue.lyricsLanguage || project.languageIntent.spokenLanguage || project.spokenLanguage,
      ),
      { medium: 'music' },
    ),
    lyrics: cue.instrumental ? '[Instrumental]' : cue.lyrics,
    instrumental: cue.instrumental,
    duration_seconds: clampStoryMusicDuration(cue.durationSeconds, project.music.model),
    model_type: project.music.model,
    workspace: input.workspace,
    initiator: `Story Lab · ${project.projectType === 'music_video' ? 'Videoclip' : 'Story song'}`,
    provenance: songGenerationProvenance(input, pending.id, version),
  })
  if (!rendered.filename || !rendered.audio_path) {
    throw new Error('El modelo local terminó sin devolver un archivo de audio verificable.')
  }
  const saved = await persistReadyCandidate(input, pending, {
    filename: rendered.filename,
    source: api.getFileUrl(rendered.filename, input.workspace),
    durationSeconds: clampStoryMusicDuration(cue.durationSeconds, project.music.model),
    taskId: rendered.task_id,
    rootTaskId: rendered.root_task_id || rendered.task_id,
    jobId: rendered.job_id,
  })
  return requireSavedCandidate(saved, input.cueId, pending.id, version, rendered.filename)
}

async function persistJobOnCandidate(
  input: GenerateStoryCueSongInput,
  pending: StoryMusicCandidate,
  job: MiniMaxMusicJob,
): Promise<void> {
  const live = cueCandidate(
    useStoryStore.getState().projects[input.projectId],
    input.cueId,
    pending.id,
  ) || pending
  if (!songJobIdentityChanged(live, patchSongCandidateJob(live, job))) return
  try {
    await persistCueCandidate(
      input.workspace,
      input.projectId,
      input.cueId,
      pending.id,
      source => patchSongCandidateJob(cueCandidate(source, input.cueId, pending.id) || pending, job),
    )
  } catch {
    // The provider already accepted the job; keep polling and retry persist later.
  }
}

function remoteSongWatchers(
  input: GenerateStoryCueSongInput,
  pending: StoryMusicCandidate,
) {
  return {
    onJobSubmitted: async (job: MiniMaxMusicJob) => {
      await persistJobOnCandidate(input, pending, job)
      await input.onJobSubmitted?.(job)
    },
    onProgress: async (job: MiniMaxMusicJob) => {
      await persistJobOnCandidate(input, pending, job)
      await input.onProgress?.(job)
    },
  }
}

async function generateRemoteStorySong(
  input: GenerateStoryCueSongInput,
  cue: StoryMusicCue,
  pending: StoryMusicCandidate,
  version: number,
  model: StoryProject['music']['model'],
): Promise<GenerateStoryCueSongResult> {
  const watchers = remoteSongWatchers(input, pending)
  const existingJobId = pending.provenance?.jobId?.trim()
  const result = existingJobId
    ? await api.watchStoryMusicCandidatesJob(existingJobId, watchers)
    : await api.generateStoryMusicCandidates({
      prompt: compiledMusicCuePrompt(cue, model),
      lyrics: cue.instrumental ? '' : cue.lyrics,
      instrumental: cue.instrumental,
      count: 1,
      model,
      workspace: input.workspace,
      idempotency_key: storySongIdempotencyKey(
        input.workspace,
        input.projectId,
        input.cueId,
        pending.id,
      ),
      provenance: songGenerationProvenance(input, pending.id, version),
    }, watchers)
  const rendered = result.candidates[0]
  if (!rendered?.filename || !rendered.source) {
    throw new Error(result.message || 'MiniMax Music terminó sin devolver un archivo de audio verificable.')
  }
  const saved = await persistReadyCandidate(input, pending, {
    filename: rendered.filename,
    source: rendered.source,
    durationSeconds: rendered.duration_seconds,
    taskId: rendered.taskId || rendered.task_id || result.taskId,
    rootTaskId: rendered.rootTaskId || rendered.root_task_id || result.taskId,
    jobId: result.jobId,
  })
  return requireSavedCandidate(saved, input.cueId, pending.id, version, rendered.filename, result.jobId)
}

async function markSongFailed(input: GenerateStoryCueSongInput, pending: StoryMusicCandidate): Promise<void> {
  try {
    await persistCueCandidate(
      input.workspace,
      input.projectId,
      input.cueId,
      pending.id,
      source => patchSongCandidateFailed(cueCandidate(source, input.cueId, pending.id) || pending),
    )
  } catch {
    // Keep the original generate failure; the pending row still has the minted id.
  }
}

function resolvePendingCandidate(
  input: GenerateStoryCueSongInput,
  project: StoryProject,
  cue: StoryMusicCue,
): { pending: StoryMusicCandidate; candidateId: string; version: number; reused: boolean } {
  const reused = reusableInFlightSongCandidate(cue.candidates)
  if (!reused) return { ...mintPendingCandidate(input, project, cue), reused: false }
  return {
    pending: reused,
    candidateId: reused.id,
    version: reused.version || nextMusicCandidateVersion(
      cue.candidates,
      cue.lyricsLanguage || project.language,
      project.language,
    ),
    reused: true,
  }
}

function cueSongKey(input: GenerateStoryCueSongInput): string {
  return `${input.workspace}:${input.projectId}:${input.cueId}`
}

async function generateStoryCueSongOnce(
  input: GenerateStoryCueSongInput,
): Promise<GenerateStoryCueSongResult> {
  const { project, cue } = requireOpenCue(useStoryStore.getState().projects[input.projectId], input.cueId)
  const minted = resolvePendingCandidate(input, project, cue)
  if (!minted.reused) {
    await persistCueCandidate(input.workspace, input.projectId, input.cueId, minted.candidateId, () => minted.pending)
  }
  try {
    if (isLocalMusicModel(project.music.model)) {
      return await generateLocalStorySong(input, project, cue, minted.pending, minted.version)
    }
    return await generateRemoteStorySong(input, cue, minted.pending, minted.version, project.music.model)
  } catch (error) {
    await markSongFailed(input, minted.pending)
    throw error
  }
}

export async function generateStoryCueSong(
  input: GenerateStoryCueSongInput,
): Promise<GenerateStoryCueSongResult> {
  const key = cueSongKey(input)
  const existing = inflightCueSongs.get(key)
  if (existing) return existing
  const run = generateStoryCueSongOnce(input).finally(() => {
    if (inflightCueSongs.get(key) === run) inflightCueSongs.delete(key)
  })
  inflightCueSongs.set(key, run)
  return run
}
