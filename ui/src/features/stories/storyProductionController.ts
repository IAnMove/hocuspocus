import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import {
  buildMusicVideoAdaptation,
  buildShortFilmAdaptation,
  buildTrailerAdaptation,
} from './adaptations'
import type { TrailerAdaptationOptions } from './adaptations'
import type { AspectRatio, ResolutionPreset } from '../../types'
import type {
  StoryMusicCandidate,
  StoryMusicCue,
  StoryProject,
} from './types'

export type StoryMusicVideoGenerationSettings = {
  imageModel: string
  videoModel: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
  generationMode: StoryProject['musicVideoGenerationMode']
  directVideoMasterPrompt: string
  writingProvider: StoryProject['provider']['writingProvider']
  writingModel: string
  writingBaseUrl: string
}

export type StoryFilmProductionOptions = {
  source: StoryProject
  direction: string
  autoStart: boolean
  targetDuration: number
  preserveVisualStyle: boolean
  videoModel: string
  imageModel: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
  trailerOptions?: TrailerAdaptationOptions
}

export type StoryMusicVideoProductionOptions = {
  source: StoryProject
  cue?: StoryMusicCue
  candidate: StoryMusicCandidate
  activeWorkspace: string
  autoStart: boolean
  pacing: 'cinematic' | 'balanced' | 'rhythmic'
  excerpt?: { start: number; end: number }
  generationSettings: StoryMusicVideoGenerationSettings
  onDirectorHandoff?: () => void
}

/** Find the cue which owns a candidate without relying on its display name. */
export function musicCueForCandidate(source: StoryProject, candidateId?: string): StoryMusicCue | undefined {
  return source.music.cues.find(item => item.candidates.some(candidate => candidate.id === candidateId))
}

/** Resolve a generated song by its durable ID, including legacy cue-local songs. */
export function musicCandidateById(source: StoryProject, candidateId?: string): StoryMusicCandidate | undefined {
  const cue = musicCueForCandidate(source, candidateId)
  return source.music.candidates.find(item => item.id === candidateId)
    || cue?.candidates.find(item => item.id === candidateId)
}

/** Build a cue around a legacy/global candidate so every Director handoff has a full context. */
export function effectiveMusicCue(
  source: StoryProject,
  cue: StoryMusicCue | undefined,
  candidate: StoryMusicCandidate,
): StoryMusicCue {
  return cue || {
    id: 'story-song',
    kind: 'story',
    targetId: source.id,
    title: candidate.title || candidate.displayName || candidate.name,
    purpose: source.music.brief || `Tell ${source.title} as a song-led visual story.`,
    referenceSong: '',
    brief: source.music.brief,
    style: candidate.prompt || source.music.style,
    lyrics: candidate.lyrics || source.music.lyrics,
    lyriaPrompt: '',
    instrumental: !(candidate.lyrics || source.music.lyrics).trim(),
    durationSeconds: candidate.durationSeconds || source.music.targetDurationSeconds,
    candidates: [candidate],
    selectedCandidateId: candidate.id,
  }
}

type StoryReference = { assetId: string; label: string }

type DirectorReferenceLoader = {
  add: (file: File) => void
  label: (value: string) => void
  missingMessage: string
}

/** Attach approved Story references while tolerating an asset removed meanwhile. */
async function hydrateStoryReferences(
  source: StoryProject,
  references: StoryReference[],
  loader: DirectorReferenceLoader,
): Promise<void> {
  for (const reference of references) {
    const asset = source.assets[reference.assetId]
    if (!asset) continue
    try {
      const blob = await fetch(asset.source).then(response => {
        if (!response.ok) throw new Error(loader.missingMessage)
        return response.blob()
      })
      loader.add(new File(
        [blob],
        asset.name || `${reference.assetId}.png`,
        { type: blob.type || 'image/png' },
      ))
      loader.label(reference.label)
    } catch {
      // The written Story bible remains usable if an older reference disappeared.
    }
  }
}

async function selectDirectorModels(
  videoModel: string,
  imageModel: string,
  useImageReferences: boolean,
  useDirectVideo: boolean,
): Promise<ReturnType<typeof useStore.getState>> {
  const store = useStore.getState()
  if (!useDirectVideo && !useImageReferences && imageModel) {
    store.selectDirectorImageModel(imageModel)
  }
  if (videoModel) {
    await store.selectDirectorVideoModel(videoModel)
    const selected = useStore.getState().selectedModelPerMode.video
    if (selected !== videoModel) {
      throw new Error(
        `Video model selection did not settle: requested ${videoModel}, effective ${selected || 'none'}.`,
      )
    }
  }
  return useStore.getState()
}

function configureStoryFilmDirector(
  source: StoryProject,
  adaptation: Awaited<ReturnType<typeof buildShortFilmAdaptation>>,
  options: StoryFilmProductionOptions,
  store: ReturnType<typeof useStore.getState>,
): void {
  const directVideo = source.musicVideoGenerationMode === 'direct_video'
  const directReferences = source.musicVideoGenerationMode === 'direct_references'
  store.setGenerationMode('video')
  store.setDirectorResolution(options.resolution)
  store.setDirectorAspectRatio(options.aspectRatio)
  store.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
  if (options.videoModel.startsWith('minimax_h3') && !directVideo) {
    store.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
  }
  store.setSidebarMode('director')
  store.directorSetSceneDescription(adaptation.sceneDescription)
  store.setDirectorSkill('short_film')
  store.setDirectorMusicVideoTreatment({
    generation_mode: directVideo ? 'direct_video' : 'image_guided',
    direct_video_master_prompt: source.directVideoMasterPrompt,
  })
  store.shortFilmSetPath('story')
  store.shortFilmSetCharacters(adaptation.characters)
  store.shortFilmSetTargetDuration(adaptation.targetDuration)
  store.shortFilmSetNarrative(adaptation.narrative)
  store.shortFilmSetVisualStyle(directVideo ? '' : adaptation.visualStyle)
  store.shortFilmSetPreserveVisualStyle(directVideo ? false : adaptation.preserveVisualStyle)
  store.setDirectorCharacterVisualStyle(directVideo ? '' : source.characterVisualStyle)
  store.setDirectorAllowClipText(source.allowClipText)
  store.setDirectorSpokenLanguage(source.spokenLanguage)
  store.setDirectorAutoMode(options.autoStart)
  useStore.setState({
    directorWritingProvider: source.provider.writingProvider,
    directorWritingModel: source.provider.writingModel,
    directorWritingBaseUrl: source.provider.writingBaseUrl,
  })
}

function configureStoryMusicVideoDirector(
  source: StoryProject,
  adaptation: ReturnType<typeof buildMusicVideoAdaptation>,
  options: StoryMusicVideoProductionOptions,
  store: ReturnType<typeof useStore.getState>,
  resolvedCue: StoryMusicCue,
): void {
  const directVideo = options.generationSettings.generationMode === 'direct_video'
  const directReferences = options.generationSettings.generationMode === 'direct_references'
  store.setGenerationMode('video')
  store.setDirectorResolution(options.generationSettings.resolution)
  store.setDirectorAspectRatio(options.generationSettings.aspectRatio)
  store.setSidebarMode('director')
  store.setDirectorSkill('music_video')
  store.setDirectorAutoMode(options.autoStart)
  store.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
  if (options.generationSettings.videoModel.startsWith('minimax_h3') && !directVideo) {
    store.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
  }
  store.setDirectorMusicVideoTreatment({
    // Director already has a model-aware direct-reference policy. Keep its
    // normal visual planner but skip generated shot images and feed the
    // approved Story references straight into H3 Ref2VA.
    generation_mode: directVideo ? 'direct_video' : 'image_guided',
    direct_video_master_prompt: options.generationSettings.directVideoMasterPrompt,
  })
  store.directorSetSceneDescription(adaptation.sceneDescription)
  store.shortFilmSetVisualStyle(directVideo ? '' : source.visualStyle)
  store.shortFilmSetPreserveVisualStyle(directVideo ? false : source.enforceVisualStyle)
  store.setDirectorCharacterVisualStyle(directVideo ? '' : source.characterVisualStyle)
  store.setDirectorAllowClipText(source.allowClipText)
  store.setDirectorSpokenLanguage(source.spokenLanguage)
  useStore.setState({
    directorMusicSource: 'upload',
    directorSongDescription: resolvedCue.brief,
    directorSongStyle: resolvedCue.style,
    directorSongLyrics: resolvedCue.lyrics,
    directorSongDuration: options.excerpt
      ? options.excerpt.end - options.excerpt.start : resolvedCue.durationSeconds,
    directorPacingProfile: options.pacing,
    directorStep: 'upload',
    directorWritingProvider: options.generationSettings.writingProvider,
    directorWritingModel: options.generationSettings.writingModel,
    directorWritingBaseUrl: options.generationSettings.writingBaseUrl,
  })
}

async function startDirectorIfRequested(autoStart: boolean): Promise<void> {
  if (!autoStart || useStore.getState().directorStep !== 'structure') return
  useStore.getState().directorConfirmStructure()
  await useStore.getState().startDirectorPipeline()
  if (!useStore.getState().pipelineId) {
    throw new Error('Director did not return a pipeline ID; video generation was not started.')
  }
}

async function adoptStorySong(
  candidate: StoryMusicCandidate,
  activeWorkspace: string,
  audioOptions: { lyricsHint?: string; trimStart?: number; trimEnd?: number },
  onDirectorHandoff?: () => void,
): Promise<void> {
  const songReference = api.getServerMediaReference(candidate.source, candidate.name, activeWorkspace)
  const adoptable = songReference && /\.(?:wav|flac|ogg)$/i.test(songReference.audio_path)
  if (songReference && adoptable) {
    onDirectorHandoff?.()
    await useStore.getState().directorAdoptAndAnalyze(songReference, candidate.name, audioOptions)
    return
  }
  const blob = await fetch(api.getPlayableFileUrl(candidate.source, candidate.name, activeWorkspace)).then(response => {
    if (!response.ok) throw new Error('The selected song file is unavailable')
    return response.blob()
  })
  onDirectorHandoff?.()
  await useStore.getState().directorUploadAndAnalyze(new File(
    [blob], candidate.name, { type: blob.type || 'audio/mpeg' },
  ), audioOptions)
}

/**
 * Stage a Story short film or trailer in Director.
 *
 * This controller owns the cross-store handoff only. UI confirmation, notices,
 * and Story production snapshots remain in StoryLabPanel, while all Director
 * mutations are kept in one testable boundary.
 */
export async function loadStoryFilmProduction(options: StoryFilmProductionOptions) {
  const { source, direction, targetDuration, preserveVisualStyle, videoModel, trailerOptions } = options
  const directVideo = source.musicVideoGenerationMode === 'direct_video'
  const directReferences = source.musicVideoGenerationMode === 'direct_references'
  if (directReferences && !videoModel.startsWith('minimax_h3')) {
    throw new Error('Direct references currently require a MiniMax H3 video model with Ref2VA support.')
  }
  const adaptation = trailerOptions
    ? buildTrailerAdaptation(source, direction, targetDuration, trailerOptions)
    : buildShortFilmAdaptation(source, direction, targetDuration, {
        preserveVisualStyle,
      })
  if (directReferences && !adaptation.characterReferences.length && !adaptation.locationReferences.length) {
    throw new Error('Direct references need at least one approved image attached to the Story world, a location or a character.')
  }
  const director = useStore.getState()
  director.directorReset()
  const store = await selectDirectorModels(
    videoModel,
    options.imageModel,
    directReferences,
    directVideo,
  )
  configureStoryFilmDirector(source, adaptation, options, store)
  await hydrateStoryReferences(source, directVideo ? [] : adaptation.characterReferences, {
    add: file => store.directorAddCharacterRef(file),
    label: value => {
      const index = useStore.getState().directorCharacterRefs.length - 1
      useStore.getState().directorSetCharacterRefLabel(index, value)
    },
    missingMessage: 'Reference unavailable',
  })
  await hydrateStoryReferences(source, directVideo ? [] : adaptation.locationReferences, {
    add: file => store.directorAddLocationRef(file),
    label: value => {
      const index = useStore.getState().directorLocationRefs.length - 1
      useStore.getState().directorSetLocationRefLabel(index, value)
    },
    missingMessage: 'Reference unavailable',
  })
  useStore.setState({ directorStep: 'style' })
  store.setMediaFilter('all')
  window.dispatchEvent(new Event('maestro:director-open'))
  await startDirectorIfRequested(options.autoStart)
  return adaptation
}

/**
 * Stage a selected Story song in Director and optionally start its video.
 * Candidate/cue IDs are supplied by the caller; this function never resolves
 * a song from a display name, which prevents stale versions crossing projects.
 */
export async function loadStoryMusicVideoProduction(options: StoryMusicVideoProductionOptions) {
  const { source, cue, candidate, generationSettings } = options
  const resolvedCue = effectiveMusicCue(source, cue, candidate)
  const directReferences = generationSettings.generationMode === 'direct_references'
  if (directReferences && !generationSettings.videoModel.startsWith('minimax_h3')) {
    throw new Error('Direct references currently require a MiniMax H3 video model with Ref2VA support.')
  }
  const adaptation = buildMusicVideoAdaptation(source, resolvedCue, {
    generationMode: generationSettings.generationMode,
  })
  if (directReferences && !adaptation.characterReferences.length && !adaptation.locationReferences.length) {
    throw new Error('No approved references match this song focus. Approve an attached world/location image or a reference for the focused character.')
  }
  const director = useStore.getState()
  director.directorReset()
  const store = await selectDirectorModels(
    generationSettings.videoModel,
    generationSettings.imageModel,
    directReferences,
    generationSettings.generationMode === 'direct_video',
  )
  configureStoryMusicVideoDirector(source, adaptation, options, store, resolvedCue)
  const directVideo = generationSettings.generationMode === 'direct_video'
  await hydrateStoryReferences(source, directVideo ? [] : adaptation.characterReferences, {
    add: file => store.directorAddCharacterRef(file),
    label: value => {
      const index = useStore.getState().directorCharacterRefs.length - 1
      useStore.getState().directorSetCharacterRefLabel(index, value)
    },
    missingMessage: 'Character reference unavailable',
  })
  await hydrateStoryReferences(source, directVideo ? [] : adaptation.locationReferences, {
    add: file => store.directorAddLocationRef(file),
    label: value => {
      const index = useStore.getState().directorLocationRefs.length - 1
      useStore.getState().directorSetLocationRefLabel(index, value)
    },
    missingMessage: 'Location reference unavailable',
  })

  window.dispatchEvent(new Event('maestro:director-open'))
  const audioOptions = {
    lyricsHint: resolvedCue.lyrics || undefined,
    trimStart: options.excerpt?.start,
    trimEnd: options.excerpt?.end,
  }
  await adoptStorySong(
    candidate,
    options.activeWorkspace,
    audioOptions,
    options.onDirectorHandoff,
  )
  await startDirectorIfRequested(options.autoStart)
  return { adaptation, resolvedCue, pipelineId: useStore.getState().pipelineId, generationSettings }
}
