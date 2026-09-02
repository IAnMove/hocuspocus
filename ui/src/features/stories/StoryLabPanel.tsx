import { useEffect, useMemo, useRef, useState } from 'react'
import JSZip from 'jszip'
import {
  BookOpen, Boxes, Check, ChevronRight, Download, Film, ImagePlus, Loader2,
  Music, Network, Play, Plus, Sparkles, Trash2, Upload, Users,
} from 'lucide-react'
import * as api from '../../api/client'
import { getModelMode, resolveResolution, useStore } from '../../stores/useStore'

import { generateImageAsset } from '../../lib/imageGeneration'
import { MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { resolveSupportedVideoFormat } from '../../lib/productionProfile'
import { StoryProductionTimeline } from './StoryProductionTimeline'
import { StoryLabNavigation } from './StoryLabNavigation'
import { StoryRelationshipsTab } from './StoryRelationshipsTab'
import { StoryWorldTab } from './StoryWorldTab'
import { StoryCharactersTab } from './StoryCharactersTab'
import { StoryStructureTab } from './StoryStructureTab'
import { StoryMusicTab } from './StoryMusicTab'
import { StoryTrailerTab } from './StoryTrailerTab'
import { StoryProductionsTab } from './StoryProductionsTab'
import { CompactVideoWorkspace } from './CompactVideoWorkspace'
import { StoryOverviewTab } from './StoryOverviewTab'
import { StoryAssetsTab } from './StoryAssetsTab'
import type { PendingSmartAsset } from './storyLabAssets'
import { StoryLabVisualsProvider } from './StoryLabVisualsProvider'
import { emptyCharacter, pruneUnusedAssets } from './storyLabEditors'
import {
  button, input, panel, requiredPreparationButton,
  type ProductionReviewIssue, type StoryGenerationOptions, type StoryLabTab as StoryTab,
} from './storyLabChrome'
import {
  STORY_VIDEO_ASPECTS, savedStoryVideoAspect, savedStoryVideoResolution,
} from './storyLabVideoFormat'
import {
  MINIMAX_LYRIC_SECTION, musicCandidateDisplayName, nextMusicCandidateVersion, storyProjectPremise, storySongBrief,
} from './storyLabMusic'
import { readDirectorClipReplacementResult } from './directorClipHandoff'
import { createStoryActivityLifecycle } from './activityLifecycle'
import { useComicStore } from '../comics/store'
import type { ComicProject } from '../comics/types'
import { syncTrailerDuration, trailerDurationForProject } from './trailerDefaults'
import { resolveStoryWritingProvider } from './provider'
import { StoryLibraryConflictNotice } from './StoryLibraryConflictNotice'
import {
  buildComicAdaptation,
  buildMusicVideoAdaptation,
  buildShortFilmAdaptation,
  buildTrailerAdaptation,
  DEFAULT_COMIC_CHAPTER_DIRECTION,
  DEFAULT_SHORT_FILM_DIRECTION,
  DEFAULT_TRAILER_DIRECTION,
} from './adaptations'
import type { TrailerAdaptationOptions } from './adaptations'
import { normalizeStoryProject, storyId, useStoryStore } from './store'
import { musicVideoShouldUseDirectVideo } from './musicVideoLook'
import {
  analyzeStoryPromptHealth,
  applyStoryVisualStyle,
  normalizeStoryCharacter,
  storyNegativePromptForStyle,
  storyRenderStyle,
} from './model'
import type {
  StoryBeat, StoryGenerationScope, StoryLocation, StoryProject,
  StoryImageProvider, StoryMusicCandidate, StoryMusicCue, StoryProjectType, StoryRelationship, StoryVisualAsset,
  StoryTrailerFormat, StoryTrailerIntensity, StoryTrailerNarration, StoryTrailerSpoiler, StoryWritingProvider,
} from './types'
import type { AspectRatio, ModelOptions, ResolutionPreset } from '../../types'
import { ACE_STEP_MUSIC_MODEL, isAceStepMusicModel, songWriteTarget } from './musicModel'
import { listenForAgentStoryDraft, listenForAgentStorySection, listenForAgentStoryVisualGeneration } from '../../lib/uiBus'

const storyLookupName = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9]+/g, ' ').trim().toLowerCase()
const CHARACTER_IDENTITY_REFERENCE_LOCK = [
  'CHARACTER IDENTITY REFERENCE: show exactly one character in a clear medium close-up or chest-up portrait.',
  'The face must be large in frame, sharply readable, unobstructed and well lit, with both eyes and defining facial features clearly visible.',
  'Use a frontal or gentle three-quarter view, a neutral readable pose, the canonical wardrobe, and a simple non-distracting background.',
  'Do not use a distant shot, full-body environmental composition, extreme profile, covered face, dramatic occlusion, action pose or additional characters.',
].join(' ')



function stableTextKey(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

const STYLE_CONVERSION_ASPECTS = [
  '1:1', '16:9', '4:3', '3:2', '2:3', '3:4', '9:16', '21:9',
] as const
const QWEN_STYLE_EDIT_MODEL = 'qwen_image_edit_20B_gguf_q4_k_m'
const FLUX_STYLE_EDIT_MODEL = 'flux2_klein_9b'
const STYLE_RESOLUTION_BY_ASPECT: Record<(typeof STYLE_CONVERSION_ASPECTS)[number], string> = {
  '1:1': '1024x1024',
  '16:9': '1280x720',
  '4:3': '1152x864',
  '3:2': '1248x832',
  '2:3': '832x1248',
  '3:4': '864x1152',
  '9:16': '720x1280',
  '21:9': '1344x576',
}

async function sourceAspectRatio(source: string): Promise<(typeof STYLE_CONVERSION_ASPECTS)[number]> {
  const dimensions = await new Promise<{ width: number; height: number }>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => reject(new Error('The source image could not be inspected'))
    image.src = source
  }).catch(() => ({ width: 1, height: 1 }))
  const target = dimensions.width / Math.max(1, dimensions.height)
  return STYLE_CONVERSION_ASPECTS.reduce((best, candidate) => {
    const [width, height] = candidate.split(':').map(Number)
    const [bestWidth, bestHeight] = best.split(':').map(Number)
    return Math.abs(Math.log(target / (width / height)))
      < Math.abs(Math.log(target / (bestWidth / bestHeight)))
      ? candidate : best
  }, '1:1' as (typeof STYLE_CONVERSION_ASPECTS)[number])
}

function styleConversionPrompt(
  asset: StoryVisualAsset,
  style: string,
  engine: 'minimax' | 'qwen' | 'flux',
): string {
  const normalizedStyle = style.trim()
    .replace(/^\s*(?:>|•|\*|-|\d+[.)])\s+/gm, '')
    .replace(/\s+/g, ' ')
  const requestsVisibleText = /\b(text|wording|lettering|caption|sign|logo|title|write|rewrite|reads?|says?|texto|palabras?|letras?|cartel|r[oó]tulo|t[ií]tulo|escrib\w*)\b/i.test(normalizedStyle)
  if (engine === 'flux') {
    const directInstruction = /^(apply|change|convert|replace|remove|add|transform)\b/i.test(normalizedStyle)
      ? normalizedStyle.replace(/[.\s]+$/, '')
      : `Apply ${normalizedStyle.replace(/[.\s]+$/, '')} to the entire input image`
    const fluxPreservation = asset.assetKind === 'character'
      ? 'Keep the same person, face, expression, facial hair, body proportions, hairstyle, clothing, accessories, pose, crop, and background unchanged.'
      : asset.assetKind === 'location'
        ? 'Keep the exact place, landmark architecture, street layout, camera position, perspective, crop, spatial relationships, people, vehicles, signs, and object placement unchanged.'
        : 'Keep the original subject, composition, camera position, perspective, crop, silhouettes, proportions, background, and object placement unchanged.'
    return [
      `${directInstruction}.`,
      fluxPreservation,
      requestsVisibleText
        ? 'Render only the visible wording explicitly requested, keeping all other visible text unchanged.'
        : 'Keep all existing visible text unchanged.',
    ].join(' ')
  }
  const preservation = asset.assetKind === 'character'
    ? 'Preserve the exact same person, face, facial hair, body proportions, hairstyle, clothing, accessories and pose.'
    : asset.assetKind === 'location'
      ? 'Preserve the exact place, landmark architecture, street layout, camera viewpoint, spatial relationships and recognizable local details.'
      : 'Preserve the original subject, composition, camera viewpoint, silhouettes, proportions and recognizable details.'
  const sourceIdentity = engine === 'minimax' && asset.description?.trim()
    ? `The input depicts ${asset.description.trim().replace(/[.\s]+$/, '')}.` : ''
  return [
    engine === 'qwen'
      ? `Edit this exact input image. Apply only this visual style: ${normalizedStyle}.`
      : `Generate a new portrait of the supplied character in this visual style: ${normalizedStyle}.`,
    preservation,
    sourceIdentity,
    engine === 'qwen'
      ? 'Keep the same crop, framing, perspective, geometry, spatial layout and object positions. Change only rendering medium, surface treatment, palette and lighting. Do not add, remove, move or redesign content.'
      : 'Keep the character identity and recognizable wardrobe. Do not introduce additional people.',
    requestsVisibleText
      ? 'Produce one finished image. Render only the visible wording explicitly requested; do not add any other text, labels, grids, borders or contact sheets.'
      : 'Produce one finished image. No text, labels, grids, borders or contact sheets.',
  ].filter(Boolean).join(' ')
}

type StyledReferenceTarget = {
  target: { kind: 'world' | 'character' | 'location'; id?: string }
  label: string
  prompt: string
}
type PendingDraft = {
  scope: StoryGenerationScope
  result: Record<string, unknown>
  selected: string[]
  replaceCollections: boolean
  generateImagesAfterApply: boolean
}
type MusicVideoGenerationSettings = {
  imageModel: string
  videoModel: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
  generationMode: StoryProject['musicVideoGenerationMode']
  directVideoMasterPrompt: string
  writingProvider: StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
}

const storyJobKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-job:${workspace}:${projectId}`
const storyResultKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-result:${workspace}:${projectId}`

const STORY_PROJECT_TYPES: Array<{ id: StoryProjectType; label: string; description: string }> = [
  { id: 'full_story', label: 'Historia completa', description: 'Mundo, personajes, estructura, música y adaptaciones.' },
  { id: 'music_video', label: 'Videoclip', description: 'Canción original y una historia visual construida alrededor de ella.' },
  { id: 'trailer', label: 'Tráiler cinematográfico', description: 'Tráiler de película con tensión, montaje y gancho final; no requiere canción.' },
  { id: 'quick_video', label: 'Vídeo rápido', description: 'Diálogo, meme, parodia, sketch, viral o anuncio breve.' },
]

function storyStyledReferenceTargets(
  project: StoryProject,
  options: { includeLocations: boolean; existingOnly: boolean },
): StyledReferenceTarget[] {
  const targets: StyledReferenceTarget[] = []
  const hasExistingReference = (ids: string[]) => ids.some(id => Boolean(project.assets[id]))
  const canInclude = (prompt: string, ids: string[]) => Boolean(prompt.trim())
    && (!options.existingOnly || hasExistingReference(ids))
  if (canInclude(project.world.visualPrompt, project.world.referenceAssetIds)) {
    targets.push({ target: { kind: 'world' }, label: 'world', prompt: project.world.visualPrompt })
  }
  project.characters.forEach(character => {
    if (!canInclude(character.visualPrompt, character.referenceAssetIds)) return
    targets.push({
      target: { kind: 'character', id: character.id },
      label: character.name,
      prompt: character.visualPrompt,
    })
  })
  if (options.includeLocations) {
    project.world.locations.forEach(location => {
      if (!canInclude(location.visualPrompt, location.referenceAssetIds)) return
      targets.push({
        target: { kind: 'location', id: location.id },
        label: location.name,
        prompt: location.visualPrompt,
      })
    })
  }
  return targets
}

function draftPaths(result: Record<string, unknown>): string[] {
  const paths: string[] = []
  if (result.overview && typeof result.overview === 'object') {
    Object.entries(result.overview as Record<string, unknown>).forEach(([key, value]) => {
      if (key === 'creativeBrief' && value && typeof value === 'object') {
        Object.keys(value).forEach(field => paths.push(`overview.creativeBrief.${field}`))
      } else {
        paths.push(`overview.${key}`)
      }
    })
  }
  if (result.world && typeof result.world === 'object') {
    Object.keys(result.world).forEach(key => paths.push(`world.${key}`))
  }
  if (Array.isArray(result.characters)) {
    result.characters.forEach((item, index) => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>
        const id = String(record.id || index)
        Object.keys(record)
          .filter(key => !['id', 'referenceAssetIds', 'primaryReferenceAssetId', 'approval'].includes(key))
          .forEach(key => paths.push(`characters.${id}.${key}`))
      }
    })
  }
  if (Array.isArray(result.relationships)) {
    result.relationships.forEach((item, index) => {
      if (item && typeof item === 'object') {
        const record = item as Record<string, unknown>
        const id = String(record.id || index)
        Object.keys(record).filter(key => key !== 'id')
          .forEach(key => paths.push(`relationships.${id}.${key}`))
      }
    })
  }
  const structure = Array.isArray(result.structure) ? result.structure
    : Array.isArray(result.beats) ? result.beats : []
  structure.forEach((item, index) => {
    if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      const id = String(record.id || index)
      Object.keys(record).filter(key => key !== 'id')
        .forEach(key => paths.push(`structure.${id}.${key}`))
    }
  })
  const music = result.music && typeof result.music === 'object'
    ? result.music as Record<string, unknown> : null
  if (music && Array.isArray(music.cues)) {
    music.cues.forEach((item, index) => {
      if (!item || typeof item !== 'object') return
      const record = item as Record<string, unknown>
      paths.push(`music.${String(record.id || index)}`)
    })
  }
  return paths
}

export function StoryLabPanel() {
  const project = useStoryStore(state => state.project)
  const productionProfile = useStore(state => state.productionProfile)
  const projects = useStoryStore(state => state.projects)
  const dirty = useStoryStore(state => state.dirty)
  const storyHydrated = useStoryStore(state => state.hydrated)
  const storyLoading = useStoryStore(state => state.loading)
  const storySaveError = useStoryStore(state => state.saveError)
  const storyLibraryConflicts = useStoryStore(state => state.libraryConflicts)
  const resolveStoryLibraryConflict = useStoryStore(state => state.resolveLibraryConflict)
  const loadWorkspace = useStoryStore(state => state.loadWorkspace)
  const openProject = useStoryStore(state => state.openProject)
  const duplicateProject = useStoryStore(state => state.duplicateProject)
  const deleteProject = useStoryStore(state => state.deleteProject)
  const patch = useStoryStore(state => state.patchProject)
  const update = useStoryStore(state => state.updateProject)
  const updateProjectById = useStoryStore(state => state.updateProjectById)
  const beginProjectOperation = useStoryStore(state => state.beginProjectOperation)
  const endProjectOperation = useStoryStore(state => state.endProjectOperation)
  const activeProjectOperations = useStoryStore(state => state.activeProjectOperations)
  const setProject = useStoryStore(state => state.setProject)
  const newProject = useStoryStore(state => state.newProject)
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const videoModels = useStore(state => state.models)
  const modelsLoaded = useStore(state => state.modelsLoaded)
  const enabledModels = useStore(state => state.enabledModels)
  const servicesConfig = useStore(state => state.servicesConfig)
  const filmImageModel = useStore(state => state.selectedModelPerMode.image) || 'flux2_klein_9b'
  const studioVideoModel = useStore(state => state.selectedModelPerMode.video)
  const studioVideoResolution = useStore(state => state.directorResolution)
  const studioVideoAspectRatio = useStore(state => state.directorAspectRatio)
  const selectDirectorImageModel = useStore(state => state.selectDirectorImageModel)
  const legacyVideoOverridePending = !project.videoOverride.model.trim()
  const requestedStoryVideoModel = project.provider.useGlobalProfile
    ? productionProfile.video.model
    : project.videoOverride.model.trim()
      || studioVideoModel
      || productionProfile.video.model
      || 'minimax_h3_legacy'
  const requestedStoryVideoResolution = savedStoryVideoResolution(
    project.provider.useGlobalProfile
      ? productionProfile.video.settings.resolution
      : legacyVideoOverridePending
        ? studioVideoResolution
        : project.videoOverride.resolution,
    '540p',
  )
  const requestedStoryVideoAspectRatio = savedStoryVideoAspect(
    project.provider.useGlobalProfile
      ? productionProfile.video.settings.aspectRatio
      : legacyVideoOverridePending
        ? studioVideoAspectRatio
        : project.videoOverride.aspectRatio,
    '16:9',
  )
  const [storyVideoOptionsState, setStoryVideoOptionsState] = useState<{
    model: string
    options: ModelOptions | null
    settled: boolean
  }>({ model: '', options: null, settled: false })
  const storyVideoOptions = storyVideoOptionsState.model === requestedStoryVideoModel
    ? storyVideoOptionsState.options : null
  const storyVideoFormat = resolveSupportedVideoFormat(
    storyVideoOptions,
    requestedStoryVideoResolution,
    requestedStoryVideoAspectRatio,
  )
  const filmVideoModel = requestedStoryVideoModel
  const storyVideoResolution = storyVideoFormat.resolution
  const storyVideoAspectRatio = storyVideoFormat.aspectRatio
  const storyVideoOptionsReady = storyVideoOptionsState.model === filmVideoModel
    && storyVideoOptionsState.settled
  const storyVideoConfigurationReady = storyVideoOptionsReady
    && (project.provider.useGlobalProfile || !legacyVideoOverridePending)
  const [tab, setTab] = useState<StoryTab>(() => (
    readDirectorClipReplacementResult() ? 'assembly' : 'overview'
  ))
  useEffect(() => listenForAgentStorySection(setTab), [])
  const [busy, setBusy] = useState<StoryGenerationScope | null>(null)
  const [agentDraftRevision, setAgentDraftRevision] = useState(0)
  useEffect(() => listenForAgentStoryDraft(projectId => {
    if (projectId === useStoryStore.getState().project.id) {
      setAgentDraftRevision(revision => revision + 1)
    }
  }), [])
  const [imageBusy, setImageBusy] = useState('')
  const [referenceBatchBusy, setReferenceBatchBusy] = useState(false)
  const [productionBusy, setProductionBusy] = useState<'film' | 'music' | 'trailer' | null>(null)
  const [musicCueBusy, setMusicCueBusy] = useState('')
  const [newSongAction, setNewSongAction] = useState<'prompts' | 'audio' | null>(null)
  const [musicQueue, setMusicQueue] = useState<{ ids: string[]; index: number; cancelling?: boolean } | null>(null)
  const [lyricsTranslationLanguage, setLyricsTranslationLanguage] = useState<Record<string, string>>({})
  const [musicVersionStyle, setMusicVersionStyle] = useState<Record<string, string>>({})
  const [musicVersionLanguage, setMusicVersionLanguage] = useState<Record<string, string>>({})
  const [instruction, setInstruction] = useState('')
  const [comicDirection, setComicDirection] = useState(DEFAULT_COMIC_CHAPTER_DIRECTION)
  const [comicPageCount, setComicPageCount] = useState(4)
  const [comicPanelsPerPage, setComicPanelsPerPage] = useState(4)
  const [filmDirection, setFilmDirection] = useState(DEFAULT_SHORT_FILM_DIRECTION)
  const [filmDuration, setFilmDuration] = useState(45)
  const [filmPreserveVisualStyle, setFilmPreserveVisualStyle] = useState(true)
  const [trailerDirection, setTrailerDirection] = useState(DEFAULT_TRAILER_DIRECTION)
  const [trailerDuration, setTrailerDuration] = useState(60)
  const [trailerFormat, setTrailerFormat] = useState<StoryTrailerFormat>('theatrical')
  const [trailerNarration, setTrailerNarration] = useState<StoryTrailerNarration>('hybrid')
  const [trailerSpoiler, setTrailerSpoiler] = useState<StoryTrailerSpoiler>('balanced')
  const [trailerIntensity, setTrailerIntensity] = useState<StoryTrailerIntensity>('rising')
  const [trailerTagline, setTrailerTagline] = useState('')
  const [trailerTitleCards, setTrailerTitleCards] = useState(false)
  const [trailerPreserveVisualStyle, setTrailerPreserveVisualStyle] = useState(true)
  const [trailerTouched, setTrailerTouched] = useState(false)
  const markTrailerTouched = () => setTrailerTouched(true)
  const [musicProductionCandidateId, setMusicProductionCandidateId] = useState(
    project.music.selectedCandidateId
      || project.music.cues.find(cue => cue.selectedCandidateId)?.selectedCandidateId
      || '',
  )
  const [musicProductionPacing, setMusicProductionPacing] = useState<'cinematic' | 'balanced' | 'rhythmic'>('balanced')
  const [musicProductionMode, setMusicProductionMode] = useState<'full' | 'trailer'>('full')
  const [musicTrailerRange, setMusicTrailerRange] = useState({ start: 0, end: 0, duration: 0 })
  const [jobProgress, setJobProgress] = useState('')
  const [recoveryJobId, setRecoveryJobId] = useState(() =>
    window.localStorage.getItem(storyJobKey(activeWorkspace, project.id)) || '')
  const [pendingDraft, setPendingDraft] = useState<PendingDraft | null>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(storyResultKey(activeWorkspace, project.id)) || 'null')
      if (!saved?.result) return null
      return {
        scope: saved.scope || 'all',
        result: saved.result,
        selected: draftPaths(saved.result),
        replaceCollections: true,
        generateImagesAfterApply: saved.generateImagesAfterApply === true,
      }
    } catch {
      return null
    }
  })
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [smartAssetBusy, setSmartAssetBusy] = useState(false)
  const [smartAssetDescription, setSmartAssetDescription] = useState('')
  const [pendingSmartAssets, setPendingSmartAssets] = useState<PendingSmartAsset[]>([])
  const [styleConversion, setStyleConversion] = useState('')
  const [styleAssetIds, setStyleAssetIds] = useState<string[]>([])
  const [styleConversionBusy, setStyleConversionBusy] = useState(false)
  const [styleConversionModel, setStyleConversionModel] = useState(QWEN_STYLE_EDIT_MODEL)
  const [styleModelDownloading, setStyleModelDownloading] = useState('')
  const [styleModelDownloadError, setStyleModelDownloadError] = useState('')
  const importRef = useRef<HTMLInputElement>(null)
  const smartAssetRef = useRef<HTMLInputElement>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const musicCoverRef = useRef<HTMLInputElement>(null)
  const lyriaUploadRef = useRef<HTMLInputElement>(null)
  const lyriaUploadCueId = useRef('')
  const customMusicUploadRef = useRef<HTMLInputElement>(null)
  const customMusicUploadCueId = useRef('')
  const musicQueueCancelRequested = useRef(false)
  const activeMusicJobId = useRef('')
  const styleConversionCancelRequested = useRef(false)
  const generationAbortRef = useRef<AbortController | null>(null)
  const [uploadTarget, setUploadTarget] = useState<{ kind: 'world' | 'character' | 'location'; id?: string } | null>(null)
  const projectOperationBusy = Boolean(activeProjectOperations[project.id])
  const musicCandidateOptions = useMemo(() => {
    const seen = new Set<string>()
    const options: Array<{ candidate: StoryMusicCandidate; cue?: StoryMusicCue; label: string }> = []
    project.music.cues.forEach(cue => cue.candidates.forEach(candidate => {
      if (seen.has(candidate.id)) return
      seen.add(candidate.id)
      options.push({
        candidate,
        cue,
        label: musicCandidateDisplayName(candidate, cue.title, cue.lyricsLanguage || project.language, cue.candidates.indexOf(candidate) + 1),
      })
    }))
    project.music.candidates.forEach(candidate => {
      if (seen.has(candidate.id)) return
      seen.add(candidate.id)
      options.push({
        candidate,
        label: musicCandidateDisplayName(candidate, project.title || 'Story song', project.music.lyricsLanguage || project.language, project.music.candidates.indexOf(candidate) + 1),
      })
    })
    return options
  }, [project.language, project.music.candidates, project.music.cues, project.music.lyricsLanguage, project.title])
  const selectedMusicOption = musicCandidateOptions.find(option => option.candidate.id === musicProductionCandidateId)

  useEffect(() => {
    let cancelled = false
    const model = requestedStoryVideoModel.trim()
    setStoryVideoOptionsState({ model, options: null, settled: !model })
    if (!model) return () => { cancelled = true }
    void api.fetchModelOptions(model).then(options => {
      if (!cancelled) setStoryVideoOptionsState({ model, options, settled: true })
    }).catch(() => {
      if (!cancelled) setStoryVideoOptionsState({ model, options: null, settled: true })
    })
    return () => { cancelled = true }
  }, [requestedStoryVideoModel])

  useEffect(() => {
    if (
      project.provider.useGlobalProfile
      || !storyVideoOptionsReady
      || !filmVideoModel
      || (legacyVideoOverridePending && !modelsLoaded)
    ) return
    const normalized = {
      model: filmVideoModel,
      resolution: storyVideoResolution,
      aspectRatio: storyVideoAspectRatio,
    }
    if (
      project.videoOverride.model === normalized.model
      && project.videoOverride.resolution === normalized.resolution
      && project.videoOverride.aspectRatio === normalized.aspectRatio
    ) return
    // Legacy override projects used the shared Director values. Capture them
    // once after hydration; subsequent edits are fully Story-local.
    patch({ videoOverride: normalized })
  }, [
    filmVideoModel,
    legacyVideoOverridePending,
    modelsLoaded,
    patch,
    project.provider.useGlobalProfile,
    project.videoOverride.aspectRatio,
    project.videoOverride.model,
    project.videoOverride.resolution,
    storyVideoAspectRatio,
    storyVideoOptionsReady,
    storyVideoResolution,
  ])

  const setStoryProfileMode = (useGlobalProfile: boolean) => {
    patch({
      provider: { ...project.provider, useGlobalProfile },
      ...(!useGlobalProfile && legacyVideoOverridePending ? {
        videoOverride: {
          model: filmVideoModel,
          resolution: storyVideoResolution,
          aspectRatio: storyVideoAspectRatio,
        },
      } : {}),
    })
  }

  const selectStoryVideoModel = (model: string) => {
    if (project.provider.useGlobalProfile || !model.trim()) return
    patch({
      videoOverride: {
        model,
        resolution: storyVideoResolution,
        aspectRatio: storyVideoAspectRatio,
      },
    })
  }

  const setStoryVideoFormat = (resolution: ResolutionPreset, aspectRatio: AspectRatio) => {
    const format = resolveSupportedVideoFormat(storyVideoOptions, resolution, aspectRatio)
    const outputSize = resolveResolution(storyVideoOptions, format.resolution, format.aspectRatio)
    const aspectLabel = STORY_VIDEO_ASPECTS.find(option => option.value === format.aspectRatio)?.label
      || format.aspectRatio
    patch({
      ...(project.provider.useGlobalProfile ? {
        provider: { ...project.provider, useGlobalProfile: false },
      } : {}),
      videoOverride: {
        model: filmVideoModel,
        resolution: format.resolution,
        aspectRatio: format.aspectRatio,
      },
    })
    setNotice({
      kind: 'ok',
      text: `Formato de vídeo actualizado: ${aspectLabel} · ${format.aspectRatio} · ${format.resolution} · ${outputSize}.`,
    })
  }

  useEffect(() => {
    if (selectedMusicOption || !musicCandidateOptions.length) return
    const preferred = musicCandidateOptions.find(option => option.cue?.selectedCandidateId === option.candidate.id)
      || musicCandidateOptions[0]
    setMusicProductionCandidateId(preferred.candidate.id)
  }, [musicCandidateOptions, selectedMusicOption])

  useEffect(() => {
    setStyleAssetIds([])
    setStyleConversion('')
  }, [project.id])

  useEffect(() => {
    const duration = selectedMusicOption?.candidate.durationSeconds || 0
    setMusicTrailerRange({ start: 0, end: duration, duration })
  }, [selectedMusicOption?.candidate.id, selectedMusicOption?.candidate.durationSeconds])

  useEffect(() => {
    if (!project.provider.useGlobalProfile) return
    const writingProvider: StoryWritingProvider = productionProfile.text.provider === 'minimax'
      ? 'minimax'
      : productionProfile.text.provider === 'openai'
        ? 'openai'
        : productionProfile.text.provider === 'deepseek'
          ? 'deepseek'
          : productionProfile.text.provider === 'openai-compatible'
            ? 'openai-compatible'
            : 'maestro'
    const writingBaseUrl = writingProvider === 'minimax'
      ? 'https://api.minimax.io/v1'
      : writingProvider === 'openai'
        ? 'https://api.openai.com'
        : writingProvider === 'deepseek'
          ? 'https://api.deepseek.com'
          : project.provider.writingBaseUrl
    const imageProvider: StoryImageProvider = productionProfile.image.provider === 'minimax'
      ? 'minimax' : 'maestro'
    if (
      project.provider.writingProvider === writingProvider
      && project.provider.writingModel === productionProfile.text.model
      && project.provider.writingBaseUrl === writingBaseUrl
      && project.provider.imageProvider === imageProvider
      && project.provider.imageModel === productionProfile.image.model
    ) return
    patch({
      provider: {
        ...project.provider,
        writingProvider,
        writingModel: productionProfile.text.model,
        writingBaseUrl,
        imageProvider,
        imageModel: productionProfile.image.model,
      },
    })
  }, [
    patch,
    productionProfile.image.model,
    productionProfile.image.provider,
    productionProfile.text.model,
    productionProfile.text.provider,
    project.provider,
  ])
  const beginStoryActivity = (phase: string, message: string, total = 0) => {
    const operationProjectId = project.id
    beginProjectOperation(operationProjectId)
    let operationEnded = false
    const endOperation = () => {
      if (operationEnded) return
      operationEnded = true
      endProjectOperation(operationProjectId)
    }
    const prefix = `story-lab:${project.id}:`
    const activityStore = useStore.getState()
    Object.values(activityStore.activities).forEach(previous => {
      if (
        previous.id.startsWith(prefix)
        && (previous.status === 'failed' || previous.status === 'completed')
      ) activityStore.removeActivity(previous.id)
    })
    const id = `${prefix}${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    const writer = project.provider.writingProvider === 'maestro'
      ? 'HocusPocus internal'
      : project.provider.writingModel || project.provider.writingProvider
    const title = `Story Lab · ${project.title.trim() || 'Untitled story'} · ${writer}`
    const lifecycle = createStoryActivityLifecycle({
      id,
      title,
      phase,
      message,
      total,
      publish: activity => useStore.getState().upsertActivity(activity),
      scheduleDismiss: activityId => {
        window.setTimeout(() => useStore.getState().removeActivity(activityId), 4000)
      },
    })
    return {
      ...lifecycle,
      fail: (error: unknown, failPhase?: string) => {
        endOperation()
        lifecycle.fail(error, failPhase)
      },
      cancel: (message?: string) => {
        endOperation()
        lifecycle.cancel(message)
      },
      finish: (message?: string, finishPhase?: string) => {
        endOperation()
        lifecycle.finish(message, finishPhase)
      },
    }
  }
  const selectableVideoModels = useMemo(
    () => videoModels
      .filter(model => model.is_i2v && enabledModels.has(model.model_type) && !model.tool_only)
      .sort((left, right) => left.name.localeCompare(right.name)),
    [enabledModels, videoModels],
  )
  const selectableImageModels = useMemo(
    () => videoModels
      .filter(model => getModelMode(model.model_type, model.family) === 'image' && enabledModels.has(model.model_type) && !model.tool_only)
      .sort((left, right) => left.name.localeCompare(right.name)),
    [enabledModels, videoModels],
  )
  const selectedFilmImageModel = videoModels.find(model => model.model_type === filmImageModel)
  const selectedFilmVideoModel = videoModels.find(model => model.model_type === filmVideoModel)
  const filmImageReady = filmImageModel !== MINIMAX_IMAGE_API_MODEL || Boolean(servicesConfig?.minimax_api_key_set)
  const effectiveMusicVideoMode = musicVideoShouldUseDirectVideo(project)
    ? 'direct_video'
    : project.musicVideoGenerationMode
  const directVideo = effectiveMusicVideoMode === 'direct_video'
  const directMusicVideo = directVideo
  const directReferenceVideo = project.musicVideoGenerationMode === 'direct_references'
  const promptHealthWarnings = useMemo(() => analyzeStoryPromptHealth(project), [project])
  const protagonist = project.characters.find(character => character.id === project.protagonistCharacterId)
  const protagonistReferenceReady = !project.protagonistConsistency || Boolean(
    protagonist?.primaryReferenceAssetId
    && project.assets[protagonist.primaryReferenceAssetId]?.approval === 'approved',
  )
  const attachedVisualReferenceIds = new Set([
    ...project.world.referenceAssetIds,
    ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ...project.characters.flatMap(character => character.referenceAssetIds),
  ])
  const approvedVisualReferenceCount = [...attachedVisualReferenceIds]
    .filter(id => project.assets[id]?.approval === 'approved').length
  const directReferenceVideoSupported = filmVideoModel.startsWith('minimax_h3')
  const directReferenceVideoReady = !directReferenceVideo
    || (directReferenceVideoSupported && approvedVisualReferenceCount > 0)
  const musicVideoImageReady = directMusicVideo || directReferenceVideo || filmImageReady
  const filmGenerationImageReady = directVideo || directReferenceVideo || filmImageReady
  const directVideoMasterReady = !directVideo || Boolean(project.directVideoMasterPrompt.trim())
  const musicWritingReady = project.provider.writingProvider === 'maestro'
    || (project.provider.writingProvider === 'deepseek' && Boolean(servicesConfig?.deepseek_api_key_set))
    || (project.provider.writingProvider === 'minimax' && Boolean(servicesConfig?.minimax_api_key_set))
    || (project.provider.writingProvider === 'openai' && Boolean(servicesConfig?.openai_api_key_set))
    || (project.provider.writingProvider === 'openai-compatible'
      && Boolean(servicesConfig?.compatible_api_key_set && project.provider.writingBaseUrl))
  const setMusicWritingProvider = (next: StoryWritingProvider) => {
    const defaults = next === 'deepseek'
      ? { writingModel: 'deepseek-v4-pro', writingBaseUrl: 'https://api.deepseek.com' }
      : next === 'minimax'
        ? { writingModel: 'MiniMax-M3', writingBaseUrl: 'https://api.minimax.io/v1' }
        : next === 'openai'
          ? { writingModel: 'gpt-4.1', writingBaseUrl: 'https://api.openai.com' }
          : next === 'openai-compatible'
            ? { writingModel: '', writingBaseUrl: servicesConfig?.compatible_base_url || '' }
            : { writingModel: project.provider.writingModel, writingBaseUrl: project.provider.writingBaseUrl }
    patch({ provider: { ...project.provider, writingProvider: next, ...defaults } })
  }
  const patchMusicWritingProvider = (value: Partial<StoryProject['provider']>) =>
    patch({ provider: { ...project.provider, ...value } })
  const musicWritingProviderParams = {
    writingProvider: project.provider.writingProvider,
    writingModel: project.provider.writingModel,
    writingBaseUrl: project.provider.writingBaseUrl,
  }

  useEffect(() => {
    loadWorkspace(activeWorkspace)
  }, [activeWorkspace, loadWorkspace])

  useEffect(() => {
    const savedJobId = window.localStorage.getItem(storyJobKey(activeWorkspace, project.id)) || ''
    setRecoveryJobId(savedJobId)
    setComicDirection(DEFAULT_COMIC_CHAPTER_DIRECTION)
    setComicPageCount(4)
    setComicPanelsPerPage(4)
    setFilmDirection(DEFAULT_SHORT_FILM_DIRECTION)
    setFilmDuration(45)
    let hasLocalResult = false
    let savedScope: StoryGenerationScope = 'all'
    let generateImagesAfterApply = false
    try {
      const saved = JSON.parse(window.localStorage.getItem(storyResultKey(activeWorkspace, project.id)) || 'null')
      hasLocalResult = Boolean(saved?.result)
      savedScope = saved?.scope || 'all'
      generateImagesAfterApply = saved?.generateImagesAfterApply === true
      setPendingDraft(saved?.result ? {
        scope: savedScope,
        result: saved.result,
        selected: draftPaths(saved.result),
        replaceCollections: true,
        generateImagesAfterApply,
      } : null)
    } catch {
      setPendingDraft(null)
    }
    let disposed = false
    if (savedJobId && !hasLocalResult) {
      void api.getStoryGenerationStatus(savedJobId).then(status => {
        const result = status.status === 'completed' ? status.result?.result : null
        if (disposed || !result) return
        const recovered = {
          jobId: savedJobId,
          scope: savedScope,
          result,
          generateImagesAfterApply,
        }
        window.localStorage.setItem(
          storyResultKey(activeWorkspace, project.id),
          JSON.stringify(recovered),
        )
        setPendingDraft({
          scope: savedScope,
          result,
          selected: draftPaths(result),
          replaceCollections: true,
          generateImagesAfterApply,
        })
        setNotice({ kind: 'ok', text: 'A Story Lab result completed on the server and was recovered automatically. Review and apply it below.' })
      }).catch(() => {
        // The visible Resume control remains available for failed, cancelled,
        // temporarily unreachable, or still-running checkpoints.
      })
    }
    return () => { disposed = true }
  }, [activeWorkspace, agentDraftRevision, project.id])

  useEffect(() => {
    if (project.projectType === 'quick_video') {
      setFilmDuration(project.creativeBrief.durationSeconds)
      setFilmDirection(project.creativeBrief.action || 'Create the complete quick video described by this Story Lab project.')
    }
  }, [project.creativeBrief.action, project.creativeBrief.durationSeconds, project.projectType])

  useEffect(() => {
    const currentProject = useStoryStore.getState().project
    setTrailerDirection(DEFAULT_TRAILER_DIRECTION)
    setTrailerDuration(trailerDurationForProject(currentProject.projectType, currentProject.creativeBrief.durationSeconds))
    setTrailerFormat('theatrical')
    setTrailerNarration('hybrid')
    setTrailerSpoiler('balanced')
    setTrailerIntensity('rising')
    setTrailerTagline('')
    setTrailerTitleCards(false)
    setTrailerPreserveVisualStyle(true)
    setTrailerTouched(false)
  }, [project.id]) // Each Story starts with a clean trailer treatment.

  useEffect(() => {
    setTrailerDuration(current => syncTrailerDuration(
      current,
      project.projectType,
      project.creativeBrief.durationSeconds,
      trailerTouched,
    ))
  }, [project.creativeBrief.durationSeconds, project.projectType, trailerTouched])

  const openStorySection = (target: StoryTab) => {
    const compactSection = project.projectType !== 'full_story'
      && ['world', 'characters', 'relationships', 'structure'].includes(target)
    setTab(compactSection ? 'overview' : target)
  }

  const openProductionReviewIssue = (issue: ProductionReviewIssue) => {
    openStorySection(issue.tab)
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      document.getElementById(issue.anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }))
  }

  const approve = (key: keyof StoryProject['approvals']) => {
    if (key === 'overview' && (!storyProjectPremise(project).trim() || !project.logline.trim() || !project.synopsis.trim())) {
      setNotice({ kind: 'error', text: 'Premise, logline and synopsis are required before approving the story.' })
      setTab('overview')
      return
    }
    if (key === 'world' && (!project.world.summary.trim() || !project.world.visualLanguage.trim())) {
      setNotice({ kind: 'error', text: 'Add a world summary and visual language before approving the world.' })
      openStorySection('world')
      return
    }
    if (key === 'characters') {
      const requiresVisualIdentities = !directVideo
      const incomplete = project.characters.flatMap(character => {
        const reasons = [
          character.approval !== 'approved' ? 'still marked draft' : '',
          requiresVisualIdentities && !character.primaryReferenceAssetId
            ? 'has no primary identity selected'
            : requiresVisualIdentities && character.primaryReferenceAssetId
              && project.assets[character.primaryReferenceAssetId]?.approval !== 'approved'
              ? 'has a missing or unapproved primary identity asset'
              : '',
        ].filter(Boolean)
        return reasons.length ? [`${character.name || 'Unnamed character'} (${reasons.join(', ')})`] : []
      })
      if (!project.characters.length || (requiresVisualIdentities && incomplete.length)) {
        setNotice({
          kind: 'error',
          text: !project.characters.length
            ? 'Add at least one character before approving the cast.'
            : `Cast approval is blocked: ${incomplete.join(' · ')}. Review each listed character, select its primary image, then click its draft button to approve it.`,
        })
        openStorySection('characters')
        return
      }
      if (!requiresVisualIdentities) {
        const changesCharacters = project.characters.some(character => character.approval !== 'approved')
        update(current => {
          current.characters = current.characters.map(character => ({ ...character, approval: 'approved' }))
          current.approvals.characters = {
            approvedAt: new Date().toISOString(),
            version: current.sectionVersions.characters + (changesCharacters ? 1 : 0),
          }
          return current
        })
        setNotice({ kind: 'ok', text: 'Character descriptions approved. Direct-video mode does not require identity images.' })
        return
      }
    }
    if (key === 'relationships' && project.relationships.some(relationship =>
      !relationship.fromCharacterId
      || !relationship.toCharacterId
      || relationship.fromCharacterId === relationship.toCharacterId
      || !relationship.dynamic.trim())) {
      setNotice({ kind: 'error', text: 'Every relationship needs two different characters and a current dynamic.' })
      openStorySection('relationships')
      return
    }
    if (key === 'structure' && (
      project.beats.length < 3
      || project.beats.some(beat => !beat.summary.trim() || !beat.conflict.trim() || !beat.turn.trim())
    )) {
      setNotice({ kind: 'error', text: 'Use at least three causal beats, each with action, conflict and a consequence.' })
      openStorySection('structure')
      return
    }
    patch({
      approvals: {
        ...project.approvals,
        [key]: {
          approvedAt: new Date().toISOString(),
          version: project.sectionVersions[key],
        },
      },
    })
  }
  const isApproved = (key: keyof StoryProject['approvals']) =>
    project.approvals[key]?.version === project.sectionVersions[key]

  const applyGeneratedResult = (
    result: Record<string, unknown>,
    selected = draftPaths(result),
    replaceCollections = true,
    projectId = project.id,
  ) => {
    const chosen = new Set(selected)
    updateProjectById(projectId, current => {
      const next = structuredClone(current)
      const characterIdMap = new Map<string, string>()
      const overview = result.overview as Record<string, unknown> | undefined
      if (overview) {
        Object.entries(overview).forEach(([key, value]) => {
          if (key === 'creativeBrief' && value && typeof value === 'object') {
            Object.entries(value as Record<string, unknown>).forEach(([field, fieldValue]) => {
              if (!chosen.has(`overview.creativeBrief.${field}`)) return
              if (typeof fieldValue === 'string' || typeof fieldValue === 'number') {
                ;(next.creativeBrief as unknown as Record<string, unknown>)[field] = fieldValue
              }
            })
          } else if (chosen.has(`overview.${key}`) && (
            typeof value === 'string' || typeof value === 'boolean'
          )) {
            ;(next as unknown as Record<string, unknown>)[key] = value
          }
        })
        next.music.brief = next.creativeBrief.songStory || next.music.brief
        next.music.style = next.creativeBrief.musicStyle || next.music.style
        next.music.targetDurationSeconds = next.creativeBrief.durationSeconds
      }
      if (result.world && typeof result.world === 'object') {
        const generated = result.world as Record<string, unknown>
        Object.entries(generated).forEach(([key, value]) => {
          if (!chosen.has(`world.${key}`)) return
          if (key === 'locations' && Array.isArray(value)) {
            next.world.locations = value.map((location, index) => {
              const raw = location && typeof location === 'object' ? location as Partial<StoryLocation> : {}
              const existing = current.world.locations.find(item =>
                item.id === raw.id || item.name === raw.name)
              return {
                id: existing?.id || (typeof raw.id === 'string' && raw.id ? raw.id : storyId('location')),
                name: typeof raw.name === 'string' ? raw.name : `Location ${index + 1}`,
                purpose: typeof raw.purpose === 'string' ? raw.purpose : '',
                description: typeof raw.description === 'string' ? raw.description : '',
                visualPrompt: typeof raw.visualPrompt === 'string' ? raw.visualPrompt : '',
                negativePrompt: typeof raw.negativePrompt === 'string' ? raw.negativePrompt : '',
                referenceAssetIds: existing?.referenceAssetIds || [],
              }
            })
          } else if (key === 'rules' && Array.isArray(value)) {
            next.world.rules = value.filter(item => typeof item === 'string')
          } else if (typeof value === 'string') {
            ;(next.world as unknown as Record<string, unknown>)[key] = value
          }
        })
      }
      if (Array.isArray(result.characters)) {
        const generatedCharacters = result.characters.map(normalizeStoryCharacter)
        const selectedCharacters = generatedCharacters
          .flatMap(character => {
            const existing = current.characters.find(item =>
              item.id === character.id || item.name === character.name)
            const selectedFields = Object.keys(character).filter(field =>
              !['id', 'referenceAssetIds', 'primaryReferenceAssetId', 'approval'].includes(field)
              && chosen.has(`characters.${character.id}.${field}`))
            if (!selectedFields.length) return []
            if (existing) characterIdMap.set(character.id, existing.id)
            const merged = {
              ...(existing || normalizeStoryCharacter({}, next.characters.length)),
              id: existing?.id || character.id,
              referenceAssetIds: existing?.referenceAssetIds || [],
              primaryReferenceAssetId: existing?.primaryReferenceAssetId,
              approval: 'draft' as const,
            }
            selectedFields.forEach(field => {
              ;(merged as unknown as Record<string, unknown>)[field] =
                (character as unknown as Record<string, unknown>)[field]
            })
            return [merged]
          })
        const selectedIds = new Set(selectedCharacters.map(character => character.id))
        const selectedNames = new Set(selectedCharacters.map(character => character.name))
        const kept = current.characters.filter(character =>
          !selectedIds.has(character.id) && !selectedNames.has(character.name))
        const allCharacterFieldsSelected = generatedCharacters.every(character =>
          Object.keys(character).filter(field =>
            !['id', 'referenceAssetIds', 'primaryReferenceAssetId', 'approval'].includes(field))
            .every(field => chosen.has(`characters.${character.id}.${field}`)))
        next.characters = replaceCollections && allCharacterFieldsSelected
          ? selectedCharacters
          : [...kept, ...selectedCharacters]
      }
      if (Array.isArray(result.relationships)) {
        const generatedRelationships = result.relationships as StoryRelationship[]
        const selectedRelationships = generatedRelationships.flatMap(item => {
          const existing = current.relationships.find(currentItem => currentItem.id === item.id)
          const selectedFields = Object.keys(item).filter(field =>
            field !== 'id' && chosen.has(`relationships.${item.id}.${field}`))
          if (!selectedFields.length) return []
          const merged: StoryRelationship = existing ? { ...existing } : {
            id: item.id || storyId('relationship'),
            fromCharacterId: '', toCharacterId: '', label: '', dynamic: '', evolution: '',
          }
          selectedFields.forEach(field => {
            ;(merged as unknown as Record<string, unknown>)[field] =
              (item as unknown as Record<string, unknown>)[field]
          })
          merged.fromCharacterId = characterIdMap.get(merged.fromCharacterId) || merged.fromCharacterId
          merged.toCharacterId = characterIdMap.get(merged.toCharacterId) || merged.toCharacterId
          return [merged]
        })
        const selectedIds = new Set(selectedRelationships.map(item => item.id))
        const kept = current.relationships.filter(item => !selectedIds.has(item.id))
        const allRelationshipFieldsSelected = generatedRelationships.every(item =>
          Object.keys(item).filter(field => field !== 'id')
            .every(field => chosen.has(`relationships.${item.id}.${field}`)))
        next.relationships = replaceCollections && allRelationshipFieldsSelected
          ? selectedRelationships : [...kept, ...selectedRelationships]
      }
      const structure = Array.isArray(result.structure) ? result.structure
        : Array.isArray(result.beats) ? result.beats : null
      if (structure) {
        const generatedBeats = structure as StoryBeat[]
        const selectedBeats = generatedBeats.flatMap(item => {
          const existing = current.beats.find(currentItem => currentItem.id === item.id)
          const selectedFields = Object.keys(item).filter(field =>
            field !== 'id' && chosen.has(`structure.${item.id}.${field}`))
          if (!selectedFields.length) return []
          const merged: StoryBeat = existing ? { ...existing } : {
            id: item.id || storyId('beat'),
            stage: '', title: '', summary: '', goal: '', conflict: '', turn: '',
          }
          selectedFields.forEach(field => {
            ;(merged as unknown as Record<string, unknown>)[field] =
              (item as unknown as Record<string, unknown>)[field]
          })
          return [merged]
        })
        const selectedIds = new Set(selectedBeats.map(item => item.id))
        const kept = current.beats.filter(item => !selectedIds.has(item.id))
        const allBeatFieldsSelected = generatedBeats.every(item =>
          Object.keys(item).filter(field => field !== 'id')
            .every(field => chosen.has(`structure.${item.id}.${field}`)))
        next.beats = replaceCollections && allBeatFieldsSelected
          ? selectedBeats : [...kept, ...selectedBeats]
      }
      const generatedMusic = result.music && typeof result.music === 'object'
        ? result.music as Record<string, unknown> : null
      if (generatedMusic && Array.isArray(generatedMusic.cues)) {
        const normalizedCues = normalizeStoryProject({
          ...next,
          music: { ...next.music, cues: generatedMusic.cues },
        }).music.cues
        const selectedCues = normalizedCues.flatMap(cue => {
          if (!chosen.has(`music.${cue.id}`)) return []
          const existing = current.music.cues.find(item =>
            item.id === cue.id || (item.kind === cue.kind && item.targetId === cue.targetId))
          return [{
            ...cue,
            candidates: existing?.candidates || [],
            selectedCandidateId: existing?.selectedCandidateId,
          }]
        })
        const replacedKeys = new Set(selectedCues.map(cue => `${cue.kind}:${cue.targetId}`))
        const kept = current.music.cues.filter(cue =>
          !replacedKeys.has(`${cue.kind}:${cue.targetId}`))
        const allSelected = normalizedCues.every(cue => chosen.has(`music.${cue.id}`))
        next.music.cues = replaceCollections && allSelected
          ? selectedCues : [...kept, ...selectedCues]
      }
      return next
    })
    setPendingDraft(null)
    window.localStorage.removeItem(storyResultKey(activeWorkspace, projectId))
    window.localStorage.removeItem(storyJobKey(activeWorkspace, projectId))
    if (useStoryStore.getState().project.id === projectId) setRecoveryJobId('')
    const characterCount = Array.isArray(result.characters) ? result.characters.length : 0
    const world = result.world && typeof result.world === 'object'
      ? result.world as Record<string, unknown> : null
    const locationCount = world && Array.isArray(world.locations) ? world.locations.length : 0
    const structure = Array.isArray(result.structure) ? result.structure
      : Array.isArray(result.beats) ? result.beats : []
    const generatedMusic = result.music && typeof result.music === 'object'
      ? result.music as Record<string, unknown> : null
    const musicCount = generatedMusic && Array.isArray(generatedMusic.cues)
      ? generatedMusic.cues.length : 0
    const overview = result.overview && typeof result.overview === 'object'
      ? result.overview as Record<string, unknown> : null
    const appliedTitle = typeof overview?.title === 'string' && overview.title.trim()
      ? overview.title.trim() : useStoryStore.getState().projects[projectId]?.title || 'Untitled story'
    setNotice({
      kind: 'ok',
      text: `Applied to “${appliedTitle}”: ${characterCount} characters · ${locationCount} locations · ${structure.length} moments · ${musicCount} song${musicCount === 1 ? '' : 's'}.`,
    })
  }

  const generateMissingImagesForScope = async (
    scope: StoryGenerationScope,
    projectId = useStoryStore.getState().project.id,
  ): Promise<boolean> => {
    const current = useStoryStore.getState().projects[projectId]
    if (!current) return false
    const targets = storyStyledReferenceTargets(current, {
      includeLocations: true,
      existingOnly: false,
    }).filter(item => {
      const inScope = scope === 'all'
        || (scope === 'characters' && item.target.kind === 'character')
        || (scope === 'world' && (item.target.kind === 'world' || item.target.kind === 'location'))
      if (!inScope) return false
      if (item.target.kind === 'world') return current.world.referenceAssetIds.length === 0
      if (item.target.kind === 'character') {
        return current.characters.find(character => character.id === item.target.id)?.referenceAssetIds.length === 0
      }
      return current.world.locations.find(location => location.id === item.target.id)?.referenceAssetIds.length === 0
    })
    if (!targets.length) {
      setNotice({ kind: 'ok', text: 'The text is ready. Every available visual target already has an image, or no visual prompt was generated.' })
      return true
    }
    const creditWarning = current.provider.imageProvider === 'minimax'
      ? ' This uses MiniMax image credits.' : ''
    if (!window.confirm(
      `Generate ${targets.length} concept image${targets.length === 1 ? '' : 's'} now: ${targets.map(item => item.label).join(', ')}? Existing references are preserved.${creditWarning}`,
    )) {
      setNotice({ kind: 'ok', text: 'The text preparation is complete. Image generation was skipped and can be started later.' })
      return true
    }
    setReferenceBatchBusy(true)
    const activity = beginStoryActivity(
      'generating_story_images',
      `Generating concept images: 0/${targets.length}`,
      targets.length,
    )
    let completed = 0
    let lastError = ''
    try {
      for (const item of targets) {
        activity.update(
          `Generating image ${completed + 1}/${targets.length}: ${item.label}`,
          'generating_story_images',
          completed,
          targets.length,
        )
        const ready = await generateVisual(item.target, item.prompt, {
          quiet: true,
          projectId,
          onError: message => { lastError = message },
          onJobSubmitted: jobId => activity.handoff(
            `Continuing as recoverable image job ${jobId}`,
          ),
        })
        if (!ready) {
          setNotice({
            kind: 'error',
            text: `Generated ${completed}/${targets.length} images. ${lastError || `Could not generate ${item.label}.`} The prepared text remains saved.`,
          })
          return false
        }
        completed += 1
      }
      setNotice({ kind: 'ok', text: `Text preparation and ${completed} concept image${completed === 1 ? '' : 's'} completed.` })
      return true
    } finally {
      activity.finish()
      setReferenceBatchBusy(false)
    }
  }

  const completeGeneratedDraft = async (
    scope: StoryGenerationScope,
    result: Record<string, unknown>,
    options: StoryGenerationOptions = {},
    projectId = project.id,
  ) => {
    if (project.workflowMode === 'guided') {
      setPendingDraft({
        scope,
        result,
        selected: draftPaths(result),
        replaceCollections: true,
        generateImagesAfterApply: options.generateImages === true,
      })
      setNotice({
        kind: 'ok',
        text: options.generateImages
          ? 'A generated text draft is ready. Review and apply it; its missing concept images will then be generated.'
          : 'A generated text draft is ready. Review the changes before applying them.',
      })
      return
    }
    applyGeneratedResult(result, draftPaths(result), true, projectId)
    if (scope === 'all') {
      if (options.generateImages && !await generateMissingImagesForScope(scope, projectId)) return
      if (!options.generateImages) {
        setNotice({ kind: 'ok', text: 'Text preparation completed. No images were generated.' })
      }
      setTab(project.projectType === 'music_video' ? 'music' : project.projectType === 'trailer' ? 'trailer' : 'productions')
    } else if (options.generateImages) {
      await generateMissingImagesForScope(scope, projectId)
    }
  }

  const generate = async (scope: StoryGenerationScope, options: StoryGenerationOptions = {}) => {
    const generationPremise = storyProjectPremise(project)
    if (!generationPremise.trim()) {
      setNotice({ kind: 'error', text: project.projectType === 'full_story' ? 'Write a premise first.' : 'Complete the creative brief first.' })
      return
    }
    const existingStoryParts = [
      project.characters.length ? `${project.characters.length} characters` : '',
      project.world.locations.length ? `${project.world.locations.length} locations` : '',
      project.beats.length ? `${project.beats.length} moments` : '',
      project.music.cues.length
        ? `${project.music.cues.length} song${project.music.cues.length === 1 ? '' : 's'}` : '',
    ].filter(Boolean)
    if (
      scope === 'all'
      && existingStoryParts.length
      && !window.confirm(
        `This Story already contains ${existingStoryParts.join(', ')}. Generate a new replacement draft? The current material remains unchanged until you review and apply the new draft.`,
      )
    ) return
    setBusy(scope)
    setNotice(null)
    const controller = new AbortController()
    generationAbortRef.current = controller
    const activity = beginStoryActivity(
      'story_planning',
      scope === 'music' ? 'Story Lab is planning the music proposals…' : 'Story Lab is preparing the generation request…',
    )
    let activeJobId = ''
    const sourceProjectId = project.id
    window.localStorage.setItem(storyResultKey(activeWorkspace, project.id), JSON.stringify({
      scope,
      generateImagesAfterApply: options.generateImages === true,
    }))
    try {
      const resolvedWriting = resolveStoryWritingProvider(productionProfile, project)
      const effectiveProvider: StoryProject['provider'] = project.provider.useGlobalProfile
        ? {
            ...project.provider,
            writingProvider: resolvedWriting.provider,
            writingModel: resolvedWriting.model,
            writingBaseUrl: resolvedWriting.baseUrl,
            imageProvider: productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
            imageModel: productionProfile.image.model,
          }
        : project.provider
      const generationProject = { ...project, provider: effectiveProvider }
      const { result } = await api.generateStorySection({
        scope,
        premise: generationPremise,
        language: project.language,
        genre: project.genre,
        tone: project.tone,
        audience: project.audience,
        instruction,
        project: generationProject,
        writingProvider: effectiveProvider.writingProvider,
        writingModel: effectiveProvider.writingModel,
        writingBaseUrl: effectiveProvider.writingBaseUrl,
        workspace: activeWorkspace,
      }, progress => {
        activity.handoff(`Continuing as recoverable job ${progress.jobId}`)
        activeJobId = progress.jobId
        setRecoveryJobId(progress.jobId)
        window.localStorage.setItem(storyJobKey(activeWorkspace, project.id), progress.jobId)
        setJobProgress(`${progress.message} ${progress.total ? `${progress.current}/${progress.total}` : ''}`)
        activity.update(
          progress.message,
          progress.stage === 'music' ? 'music_planning' : `story_${progress.stage || 'planning'}`,
          progress.current,
          progress.total,
        )
      }, controller.signal)
      setInstruction('')
      window.localStorage.setItem(storyResultKey(activeWorkspace, project.id), JSON.stringify({
        jobId: activeJobId,
        scope,
        result,
        generateImagesAfterApply: options.generateImages === true,
      }))
      if (useStoryStore.getState().project.id !== sourceProjectId) {
        setNotice({ kind: 'ok', text: 'Generation completed and was saved with its source story. Reopen that story to review the draft.' })
        return
      }
      await completeGeneratedDraft(scope, result, options, sourceProjectId)
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        activity.cancel('Story generation cancellation requested')
      } else {
        activity.fail(error)
      }
      setNotice({
        kind: (error as Error).name === 'AbortError' ? 'ok' : 'error',
        text: (error as Error).name === 'AbortError'
          ? 'Generation cancelled. Completed stages remain available through Resume.'
          : (error as Error).message,
      })
    } finally {
      activity.finish()
      if (generationAbortRef.current === controller) generationAbortRef.current = null
      setBusy(null)
      setJobProgress('')
    }
  }

  const applyPendingGeneratedDraft = async () => {
    if (!pendingDraft) return
    const { scope, result, selected, replaceCollections, generateImagesAfterApply } = pendingDraft
    const sourceProjectId = project.id
    applyGeneratedResult(result, selected, replaceCollections, sourceProjectId)
    if (generateImagesAfterApply && !await generateMissingImagesForScope(scope, sourceProjectId)) return
    if (scope === 'all') setTab(project.projectType === 'music_video' ? 'music' : project.projectType === 'trailer' ? 'trailer' : 'productions')
  }

  const cancelGeneration = async () => {
    generationAbortRef.current?.abort()
    if (recoveryJobId) {
      try {
        await api.cancelStoryGeneration(recoveryJobId)
      } catch (error) {
        setNotice({ kind: 'error', text: (error as Error).message })
      }
    }
  }

  const resumeGeneration = async () => {
    if (!recoveryJobId.trim() || busy) return
    const sourceProjectId = project.id
    const activity = beginStoryActivity('story_planning', 'Story Lab is resuming the saved generation…')
    activity.handoff(`Continuing as recoverable job ${recoveryJobId.trim()}`)
    setBusy('all')
    setNotice(null)
    try {
      const resolvedWriting = resolveStoryWritingProvider(
        useStore.getState().productionProfile,
        project,
      )
      const { result } = await api.resumeStoryGeneration(recoveryJobId.trim(), progress => {
        activity.handoff(`Continuing as recoverable job ${progress.jobId}`)
        setJobProgress(`${progress.message} ${progress.total ? `${progress.current}/${progress.total}` : ''}`)
        activity.update(
          progress.message,
          progress.stage === 'music' ? 'music_planning' : `story_${progress.stage || 'planning'}`,
          progress.current,
          progress.total,
        )
      }, {
        writingProvider: resolvedWriting.provider,
        writingModel: resolvedWriting.model,
        writingBaseUrl: resolvedWriting.baseUrl,
      })
      if (useStoryStore.getState().project.id !== sourceProjectId) return
      let generateImagesAfterApply = false
      try {
        const saved = JSON.parse(window.localStorage.getItem(storyResultKey(activeWorkspace, project.id)) || 'null')
        generateImagesAfterApply = saved?.generateImagesAfterApply === true
      } catch {
        // Resume remains safe as a text-only draft when legacy recovery metadata is malformed.
      }
      setPendingDraft({
        scope: 'all',
        result,
        selected: draftPaths(result),
        replaceCollections: true,
        generateImagesAfterApply,
      })
      window.localStorage.setItem(storyResultKey(activeWorkspace, project.id), JSON.stringify({
        jobId: recoveryJobId,
        scope: 'all',
        result,
        generateImagesAfterApply,
      }))
      setNotice({ kind: 'ok', text: 'Recovered Story Lab draft is ready for review.' })
    } catch (error) {
      const message = (error as Error).message
      if (/cancelled/i.test(message)) {
        activity.cancel('Saved Story Lab generation cancelled')
        setNotice({ kind: 'ok', text: 'That saved attempt was cancelled. Any completed stages and newer completed drafts remain available.' })
      } else {
        activity.fail(error)
        setNotice({ kind: 'error', text: message })
      }
    } finally {
      activity.finish()
      setBusy(null)
      setJobProgress('')
    }
  }

  const addAsset = (
    asset: StoryVisualAsset,
    target: { kind: 'world' | 'character' | 'location'; id?: string },
    replaceReferences = false,
    projectId = project.id,
  ) => {
    updateProjectById(projectId, current => {
      current.assets[asset.id] = asset
      if (target.kind === 'world') {
        current.world.referenceAssetIds = replaceReferences
          ? [asset.id] : [...current.world.referenceAssetIds, asset.id]
      }
      if (target.kind === 'character') {
        const character = current.characters.find(item => item.id === target.id)
        if (character) {
          character.referenceAssetIds = replaceReferences
            ? [asset.id] : [...character.referenceAssetIds, asset.id]
          if (replaceReferences || !character.primaryReferenceAssetId) {
            character.primaryReferenceAssetId = asset.id
          }
          character.approval = 'draft'
        }
      }
      if (target.kind === 'location') {
        const location = current.world.locations.find(item => item.id === target.id)
        if (location) {
          location.referenceAssetIds = replaceReferences
            ? [asset.id] : [...location.referenceAssetIds, asset.id]
        }
      }
      if (replaceReferences) pruneUnusedAssets(current)
      return current
    })
  }

  const generateVisual = async (
    target: { kind: 'world' | 'character' | 'location'; id?: string },
    prompt: string,
    options: {
      replaceReferences?: boolean
      usePrimaryReference?: boolean
      quiet?: boolean
      onError?: (message: string) => void
      onJobSubmitted?: (jobId: string) => void
      projectId?: string
    } = {},
  ) => {
    if (!prompt.trim()) return
    const key = `${target.kind}:${target.id || 'world'}`
    const sourceProjectId = options.projectId || useStoryStore.getState().project.id
    const current = useStoryStore.getState().projects[sourceProjectId]
    if (!current) return false
    const globalProfile = useStore.getState().productionProfile
    const effectiveImageProvider = current.provider.useGlobalProfile && globalProfile.image.provider === 'minimax'
      ? 'minimax' : current.provider.imageProvider
    const effectiveImageModel = current.provider.useGlobalProfile
      ? globalProfile.image.model : current.provider.imageModel
    const character = target.kind === 'character'
      ? current.characters.find(item => item.id === target.id) : undefined
    const location = target.kind === 'location'
      ? current.world.locations.find(item => item.id === target.id) : undefined
    const negativePrompt = target.kind === 'world'
      ? current.world.negativePrompt
      : character?.negativePrompt || location?.negativePrompt || ''
    const renderStyle = storyRenderStyle(current)
    const compatibleNegativePrompt = storyNegativePromptForStyle(
      negativePrompt,
      renderStyle,
      current.enforceVisualStyle,
    )
    const primaryReference = options.usePrimaryReference !== false && character?.primaryReferenceAssetId
      ? current.assets[character.primaryReferenceAssetId]?.source
      : undefined
    const effectivePrompt = [
      applyStoryVisualStyle(prompt, renderStyle, current.enforceVisualStyle),
      target.kind === 'character' ? CHARACTER_IDENTITY_REFERENCE_LOCK : '',
      'Single concept-art image, one coherent view, no contact sheet, no grid, no text, no labels.',
      compatibleNegativePrompt ? `Strictly avoid: ${compatibleNegativePrompt}.` : '',
    ].filter(Boolean).join(' ')
    const jobKey = `${key}:${stableTextKey(effectivePrompt)}`
    const existingJobId = current.visualJobs[jobKey]
    beginProjectOperation(sourceProjectId)
    setImageBusy(key)
    if (!options.quiet) setNotice(null)
    try {
      if (existingJobId) options.onJobSubmitted?.(existingJobId)
      const generated = await generateImageAsset(
        effectiveImageProvider,
        effectivePrompt,
        effectiveImageModel,
        primaryReference,
        negativePrompt.trim(),
        {
          panelId: `story-${jobKey}`,
          existingJobId,
          onJobSubmitted: jobId => {
            options.onJobSubmitted?.(jobId)
            updateProjectById(sourceProjectId, latest => {
              Object.keys(latest.visualJobs)
                .filter(item => item.startsWith(`${key}:`))
                .forEach(item => { delete latest.visualJobs[item] })
              latest.visualJobs[jobKey] = jobId
              return latest
            })
          },
          strictReference: Boolean(primaryReference),
        },
      )
      if (useStoryStore.getState().project.id !== sourceProjectId) {
        setNotice({
          kind: 'error',
          text: 'The concept finished after you changed stories, so it was not attached to the wrong one. Reopen the source story and retry to recover the completed job.',
        })
        return false
      }
      addAsset({
        id: storyId('asset'),
        name: generated.name,
        source: generated.source,
        prompt: effectivePrompt,
        negativePrompt,
        provider: effectiveImageProvider,
        model: generated.model,
        createdAt: new Date().toISOString(),
        approval: 'draft',
        variantKind: 'original',
      }, target, options.replaceReferences, sourceProjectId)
      updateProjectById(sourceProjectId, latest => {
        Object.keys(latest.visualJobs)
          .filter(item => item.startsWith(`${key}:`))
          .forEach(item => { delete latest.visualJobs[item] })
        return latest
      })
      if (!options.quiet) {
        setNotice({ kind: 'ok', text: 'Concept image generated and attached as a reference.' })
      }
      return true
    } catch (error) {
      const message = (error as Error).message
      if (!/job ID was preserved|could not reconnect/i.test(message)) {
        updateProjectById(sourceProjectId, latest => {
          delete latest.visualJobs[jobKey]
          return latest
        })
      }
      options.onError?.(message)
      if (!options.quiet) setNotice({ kind: 'error', text: message })
      return false
    } finally {
      setImageBusy('')
      endProjectOperation(sourceProjectId)
    }
  }
  const generateVisualRef = useRef(generateVisual)
  generateVisualRef.current = generateVisual
  useEffect(() => listenForAgentStoryVisualGeneration(async request => {
    const current = useStoryStore.getState().project
    if (current.id !== request.projectId) {
      throw new Error('La historia cambió mientras se preparaba la generación visual; no he generado imágenes en otro proyecto.')
    }
    const requestedNames = new Set(request.targetNames.map(storyLookupName).filter(Boolean))
    const includeCharacters = request.scope === 'characters' || request.scope === 'all'
    const includeLocations = request.scope === 'locations' || request.scope === 'all'
    const characters = includeCharacters
      ? current.characters.filter(character => !requestedNames.size || requestedNames.has(storyLookupName(character.name)))
      : []
    const locations = includeLocations
      ? current.world.locations.filter(location => !requestedNames.size || requestedNames.has(storyLookupName(location.name)))
      : []
    const ambiguous = [...requestedNames].filter(name => (
      characters.filter(character => storyLookupName(character.name) === name).length
      + locations.filter(location => storyLookupName(location.name) === name).length
    ) > 1)
    if (ambiguous.length) throw new Error(`Estos destinos visuales no son inequívocos: ${ambiguous.join(', ')}.`)
    const matchedNames = new Set([
      ...characters.map(character => storyLookupName(character.name)),
      ...locations.map(location => storyLookupName(location.name)),
    ])
    const unknown = [...requestedNames].filter(name => !matchedNames.has(name))
    if (unknown.length) throw new Error(`No existen estos destinos visuales en “${current.title}”: ${unknown.join(', ')}.`)

    const targets: Array<{ target: { kind: 'world' | 'character' | 'location'; id?: string }; label: string; prompt: string }> = []
    if (request.scope === 'world' || (request.scope === 'all' && !requestedNames.size)) {
      targets.push({ target: { kind: 'world' }, label: 'mundo', prompt: current.world.visualPrompt })
    }
    characters.forEach(character => targets.push({ target: { kind: 'character', id: character.id }, label: character.name, prompt: character.visualPrompt }))
    locations.forEach(location => targets.push({ target: { kind: 'location', id: location.id }, label: location.name, prompt: location.visualPrompt }))
    if (!targets.length) throw new Error('La selección no contiene mundos, personajes ni localizaciones que puedan generarse.')
    const missingPrompts = targets.filter(target => !target.prompt.trim()).map(target => target.label)
    if (missingPrompts.length) throw new Error(`Falta visualPrompt para: ${missingPrompts.join(', ')}.`)

    const assetIdsBefore = new Set(Object.keys(current.assets))
    let completed = 0
    let failure = ''
    for (const item of targets) {
      const ok = await generateVisualRef.current(item.target, item.prompt, {
        quiet: true,
        projectId: request.projectId,
        onError: message => { failure = message },
      })
      if (!ok) throw new Error(`${completed}/${targets.length} referencias terminadas. Falló “${item.label}”: ${failure || 'error de generación desconocido'}.`)
      completed += 1
    }
    setTab('assets')
    const message = `He generado y adjuntado ${completed} referencia${completed === 1 ? '' : 's'} visual${completed === 1 ? '' : 'es'} en “${current.title}”. Quedan en Draft dentro de Story Lab → Assets para que las revises y apruebes.`
    const latest = useStoryStore.getState().projects[request.projectId]
    const assetIds = latest ? Object.keys(latest.assets).filter(id => !assetIdsBefore.has(id)) : []
    if (assetIds.length !== completed) throw new Error('Las referencias visuales terminaron sin poder correlacionar todos sus IDs de asset.')
    setNotice({ kind: 'ok', text: message })
    return { message, assetIds }
  }), [])

  const writeStyleIntoPrompts = () => {
    const style = storyRenderStyle(project)
    if (!style) {
      setNotice({ kind: 'error', text: 'Write a global or character visual style before applying it to prompts.' })
      return
    }
    let changed = 0
    update(current => {
      current.enforceVisualStyle = true
      const apply = (value: string) => {
        if (!value.trim()) return value
        changed += 1
        return applyStoryVisualStyle(value, storyRenderStyle(current), true)
      }
      current.world.visualPrompt = apply(current.world.visualPrompt)
      current.world.locations.forEach(location => {
        location.visualPrompt = apply(location.visualPrompt)
      })
      current.characters.forEach(character => {
        character.visualPrompt = apply(character.visualPrompt)
      })
      return current
    })
    setNotice({
      kind: 'ok',
      text: changed
        ? `The replaceable style lock was written into ${changed} existing visual prompt${changed === 1 ? '' : 's'} and render-time enforcement is on.`
        : 'There are no existing visual prompts to update yet; render-time style enforcement is on.',
    })
  }

  const regenerateStyledReferences = () => {
    const sourceProjectId = project.id
    const current = useStoryStore.getState().projects[sourceProjectId]
    if (!current) return false
    if (!storyRenderStyle(current)) {
      setNotice({ kind: 'error', text: 'Write a global or character visual style before preparing reference conversion.' })
      return
    }
    const ids = [...new Set([
      ...current.world.referenceAssetIds,
      ...current.world.locations.flatMap(location => location.referenceAssetIds),
      ...current.characters.flatMap(character => character.referenceAssetIds),
    ])].filter(id => Boolean(current.assets[id]))
    if (!ids.length) {
      setNotice({ kind: 'error', text: 'There are no attached reference images to convert yet.' })
      return
    }
    update(latest => {
      latest.enforceVisualStyle = true
      return latest
    })
    setStyleConversion(storyRenderStyle(current))
    setStyleAssetIds(ids)
    setTab('assets')
    setNotice({
      kind: 'ok',
      text: `${ids.length} attached reference${ids.length === 1 ? ' is' : 's are'} selected. Review the style and start the non-destructive MiniMax conversion from Images.`,
    })
  }

  const uploadVisual = async (files: FileList | null) => {
    if (!files?.length || !uploadTarget) return
    const sourceProjectId = project.id
    beginProjectOperation(sourceProjectId)
    setImageBusy('upload')
    try {
      for (const file of Array.from(files)) {
        const uploaded = await api.uploadImage(file)
        addAsset({
          id: storyId('asset'), name: file.name, source: uploaded.url, prompt: '',
          provider: 'upload', createdAt: new Date().toISOString(),
          approval: 'draft', variantKind: 'original',
        }, uploadTarget, false, sourceProjectId)
      }
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      setImageBusy('')
      endProjectOperation(sourceProjectId)
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const analyzeSmartAssets = async (files: File[]) => {
    const images = files.filter(file => file.type.startsWith('image/')).slice(0, 24)
    if (!images.length) {
      setNotice({ kind: 'error', text: 'Choose one or more image files.' })
      return
    }
    const sourceProjectId = project.id
    const sourceProject = useStoryStore.getState().projects[sourceProjectId]
    if (!sourceProject) return
    const activity = beginStoryActivity(
      'uploading_assets', `Uploading 0/${images.length} assets…`, images.length + 1,
    )
    setSmartAssetBusy(true)
    setTab('assets')
    try {
      const uploaded: Array<{ name: string; path: string; url: string }> = []
      for (let index = 0; index < images.length; index += 1) {
        const file = images[index]
        activity.update(
          `Uploading ${index + 1}/${images.length}: ${file.name}`,
          'uploading_assets', index, images.length + 1,
        )
        const result = await api.uploadImage(file)
        uploaded.push({ name: file.name, path: result.path, url: result.url })
      }
      activity.update(
        `Analyzing ${images.length} assets together with the selected Story Lab LLM…`,
        'analyzing_assets', images.length, images.length + 1,
      )
      const result = await api.analyzeStoryAssets({
        assets: uploaded,
        description: smartAssetDescription,
        project: sourceProject,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
        activity_id: activity.id,
      })
      if (useStoryStore.getState().projects[sourceProjectId]) {
        setPendingSmartAssets(result.assets.map(item => ({ ...item, selected: item.kind !== 'ignore' })))
      }
      setNotice({ kind: 'ok', text: `${result.assets.length} asset suggestions are ready for review.` })
      activity.finish()
    } catch (error) {
      activity.fail(error, 'analyzing_assets')
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      setSmartAssetBusy(false)
      if (smartAssetRef.current) smartAssetRef.current.value = ''
    }
  }

  const patchPendingSmartAsset = (index: number, patchValue: Partial<PendingSmartAsset>) => {
    setPendingSmartAssets(current => current.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patchValue } : item))
  }

  const applySmartAssets = () => {
    const selected = pendingSmartAssets.filter(item => item.selected && item.kind !== 'ignore')
    if (!selected.length) return
    const batchId = storyId('asset-import')
    update(current => {
      const newTargets = new Map<string, string>()
      selected.forEach(item => {
        const assetId = storyId('asset')
        const asset: StoryVisualAsset = {
          id: assetId,
          name: item.name,
          source: item.source,
          prompt: item.visualPrompt,
          provider: 'upload',
          createdAt: new Date().toISOString(),
          assetKind: item.kind,
          description: item.description,
          confidence: item.confidence,
          originalName: item.nameOriginal,
          importBatchId: batchId,
          approval: 'draft',
          variantKind: 'original',
        }
        current.assets[assetId] = asset

        if (item.kind === 'character') {
          let character = current.characters.find(candidate => candidate.id === item.targetId)
          if (!character) {
            const groupingKey = item.targetId || `new-character:${item.name.toLocaleLowerCase()}`
            const existingId = newTargets.get(groupingKey)
            character = existingId
              ? current.characters.find(candidate => candidate.id === existingId)
              : undefined
            if (!character) {
              character = {
                ...emptyCharacter(),
                id: storyId('character'),
                name: item.name,
                appearance: item.description,
                visualPrompt: item.visualPrompt,
              }
              current.characters.push(character)
              newTargets.set(groupingKey, character.id)
            }
          }
          character.referenceAssetIds = [...new Set([...character.referenceAssetIds, assetId])]
          character.primaryReferenceAssetId ||= assetId
          character.approval = 'draft'
          return
        }

        if (item.kind === 'location') {
          let location = current.world.locations.find(candidate => candidate.id === item.targetId)
          if (!location) {
            const groupingKey = item.targetId || `new-location:${item.name.toLocaleLowerCase()}`
            const existingId = newTargets.get(groupingKey)
            location = existingId
              ? current.world.locations.find(candidate => candidate.id === existingId)
              : undefined
            if (!location) {
              location = {
                id: storyId('location'), name: item.name, purpose: '',
                description: item.description, visualPrompt: item.visualPrompt,
                negativePrompt: '', referenceAssetIds: [],
              }
              current.world.locations.push(location)
              newTargets.set(groupingKey, location.id)
            }
          }
          location.referenceAssetIds = [...new Set([...location.referenceAssetIds, assetId])]
          return
        }

        current.world.referenceAssetIds = [...new Set([...current.world.referenceAssetIds, assetId])]
      })
      return current
    })
    setPendingSmartAssets([])
    setNotice({ kind: 'ok', text: `${selected.length} assets applied to Story Lab. New entities remain editable drafts.` })
  }

  const patchVisualAsset = (assetId: string, patchValue: Partial<StoryVisualAsset>) => {
    update(current => {
      const asset = current.assets[assetId]
      if (asset) current.assets[assetId] = { ...asset, ...patchValue }
      return current
    })
  }

  const toggleStyleAsset = (assetId: string) => {
    setStyleAssetIds(current => current.includes(assetId)
      ? current.filter(id => id !== assetId)
      : [...current, assetId])
  }

  const selectedDraftAssetIds = styleAssetIds.filter(id => project.assets[id]?.approval === 'draft')
  const visualAssetsNewestFirst = Object.values(project.assets).sort((left, right) =>
    Date.parse(right.createdAt || '') - Date.parse(left.createdAt || ''))

  const deleteSelectedDraftAssets = () => {
    const snapshot = useStoryStore.getState().project
    const draftIds = styleAssetIds.filter(id => snapshot.assets[id]?.approval === 'draft')
    const approvedCount = styleAssetIds.filter(id => snapshot.assets[id]?.approval === 'approved').length
    if (!draftIds.length) {
      setNotice({ kind: 'error', text: 'Select one or more Draft images to remove from the Story library.' })
      return
    }
    if (!window.confirm(
      `Remove ${draftIds.length} selected Draft image${draftIds.length === 1 ? '' : 's'} from this Story?${approvedCount ? ` ${approvedCount} approved selection${approvedCount === 1 ? ' is' : 's are'} protected and will be kept.` : ''} Generated files remain available in Gallery.`,
    )) return

    update(current => {
      const deleting = new Set(draftIds.filter(id => current.assets[id]?.approval === 'draft'))
      current.world.referenceAssetIds = current.world.referenceAssetIds.filter(id => !deleting.has(id))
      current.world.locations.forEach(location => {
        location.referenceAssetIds = location.referenceAssetIds.filter(id => !deleting.has(id))
      })
      current.characters.forEach(character => {
        character.referenceAssetIds = character.referenceAssetIds.filter(id => !deleting.has(id))
        if (character.primaryReferenceAssetId && deleting.has(character.primaryReferenceAssetId)) {
          character.primaryReferenceAssetId = character.referenceAssetIds.find(id => current.assets[id]?.approval === 'approved')
            || character.referenceAssetIds[0]
          character.approval = 'draft'
        }
      })
      Object.values(current.assets).forEach(asset => {
        if (asset.derivedFromAssetId && deleting.has(asset.derivedFromAssetId)) {
          delete asset.derivedFromAssetId
        }
      })
      deleting.forEach(id => delete current.assets[id])
      return current
    })
    const removed = new Set(draftIds)
    setStyleAssetIds(current => current.filter(id => !removed.has(id)))
    setNotice({
      kind: 'ok',
      text: `${draftIds.length} Draft image${draftIds.length === 1 ? '' : 's'} removed from the Story library. Generated files remain in Gallery.${approvedCount ? ` ${approvedCount} approved image${approvedCount === 1 ? ' was' : 's were'} kept.` : ''}`,
    })
  }

  const styleUsesMiniMax = styleConversionModel === MINIMAX_IMAGE_API_MODEL
  const styleUsesFlux = styleConversionModel === FLUX_STYLE_EDIT_MODEL
  const localStyleModels = videoModels.filter(model =>
    (model.model_type.startsWith('qwen_image_edit') || model.model_type === FLUX_STYLE_EDIT_MODEL)
    && getModelMode(model.model_type, model.family) === 'image')
  const selectedStyleModel = styleUsesMiniMax
    ? undefined : videoModels.find(model => model.model_type === styleConversionModel)
  const styleModelReady = styleUsesMiniMax
    ? Boolean(servicesConfig?.minimax_api_key_set)
    : Boolean(selectedStyleModel?.is_downloaded)
  const miniMaxIncompatibleSelection = styleUsesMiniMax && styleAssetIds.some(id =>
    useStoryStore.getState().project.assets[id]?.assetKind !== 'character')

  useEffect(() => {
    if (!styleModelDownloading) return
    let cancelled = false
    const poll = async () => {
      try {
        const { downloads } = await api.fetchModelDownloads()
        if (cancelled) return
        const current = downloads[styleModelDownloading]
        if (current?.status === 'completed') {
          await useStore.getState().loadModels()
          if (cancelled) return
          const installedName = useStore.getState().models.find(model => model.model_type === styleModelDownloading)?.name
            || styleModelDownloading
          setStyleModelDownloading('')
          setStyleModelDownloadError('')
          setNotice({ kind: 'ok', text: `${installedName} is installed and ready for local style conversion.` })
        } else if (current?.status === 'failed') {
          setStyleModelDownloading('')
          setStyleModelDownloadError(current.error || 'Model download failed. Check Activity for details.')
        }
      } catch {
        // Maestro may be restarting while a background download continues.
      }
    }
    void poll()
    const interval = window.setInterval(() => void poll(), 2000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [styleModelDownloading])

  const installStyleConversionModel = async () => {
    if (styleUsesMiniMax || !selectedStyleModel || selectedStyleModel.is_downloaded) return
    if (!window.confirm(
      `Install ${selectedStyleModel.name}? Model files download once and may require tens of GB; progress remains visible in Activity.`,
    )) return
    setStyleModelDownloadError('')
    setStyleModelDownloading(selectedStyleModel.model_type)
    try {
      await api.downloadModel(selectedStyleModel.model_type)
      setNotice({ kind: 'ok', text: `Downloading ${selectedStyleModel.name}. You can keep using HocusPocus while it installs.` })
    } catch (error) {
      setStyleModelDownloading('')
      setStyleModelDownloadError((error as Error).message)
    }
  }

  const convertSelectedAssetsToStyle = async () => {
    const sourceProjectId = project.id
    const style = styleConversion.trim()
    const selected = styleAssetIds
      .map(id => useStoryStore.getState().project.assets[id])
      .filter((asset): asset is StoryVisualAsset => Boolean(asset))
    if (!style) {
      setNotice({ kind: 'error', text: 'Describe the destination style before converting images.' })
      return
    }
    if (!selected.length) {
      setNotice({ kind: 'error', text: 'Select one or more images from the library first.' })
      return
    }
    if (styleUsesMiniMax && !servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services first, or choose local Qwen or Flux image editing.' })
      return
    }
    if (miniMaxIncompatibleSelection) {
      setNotice({ kind: 'error', text: 'MiniMax Image-01 references are documented for character identity only. Choose Qwen Image Edit or Flux 2 Klein for locations, worlds, props or style references.' })
      return
    }
    if (!styleUsesMiniMax && !selectedStyleModel?.is_downloaded) {
      setNotice({ kind: 'error', text: 'Install the selected local image editor before starting the batch.' })
      return
    }
    const modelLabel = styleUsesMiniMax
      ? 'MiniMax Image-01 API' : `${selectedStyleModel?.name || styleConversionModel} · local`
    if (!window.confirm(
      `Create ${selected.length} non-destructive style variant${selected.length === 1 ? '' : 's'} with ${modelLabel}? The originals remain available.${styleUsesMiniMax ? ' Each API request may consume credits.' : ' Generation runs locally on the GPU.'}`,
    )) return

    styleConversionCancelRequested.current = false
    setStyleConversionBusy(true)
    setNotice(null)
    const activity = beginStoryActivity(
      'converting_reference_style',
      `Converting references to “${style}”: 0/${selected.length}`,
      selected.length,
    )
    let completed = 0
    try {
      for (const sourceAsset of selected) {
        if (styleConversionCancelRequested.current) break
        activity.update(
          `${modelLabel} · ${completed + 1}/${selected.length} · ${sourceAsset.name}`,
          'converting_reference_style',
          completed,
          selected.length,
        )
        const prompt = styleConversionPrompt(sourceAsset, style, styleUsesMiniMax ? 'minimax' : styleUsesFlux ? 'flux' : 'qwen')
        const aspectRatio = await sourceAspectRatio(sourceAsset.source)
        const generated = await generateImageAsset(
          styleUsesMiniMax ? 'minimax' : 'maestro',
          prompt,
          styleUsesMiniMax ? 'image-01' : styleConversionModel,
          sourceAsset.source,
          '',
          {
            aspectRatio,
            panelId: `story-style-${sourceAsset.id}-${stableTextKey(`${styleConversionModel}:${style}`)}`,
            referenceMode: 'edit',
            resolution: STYLE_RESOLUTION_BY_ASPECT[aspectRatio],
            strictReference: true,
            onJobSubmitted: jobId => activity.handoff(
              `Continuing as recoverable image job ${jobId}`,
            ),
          },
        )
        const derivedId = storyId('asset')
        updateProjectById(sourceProjectId, current => {
          if (!current.assets[sourceAsset.id]) return current
          const shortStyle = style.replace(/\s+/g, ' ').slice(0, 48)
          current.assets[derivedId] = {
            id: derivedId,
            name: `${sourceAsset.name} · ${shortStyle}`,
            source: generated.source,
            prompt,
            provider: styleUsesMiniMax ? 'minimax' : 'maestro',
            model: generated.model || (styleUsesMiniMax ? 'image-01' : styleConversionModel),
            createdAt: new Date().toISOString(),
            assetKind: sourceAsset.assetKind,
            description: sourceAsset.description,
            originalName: sourceAsset.originalName || sourceAsset.name,
            approval: 'draft',
            variantKind: 'styled',
            derivedFromAssetId: sourceAsset.id,
            stylePrompt: style,
          }
          let attached = false
          if (current.world.referenceAssetIds.includes(sourceAsset.id)) {
            current.world.referenceAssetIds = [...new Set([...current.world.referenceAssetIds, derivedId])]
            attached = true
          }
          current.world.locations.forEach(location => {
            if (!location.referenceAssetIds.includes(sourceAsset.id)) return
            location.referenceAssetIds = [...new Set([...location.referenceAssetIds, derivedId])]
            attached = true
          })
          current.characters.forEach(character => {
            if (!character.referenceAssetIds.includes(sourceAsset.id)) return
            character.referenceAssetIds = [...new Set([...character.referenceAssetIds, derivedId])]
            character.approval = 'draft'
            attached = true
          })
          if (!attached) current.world.referenceAssetIds.push(derivedId)
          return current
        })
        completed += 1
        activity.update(
          `Styled variant ready ${completed}/${selected.length} · awaiting approval`,
          'converting_reference_style',
          completed,
          selected.length,
        )
      }
      if (styleConversionCancelRequested.current) {
        setNotice({ kind: 'ok', text: `Style conversion stopped after ${completed}/${selected.length}. Completed variants were preserved as drafts.` })
      } else {
        setNotice({ kind: 'ok', text: `${completed} styled variant${completed === 1 ? '' : 's'} created. Review and approve only the images Director should use.` })
      }
    } catch (error) {
      activity.fail(error, 'converting_reference_style')
      setNotice({ kind: 'error', text: `Style conversion stopped after ${completed}/${selected.length}: ${(error as Error).message}` })
    } finally {
      activity.finish()
      styleConversionCancelRequested.current = false
      setStyleConversionBusy(false)
      setStyleAssetIds([])
    }
  }

  const cancelStyleConversion = () => {
    styleConversionCancelRequested.current = true
    setNotice({ kind: 'ok', text: 'Stopping after the current image finishes…' })
  }

  const removeReference = (target: 'world' | 'character' | 'location', targetId: string | undefined, assetId: string) => {
    update(current => {
      if (target === 'world') current.world.referenceAssetIds = current.world.referenceAssetIds.filter(id => id !== assetId)
      if (target === 'character') {
        const character = current.characters.find(item => item.id === targetId)
        if (character) {
          character.referenceAssetIds = character.referenceAssetIds.filter(id => id !== assetId)
          if (character.primaryReferenceAssetId === assetId) character.primaryReferenceAssetId = character.referenceAssetIds[0]
        }
      }
      if (target === 'location') {
        const location = current.world.locations.find(item => item.id === targetId)
        if (location) location.referenceAssetIds = location.referenceAssetIds.filter(id => id !== assetId)
      }
      const stillReferenced = current.world.referenceAssetIds.includes(assetId)
        || current.world.locations.some(location => location.referenceAssetIds.includes(assetId))
        || current.characters.some(character => character.referenceAssetIds.includes(assetId))
      if (!stillReferenced) delete current.assets[assetId]
      return current
    })
  }

  const exportStorypack = async () => {
    const sourceProjectId = project.id
    beginProjectOperation(sourceProjectId)
    try {
      const zip = new JSZip()
      const packed = structuredClone(project) as StoryProject & { packedAssets?: Record<string, string> }
      packed.packedAssets = {}
      await Promise.all(Object.values(project.assets).map(async asset => {
        try {
          const blob = await fetch(asset.source).then(response => response.blob())
          const extension = blob.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png'
          const path = `assets/${asset.id}.${extension}`
          zip.file(path, blob)
          packed.packedAssets![asset.id] = path
        } catch {
          // Keep the original source in the manifest when an old asset is unavailable.
        }
      }))
      zip.file('story.json', JSON.stringify(packed, null, 2))
      const blob = await zip.generateAsync({ type: 'blob' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `${project.title.replace(/[^\w.-]+/g, '-') || 'story'}.storypack`
      link.click()
      URL.revokeObjectURL(link.href)
    } finally {
      endProjectOperation(sourceProjectId)
    }
  }

  const importStorypack = async (file?: File) => {
    if (!file) return
    const sourceProjectId = project.id
    beginProjectOperation(sourceProjectId)
    try {
      let imported: StoryProject & { packedAssets?: Record<string, string> }
      let zip: JSZip | null = null
      if (file.name.endsWith('.json')) {
        imported = JSON.parse(await file.text())
      } else {
        zip = await JSZip.loadAsync(file)
        const manifest = zip.file('story.json')
        if (!manifest) throw new Error('The Storypack has no story.json manifest')
        imported = JSON.parse(await manifest.async('text'))
      }
      if (zip && imported.packedAssets) {
        for (const [assetId, path] of Object.entries(imported.packedAssets)) {
          const entry = zip.file(path)
          if (!entry || !imported.assets[assetId]) continue
          const blob = await entry.async('blob')
          const uploaded = await api.uploadImage(new File([blob], path.split('/').pop() || `${assetId}.png`, { type: blob.type }))
          imported.assets[assetId].source = uploaded.url
        }
      }
      delete imported.packedAssets
      const normalized = normalizeStoryProject(imported)
      if (projects[normalized.id]) {
        normalized.id = storyId('story')
        normalized.title = `${normalized.title} imported`
      }
      // Import is owned by the Story that opened the file picker. If the user
      // navigated while uploads were in flight, do not replace the new Story.
      if (useStoryStore.getState().project.id !== sourceProjectId) {
        setNotice({ kind: 'error', text: 'The Storypack finished after you changed Stories; it was not applied to the wrong Story.' })
        return
      }
      setProject(normalized)
      setNotice({ kind: 'ok', text: 'Story project imported with its editable bible and available visual references.' })
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      endProjectOperation(sourceProjectId)
      if (importRef.current) importRef.current.value = ''
    }
  }

  const stageComic = (autoStart = false) => {
    const existingDirty = useComicStore.getState().dirty
    const pageCount = Math.max(1, Math.min(100, Math.round(comicPageCount || 4)))
    const panelsPerPage = Math.max(1, Math.min(12, Math.round(comicPanelsPerPage || 4)))
    const estimatedPanels = pageCount * panelsPerPage
    const confirmed = autoStart
      ? window.confirm(
        `Generate a complete ${pageCount}-page, ${estimatedPanels}-panel comic chapter from this story? The current comic will be replaced and image generation may use provider credits.`,
      )
      : !existingDirty || window.confirm(
        'Open a new comic chapter in Director? Unsaved changes in the current comic will be lost.',
      )
    if (!confirmed) return
    const { comic, request } = buildComicAdaptation(project, comicDirection, {
      pageCount,
      panelsPerPage,
    })
    useComicStore.getState().setProject(comic)
    window.localStorage.removeItem('maestro-last-comic-plan-result')
    window.localStorage.removeItem('maestro-last-comic-plan-job')
    window.localStorage.setItem('maestro-story-comic-draft', JSON.stringify(request))
    if (autoStart) {
      window.localStorage.setItem('maestro-story-comic-auto-start', JSON.stringify({
        id: project.id,
        revision: project.revision,
      }))
    } else {
      window.localStorage.removeItem('maestro-story-comic-auto-start')
    }
    window.dispatchEvent(new CustomEvent('maestro:comic-staged', { detail: request }))
    patch({
      productions: [...project.productions, {
        id: storyId('production'), kind: 'comic', title: `${project.title} · comic chapter`,
        createdAt: new Date().toISOString(), sourceVersion: project.revision,
        sourceSnapshot: { ...structuredClone(project), productions: [] },
        targetId: comic.id,
        targetName: comic.title,
        targetSnapshot: {
          comic: structuredClone(comic) as unknown as Record<string, unknown>,
          request: structuredClone(request) as unknown as Record<string, unknown>,
        },
        status: 'staged',
      }],
    })
    const maestro = useStore.getState()
    maestro.setMediaFilter('comics')
    maestro.setSidebarMode('director')
    maestro.setDirectorSkill('comic')
    window.dispatchEvent(new Event('maestro:director-open'))
  }

  const loadFilmProduction = async (
    source: StoryProject,
    direction = DEFAULT_SHORT_FILM_DIRECTION,
    autoStart = false,
    targetDuration = filmDuration,
    preserveVisualStyle = filmPreserveVisualStyle,
    videoModel = filmVideoModel,
    imageModel = filmImageModel,
    resolution = storyVideoResolution,
    aspectRatio = storyVideoAspectRatio,
    trailerOptions?: TrailerAdaptationOptions,
  ) => {
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
    const store = useStore.getState()
    store.setGenerationMode('video')
    if (!directVideo && !directReferences && imageModel) {
      useStore.getState().selectDirectorImageModel(imageModel)
    }
    if (videoModel) {
      await useStore.getState().selectDirectorVideoModel(videoModel)
      const selected = useStore.getState().selectedModelPerMode.video
      if (selected !== videoModel) {
        throw new Error(
          `Video model selection did not settle: requested ${videoModel}, effective ${selected || 'none'}.`,
        )
      }
    }
    store.setDirectorResolution(resolution)
    store.setDirectorAspectRatio(aspectRatio)
    store.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
    if (videoModel.startsWith('minimax_h3') && !directVideo) {
      store.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
    }
    // setSidebarMode normally sends a fresh Director session to its route
    // chooser. Open it before restoring the Story Lab payload, otherwise it
    // overwrites the preloaded `style` step with `upload`.
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
    store.setDirectorAutoMode(autoStart)
    useStore.setState({
      directorWritingProvider: source.provider.writingProvider,
      directorWritingModel: source.provider.writingModel,
      directorWritingBaseUrl: source.provider.writingBaseUrl,
    })
    for (const reference of directVideo ? [] : adaptation.characterReferences) {
      const asset = source.assets[reference.assetId]
      if (!asset) continue
      try {
        const blob = await fetch(asset.source).then(response => {
          if (!response.ok) throw new Error('Reference unavailable')
          return response.blob()
        })
        const file = new File([blob], asset.name || `${reference.assetId}.png`, { type: blob.type })
        store.directorAddCharacterRef(file)
        const index = useStore.getState().directorCharacterRefs.length - 1
        useStore.getState().directorSetCharacterRefLabel(index, reference.label)
      } catch {
        // The written bible is still staged if an older reference disappeared.
      }
    }
    for (const reference of directVideo ? [] : adaptation.locationReferences) {
      const asset = source.assets[reference.assetId]
      if (!asset) continue
      try {
        const blob = await fetch(asset.source).then(response => {
          if (!response.ok) throw new Error('Reference unavailable')
          return response.blob()
        })
        store.directorAddLocationRef(new File(
          [blob],
          asset.name || `${reference.assetId}.png`,
          { type: blob.type || 'image/png' },
        ))
        const index = useStore.getState().directorLocationRefs.length - 1
        useStore.getState().directorSetLocationRefLabel(index, reference.label)
      } catch {
        // Keep staging the production; the missing asset remains visible in Story Lab.
      }
    }
    useStore.setState({ directorStep: 'style' })
    store.setMediaFilter('all')
    window.dispatchEvent(new Event('maestro:director-open'))
    if (autoStart) await useStore.getState().startDirectorPipeline()
    return adaptation
  }

  const stageFilm = async (autoStart = false) => {
    const sourceProjectId = project.id
    if (!storyVideoConfigurationReady) {
      setNotice({
        kind: 'error',
        text: legacyVideoOverridePending
          ? 'Restoring this legacy Story’s previous video model and format. Try again in a moment.'
          : 'Checking the selected video model’s supported formats. Try again in a moment.',
      })
      return
    }
    const director = useStore.getState()
    const hasDirectorWork = Boolean(
      director.directorSceneDescription.trim()
      || director.directorPlannedClips.length
      || director.directorCharacterRefs.length
      || director.directorLocationRefs.length,
    )
    if (!directReferenceVideoReady) {
      setNotice({
        kind: 'error',
        text: directReferenceVideoSupported
          ? 'Approve at least one visual asset before using direct references.'
          : 'Choose a MiniMax H3 video model before using direct references.',
      })
      return
    }
    const confirmed = autoStart
      ? window.confirm(
        directReferenceVideo
          ? `Generate this video with ${approvedVisualReferenceCount} approved references sent directly to H3 Ref2VA? No start images will be generated.`
          : 'Generate a complete short-film episode from this story? The current Director draft will be replaced and image/video generation may use provider credits.',
      )
      : !hasDirectorWork || window.confirm(
        'Open a clean short-film episode in Director? The current Director draft will be replaced.',
    )
    if (!confirmed) return
    beginProjectOperation(sourceProjectId)
    setProductionBusy('film')
    try {
      const adaptation = await loadFilmProduction(
        project,
        filmDirection,
        autoStart,
        filmDuration,
        filmPreserveVisualStyle,
      )
      updateProjectById(sourceProjectId, current => ({
        ...current,
        productions: [...current.productions, {
          id: storyId('production'), kind: 'film', title: `${project.title} · short episode`,
          createdAt: new Date().toISOString(), sourceVersion: project.revision,
          sourceSnapshot: { ...structuredClone(project), productions: [] },
          targetName: `${project.title} · short episode`,
          targetSnapshot: {
            direction: filmDirection,
            sceneDescription: adaptation.sceneDescription,
            characters: adaptation.characters,
            targetDuration: adaptation.targetDuration,
            narrative: adaptation.narrative,
            visualStyle: adaptation.visualStyle,
            preserveVisualStyle: adaptation.preserveVisualStyle,
            imageModel: filmImageModel,
            videoModel: filmVideoModel,
            generationMode: project.musicVideoGenerationMode,
            resolution: storyVideoResolution,
            aspectRatio: storyVideoAspectRatio,
            pipelineId: useStore.getState().pipelineId || undefined,
          },
          status: 'staged',
        }],
      }))
      setNotice({
        kind: 'ok',
        text: autoStart
          ? 'The short-film episode is running in Director; its pipeline remains recoverable from Productions.'
          : 'The complete story canon and approved visual references are loaded in Short Film Director.',
      })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: `The short-film episode could not be staged: ${(error as Error).message}`,
      })
    } finally {
      endProjectOperation(sourceProjectId)
      setProductionBusy(null)
    }
  }

  const stageTrailer = async (autoStart = false) => {
    const sourceProjectId = project.id
    if (!storyVideoConfigurationReady) {
      setNotice({
        kind: 'error',
        text: legacyVideoOverridePending
          ? 'Restaurando el modelo y formato anterior de esta Story. Inténtalo de nuevo en un momento.'
          : 'Comprobando los formatos compatibles del modelo de vídeo. Inténtalo de nuevo en un momento.',
      })
      return
    }
    if (!project.synopsis.trim() || !project.characters.length) {
      setNotice({ kind: 'error', text: 'El tráiler necesita una sinopsis y al menos un personaje.' })
      return
    }
    if (trailerTitleCards && !project.allowClipText) {
      setNotice({
        kind: 'error',
        text: 'Activa “Permitir texto visible” en Story para generar cartelas; o selecciona “Sin cartelas”.',
      })
      return
    }
    if (!directVideoMasterReady) {
      setNotice({ kind: 'error', text: 'El vídeo directo necesita un prompt maestro de mundo y estilo.' })
      return
    }
    if (!directReferenceVideoReady) {
      setNotice({
        kind: 'error',
        text: directReferenceVideoSupported
          ? 'Aprueba al menos una imagen antes de usar referencias directas.'
          : 'Elige un modelo MiniMax H3 antes de usar referencias directas.',
      })
      return
    }
    const director = useStore.getState()
    const hasDirectorWork = Boolean(
      director.directorSceneDescription.trim()
      || director.directorPlannedClips.length
      || director.directorCharacterRefs.length
      || director.directorLocationRefs.length,
    )
    const confirmed = autoStart
      ? window.confirm(
        directVideo
          ? `¿Generar el tráiler de “${project.title}” (${trailerDuration}s) como T2V puro? No se crearán ni enviarán imágenes o referencias.`
          : `¿Generar el tráiler épico completo de “${project.title}” (${trailerDuration}s)? El borrador actual de Director se sustituirá y la generación puede consumir créditos.`,
      )
      : !hasDirectorWork || window.confirm(
        '¿Abrir este tráiler en Director? El borrador actual de Director se sustituirá.',
      )
    if (!confirmed) return
    beginProjectOperation(sourceProjectId)
    const trailerOptions: TrailerAdaptationOptions = {
      format: trailerFormat,
      narration: trailerNarration,
      spoiler: trailerSpoiler,
      intensity: trailerIntensity,
      tagline: trailerTagline.trim(),
      titleCards: trailerTitleCards,
      preserveVisualStyle: trailerPreserveVisualStyle,
    }
    setProductionBusy('trailer')
    try {
      const adaptation = await loadFilmProduction(
        project,
        trailerDirection,
        autoStart,
        trailerDuration,
        trailerPreserveVisualStyle,
        filmVideoModel,
        filmImageModel,
        storyVideoResolution,
        storyVideoAspectRatio,
        trailerOptions,
      )
      updateProjectById(sourceProjectId, current => ({
        ...current,
        productions: [...current.productions, {
          id: storyId('production'),
          kind: 'trailer',
          title: `${project.title} · epic trailer`,
          createdAt: new Date().toISOString(),
          sourceVersion: project.revision,
          sourceSnapshot: { ...structuredClone(project), productions: [] },
          targetName: `${project.title} · epic trailer`,
          targetSnapshot: {
            direction: trailerDirection,
            sceneDescription: adaptation.sceneDescription,
            characters: adaptation.characters,
            targetDuration: adaptation.targetDuration,
            narrative: adaptation.narrative,
            visualStyle: adaptation.visualStyle,
            preserveVisualStyle: adaptation.preserveVisualStyle,
            trailerFormat,
            trailerNarration,
            trailerSpoiler,
            trailerIntensity,
            trailerTagline: trailerTagline.trim(),
            trailerTitleCards,
            imageModel: filmImageModel,
            videoModel: filmVideoModel,
            generationMode: project.musicVideoGenerationMode,
            resolution: storyVideoResolution,
            aspectRatio: storyVideoAspectRatio,
            pipelineId: useStore.getState().pipelineId || undefined,
          },
          status: 'staged',
        }],
      }))
      setNotice({
        kind: 'ok',
        text: directVideo
          ? autoStart
            ? 'El tráiler T2V está ejecutándose en Director sin imágenes ni referencias.'
            : 'El tráiler T2V está abierto en Director; sólo se han cargado el guion visual y el prompt maestro.'
          : autoStart
            ? 'El tráiler está ejecutándose en Director y queda recuperable en Montaje.'
            : 'El arco, canon y referencias del tráiler están cargados en Director para revisar y editar.',
      })
    } catch (error) {
      setNotice({ kind: 'error', text: `No se pudo preparar el tráiler: ${(error as Error).message}` })
    } finally {
      endProjectOperation(sourceProjectId)
      setProductionBusy(null)
    }
  }

  const writeStorySong = async () => {
    const sourceProjectId = project.id
    const activity = beginStoryActivity('writing_song', 'Story Lab is writing the song prompt and lyrics…', 1)
    setProductionBusy('music')
    try {
      const brief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds)
      const written = await api.writeSong({
        ...musicWritingProviderParams,
        target: project.music.mode === 'cover' ? 'minimax' : songWriteTarget(project.music.model),
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: brief,
        style_direction: project.music.style || `${project.genre}, ${project.tone}`,
        lyrics_direction: project.music.lyrics || project.music.sourceLyrics,
        story_context: storySongBrief(project, project.music.targetDurationSeconds),
        language: project.language,
        duration_seconds: project.music.targetDurationSeconds,
      })
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: {
          ...current.music,
          brief,
          style: written.style,
          lyrics: written.lyrics,
          lyricsLanguage: project.language,
        },
      }))
      setNotice({ kind: 'ok', text: 'Song prompt and editable lyrics are ready. Review them before spending MiniMax credits.' })
      return { brief, style: written.style, lyrics: written.lyrics }
    } catch (error) {
      activity.fail(error)
      setNotice({ kind: 'error', text: `The song draft could not be written: ${(error as Error).message}` })
      return null
    } finally {
      activity.finish()
      setProductionBusy(null)
    }
  }

  const adaptStoryLyrics = async () => {
    const sourceProjectId = project.id
    const sourceLyrics = project.music.sourceLyrics.trim()
    if (!sourceLyrics) {
      setNotice({ kind: 'error', text: 'Paste the source lyrics you are authorized to adapt first.' })
      return
    }
    const activity = beginStoryActivity('writing_song', 'Story Lab is adapting the lyrics to this story…', 1)
    setProductionBusy('music')
    try {
      const storyBrief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds)
      const written = await api.writeSong({
        ...musicWritingProviderParams,
        target: project.music.mode === 'cover' ? 'minimax' : songWriteTarget(project.music.model),
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: 'Write completely original replacement lyrics for this Story. Keep only the broad section order, approximate meter and singability of the authorized source; do not copy distinctive wording, names or lines.',
        style_direction: project.music.style || storyBrief,
        lyrics_direction: sourceLyrics,
        story_context: storySongBrief(project, project.music.targetDurationSeconds),
        language: project.language,
        duration_seconds: project.music.targetDurationSeconds,
      })
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: {
          ...current.music,
          brief: storyBrief,
          style: written.style || project.music.style,
          lyrics: written.lyrics,
          lyricsLanguage: project.language,
        },
      }))
      setNotice({ kind: 'ok', text: 'The Story lyrics were adapted and remain fully editable before generation.' })
    } catch (error) {
      activity.fail(error)
      setNotice({ kind: 'error', text: `The lyrics could not be adapted: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setProductionBusy(null)
    }
  }

  const uploadCoverReference = async (file?: File) => {
    if (!file) return
    const sourceProjectId = project.id
    if (file.size > 50 * 1024 * 1024) {
      setNotice({ kind: 'error', text: 'MiniMax Cover accepts reference audio up to 50 MB.' })
      return
    }
    const activity = beginStoryActivity('uploading_music_reference', `Uploading cover reference “${file.name}”…`, 1)
    setProductionBusy('music')
    try {
      const uploaded = await api.uploadAudio(file)
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: {
          ...current.music,
          mode: 'cover',
          coverReferenceFilename: uploaded.filename,
          coverReferenceName: file.name,
        },
      }))
      setNotice({ kind: 'ok', text: 'Cover reference uploaded. You can keep its lyrics or replace them with the editable Story lyrics.' })
    } catch (error) {
      activity.fail(error)
      setNotice({ kind: 'error', text: `The cover reference could not be uploaded: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setProductionBusy(null)
      if (musicCoverRef.current) musicCoverRef.current.value = ''
    }
  }

  const generateMinimaxSongs = async () => {
    const sourceProjectId = project.id
    if (!servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services first.' })
      return
    }
    if (project.music.mode === 'cover' && !project.music.coverReferenceFilename) {
      setNotice({ kind: 'error', text: 'Upload a reference song before generating a cover.' })
      return
    }
    const activity = beginStoryActivity(
      'generating_music',
      `Preparing ${project.music.candidateCount} MiniMax Music candidates…`,
      project.music.candidateCount,
    )
    setProductionBusy('music')
    try {
      const generationLanguage = project.music.lyricsLanguage || project.language
      const brief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds, generationLanguage)
      let style = project.music.style.trim()
      let lyrics = project.music.lyrics.trim()
      if (!style || (project.music.mode === 'original' && !lyrics)) {
        activity.update('Story Lab is writing the missing song prompt and lyrics…', 'writing_song', 0, 1)
        const written = await api.writeSong({
          ...musicWritingProviderParams,
          target: project.music.mode === 'cover' ? 'minimax' : songWriteTarget(project.music.model),
          model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
          description: brief,
          style_direction: style || `${project.genre}, ${project.tone}`,
          lyrics_direction: lyrics || project.music.sourceLyrics,
          story_context: storySongBrief(project, project.music.targetDurationSeconds, generationLanguage),
          language: generationLanguage,
          duration_seconds: project.music.targetDurationSeconds,
        })
        style = written.style
        lyrics = written.lyrics
      }
      activity.update(
        `MiniMax Music is generating ${project.music.candidateCount} candidates…`,
        'generating_music',
        0,
        project.music.candidateCount,
      )
      const result = await api.generateStoryMusicCandidates({
        prompt: style,
        lyrics,
        count: project.music.candidateCount,
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        reference_audio_filename: project.music.mode === 'cover'
          ? project.music.coverReferenceFilename : undefined,
        workspace: activeWorkspace,
      }, {
        onJobSubmitted: job => {
          activeMusicJobId.current = job.jobId
          activity.handoff(`Continuing as recoverable MiniMax Music job ${job.jobId}`)
        },
        onProgress: job => activity.update(
          job.message,
          job.phase === 'waiting_resource' ? 'waiting_resource' : 'generating_music',
          job.current,
          job.total,
        ),
      })
      const createdAt = new Date().toISOString()
      const language = generationLanguage
      const firstVersion = nextMusicCandidateVersion(project.music.candidates, language, project.music.lyricsLanguage || project.language)
      const candidates = result.candidates.map((candidate, index) => ({
        id: storyId('song'),
        displayName: `${project.title || 'Story song'} · ${language} · v${firstVersion + index}`,
        title: project.title || 'Story song',
        language,
        version: firstVersion + index,
        name: candidate.filename,
        source: candidate.source,
        prompt: style,
        lyrics,
        provider: 'minimax' as const,
        model: candidate.model,
        durationSeconds: candidate.duration_seconds,
        createdAt,
        taskId: candidate.taskId || candidate.task_id,
        rootTaskId: candidate.rootTaskId || candidate.root_task_id,
      }))
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: {
          ...current.music,
          brief,
          style,
          lyrics,
          lyricsLanguage: project.music.lyricsLanguage || project.language,
          candidates: [...current.music.candidates, ...candidates],
          selectedCandidateId: candidates[0]?.id || current.music.selectedCandidateId,
        },
      }))
      setNotice({
        kind: result.status === 'completed' ? 'ok' : 'error',
        text: result.status === 'completed'
          ? `${candidates.length} MiniMax Music candidates generated. Listen and choose one for the musical trailer.`
          : `${result.message}. ${candidates.length} completed candidate(s) were preserved.`,
      })
    } catch (error) {
      activity.fail(error, 'generating_music')
      setNotice({ kind: 'error', text: `MiniMax Music could not generate the candidates: ${(error as Error).message}` })
    } finally {
      activeMusicJobId.current = ''
      activity.finish()
      setProductionBusy(null)
    }
  }

  const patchMusicCue = (
    cueId: string,
    changes: Partial<StoryMusicCue>,
    projectId = useStoryStore.getState().project.id,
  ) => {
    updateProjectById(projectId, current => {
      const cue = current.music.cues.find(item => item.id === cueId)
      if (cue) Object.assign(cue, changes)
      return current
    })
  }

  const translateMusicCueLyrics = async (cueId: string) => {
    const sourceProjectId = project.id
    const cue = useStoryStore.getState().projects[sourceProjectId]?.music.cues.find(item => item.id === cueId)
    const targetLanguage = (lyricsTranslationLanguage[cueId] || '').trim()
    if (!cue?.lyrics.trim()) return
    if (!targetLanguage) {
      setNotice({ kind: 'error', text: 'Write the target language before translating the lyrics.' })
      return
    }
    const activity = beginStoryActivity('writing_song', `Translating “${cue.title}” into ${targetLanguage}…`, 1)
    setMusicCueBusy(`translate:${cueId}`)
    try {
      const translated = await api.translateStoryLyrics({
        lyrics: cue.lyrics,
        targetLanguage,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
      })
      updateProjectById(sourceProjectId, current => {
        const target = current.music.cues.find(item => item.id === cueId)
        if (target) Object.assign(target, { lyrics: translated.lyrics, lyricsLanguage: translated.targetLanguage })
        return current
      })
      setNotice({ kind: 'ok', text: `“${cue.title}” lyrics were translated into ${translated.targetLanguage}. Review them before generating audio.` })
    } catch (error) {
      activity.fail(error, 'writing_song')
      setNotice({ kind: 'error', text: `Lyrics could not be translated: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setMusicCueBusy('')
    }
  }

  const translateManualSongLyrics = async () => {
    const sourceProjectId = project.id
    const lyrics = project.music.lyrics.trim()
    const targetLanguage = (lyricsTranslationLanguage.manual || '').trim()
    if (!lyrics) return
    if (!targetLanguage) {
      setNotice({ kind: 'error', text: 'Write the target language before translating the lyrics.' })
      return
    }
    const activity = beginStoryActivity('writing_song', `Translating the manual song into ${targetLanguage}…`, 1)
    setProductionBusy('music')
    try {
      const translated = await api.translateStoryLyrics({
        lyrics,
        targetLanguage,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
      })
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: { ...current.music, lyrics: translated.lyrics, lyricsLanguage: translated.targetLanguage },
      }))
      setNotice({ kind: 'ok', text: `Manual song lyrics were translated into ${translated.targetLanguage}. Review them before generating audio.` })
    } catch (error) {
      activity.fail(error, 'writing_song')
      setNotice({ kind: 'error', text: `Lyrics could not be translated: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setProductionBusy(null)
    }
  }

  const rewriteMusicCueDraft = async (
    cue: StoryMusicCue,
    requestedStyle: string,
    requestedLanguage: string,
    projectId = useStoryStore.getState().project.id,
  ) => {
    const latest = useStoryStore.getState().projects[projectId]
    if (!latest) throw new Error('The source Story is no longer available.')
    const targetLanguage = requestedLanguage.trim() || cue.lyricsLanguage || latest.language
    const targetStyle = requestedStyle.trim() || cue.style || cue.brief
    const target = cue.kind === 'character'
      ? latest.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
      : cue.kind === 'world' ? 'the Story world' : 'the complete Story'
    return api.writeSong({
      writingProvider: latest.provider.writingProvider,
      writingModel: latest.provider.writingModel,
      writingBaseUrl: latest.provider.writingBaseUrl,
      target: latest.music.mode === 'cover' ? 'minimax' : songWriteTarget(latest.music.model),
      model: latest.music.model,
      instrumental: cue.instrumental,
      description: [
        `Create a completely new ${cue.instrumental ? 'instrumental composition' : 'song version'} for ${target}.`,
        `Its Story purpose remains: ${cue.purpose}.`,
        'This must be a full recomposition, not a light edit: rebuild genre, arrangement, instrumentation, vocal delivery, rhythm and production around the requested style.',
        cue.instrumental
          ? 'Preserve the narrative role and emotional arc, but do not preserve the old arrangement.'
          : 'Rewrite every sung line from scratch while preserving the Story facts, emotional arc and a memorable recurring hook. Do not merely translate or paraphrase the old wording.',
      ].join(' '),
      style_direction: targetStyle,
      lyrics_direction: cue.instrumental ? '' : [
        `Write entirely new structured lyrics in ${targetLanguage}, using MiniMax section tags in English.`,
        'The previous lyrics below are narrative source material only; do not copy their lines:',
        cue.lyrics,
      ].join('\n\n'),
      story_context: storySongBrief(latest, cue.durationSeconds, targetLanguage),
      language: targetLanguage,
      duration_seconds: cue.durationSeconds,
      max_new_tokens: 1600,
    }).then(written => ({
      style: written.style,
      lyrics: written.lyrics,
      lyricsLanguage: targetLanguage,
      lyriaPrompt: written.lyria_prompt,
      brief: requestedStyle.trim() || cue.brief,
    }))
  }

  const createNewMusicVideoSong = async (generateAudio: boolean) => {
    const current = useStoryStore.getState().project
    if (current.projectType !== 'music_video') return
    if (!musicWritingReady) {
      setNotice({ kind: 'error', text: 'Configure the selected Story Lab writing model before creating a new song.' })
      return
    }
    if (generateAudio && !servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services before generating the new song.' })
      return
    }
    const existingCue = current.music.cues.find(cue => cue.kind === 'story') || current.music.cues[0]
    const cue: StoryMusicCue = existingCue || {
      id: storyId('music-cue'),
      kind: 'story',
      targetId: current.id,
      title: current.title.trim() ? `${current.title} · canción` : 'Nueva canción',
      purpose: current.creativeBrief.songStory || current.music.brief || 'Tell this Story as a memorable song.',
      referenceSong: '',
      brief: current.music.brief || storySongBrief(current, current.music.targetDurationSeconds),
      style: '',
      lyrics: '',
      lyricsLanguage: current.language,
      lyriaPrompt: '',
      instrumental: false,
      durationSeconds: current.music.targetDurationSeconds,
      candidates: [],
    }
    const total = generateAudio ? 2 : 1
    const activity = beginStoryActivity(
      'writing_song',
      generateAudio
        ? 'Creating fresh prompts before generating the new song…'
        : 'Creating prompts for a completely new song…',
      total,
    )
    setNewSongAction(generateAudio ? 'audio' : 'prompts')
    setMusicCueBusy(`new-song:${cue.id}`)
    setNotice(null)
    try {
      const rewritten = await rewriteMusicCueDraft(cue, instruction, '', current.id)
      if (existingCue) {
        patchMusicCue(cue.id, rewritten, current.id)
      } else {
        updateProjectById(current.id, latest => {
          latest.music.cues.unshift({ ...cue, ...rewritten })
          return latest
        })
      }
      setInstruction('')
      activity.update(
        generateAudio
          ? 'New prompts saved. MiniMax Music is generating the new song…'
          : 'New song prompts saved without generating audio.',
        generateAudio ? 'generating_music' : 'writing_song',
        1,
        total,
      )
      if (generateAudio) {
        const ready = await generateMusicCueAudio(cue.id, true, jobId => activity.handoff(
          `Continuing as recoverable MiniMax Music job ${jobId}`,
        ))
        if (!ready) {
          activity.fail(new Error('MiniMax Music did not complete the new song.'), 'generating_music')
          return
        }
        activity.update('The new song and its fresh prompts are ready.', 'generating_music', 2, 2)
        setNotice({ kind: 'ok', text: `A new version of “${cue.title}” was written and generated. Previous audio remains available.` })
      } else {
        setNotice({ kind: 'ok', text: `Fresh prompts and lyrics for “${cue.title}” are ready. No MiniMax music credits were used and previous audio remains available.` })
      }
    } catch (error) {
      activity.fail(error, generateAudio ? 'generating_music' : 'writing_song')
      setNotice({
        kind: 'error',
        text: `The new song could not be prepared: ${(error as Error).message}`,
      })
    } finally {
      activity.finish()
      setMusicCueBusy('')
      setNewSongAction(null)
    }
  }

  const createMusicCueVersion = async (cueId: string) => {
    const sourceProjectId = project.id
    const cue = useStoryStore.getState().projects[sourceProjectId]?.music.cues.find(item => item.id === cueId)
    if (!cue) return
    const requestedStyle = (musicVersionStyle[cueId] || '').trim()
    const requestedLanguage = (musicVersionLanguage[cueId] || '').trim()
    if (!requestedStyle && !requestedLanguage) {
      setNotice({ kind: 'error', text: 'Write a new style, a new language, or both before creating the version.' })
      return
    }
    const changeLabel = [requestedStyle, requestedLanguage].filter(Boolean).join(' · ')
    const activity = beginStoryActivity('writing_song', `Creating a new version of “${cue.title}” · ${changeLabel}…`, 1)
    setMusicCueBusy(`version:${cueId}`)
    try {
      const rewritten = await rewriteMusicCueDraft(cue, requestedStyle, requestedLanguage, sourceProjectId)
      patchMusicCue(cueId, rewritten, sourceProjectId)
      setNotice({
        kind: 'ok',
        text: `A completely new “${cue.title}” draft is ready in ${rewritten.lyricsLanguage}. Existing generated audio was preserved. Review the prompts before generating it.`,
      })
    } catch (error) {
      activity.fail(error, 'writing_song')
      setNotice({ kind: 'error', text: `The new song version could not be written: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setMusicCueBusy('')
    }
  }

  const createAllMusicCueVersions = async () => {
    const sourceProjectId = project.id
    const cues = useStoryStore.getState().projects[sourceProjectId]?.music.cues || []
    const requestedStyle = (musicVersionStyle.all || '').trim()
    const requestedLanguage = (musicVersionLanguage.all || '').trim()
    if (!cues.length) {
      setNotice({ kind: 'error', text: 'Generate the music proposals before creating alternate versions.' })
      return
    }
    if (!requestedStyle && !requestedLanguage) {
      setNotice({ kind: 'error', text: 'Write a global style, a global language, or both.' })
      return
    }
    if (!window.confirm(
      `Rewrite all ${cues.length} music proposals sequentially? This makes ${cues.length} LLM call${cues.length === 1 ? '' : 's'}, but does not generate paid MiniMax audio. Existing audio candidates will remain available.`,
    )) return
    const activity = beginStoryActivity('writing_song', `Preparing alternate music drafts · 0/${cues.length}`, cues.length)
    setMusicCueBusy('version:all')
    let completed = 0
    try {
      for (let index = 0; index < cues.length; index += 1) {
        const currentCue = useStoryStore.getState().projects[sourceProjectId]?.music.cues.find(item => item.id === cues[index].id)
        if (!currentCue) continue
        activity.update(`Rewriting “${currentCue.title}” · ${index + 1}/${cues.length}`, 'writing_song', index, cues.length)
        const rewritten = await rewriteMusicCueDraft(currentCue, requestedStyle, requestedLanguage, sourceProjectId)
        patchMusicCue(currentCue.id, rewritten, sourceProjectId)
        completed += 1
        activity.update(`Completed “${currentCue.title}” · ${completed}/${cues.length}`, 'writing_song', completed, cues.length)
      }
      setNotice({
        kind: 'ok',
        text: `${completed} alternate music drafts are ready. Existing audio was preserved; review each new prompt before generating tracks.`,
      })
    } catch (error) {
      activity.fail(error, 'writing_song')
      setNotice({
        kind: 'error',
        text: `Bulk versioning stopped after ${completed}/${cues.length}. Completed drafts were preserved: ${(error as Error).message}`,
      })
    } finally {
      activity.finish()
      setMusicCueBusy('')
    }
  }

  const createManualSongVersion = async () => {
    const sourceProjectId = project.id
    const requestedStyle = (musicVersionStyle.manual || '').trim()
    const requestedLanguage = (musicVersionLanguage.manual || '').trim()
    if (!requestedStyle && !requestedLanguage) {
      setNotice({ kind: 'error', text: 'Write a new style, a new language, or both before creating the manual version.' })
      return
    }
    const targetLanguage = requestedLanguage || project.music.lyricsLanguage || project.language
    const activity = beginStoryActivity('writing_song', `Creating a new manual song version in ${targetLanguage}…`, 1)
    setProductionBusy('music')
    try {
      const written = await api.writeSong({
        ...musicWritingProviderParams,
        target: project.music.mode === 'cover' ? 'minimax' : songWriteTarget(project.music.model),
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: 'Create a complete new version of this Story song. Recompose the arrangement and rewrite every lyric line from scratch; preserve only its Story meaning and emotional progression.',
        style_direction: requestedStyle || project.music.style || `${project.genre}, ${project.tone}`,
        lyrics_direction: `Write entirely new lyrics in ${targetLanguage}. Treat these previous lyrics only as narrative source material and do not copy their lines:\n\n${project.music.lyrics}`,
        story_context: storySongBrief(project, project.music.targetDurationSeconds, targetLanguage),
        language: targetLanguage,
        duration_seconds: project.music.targetDurationSeconds,
      })
      updateProjectById(sourceProjectId, current => ({
        ...current,
        music: {
          ...current.music,
          style: written.style,
          lyrics: written.lyrics,
          lyricsLanguage: targetLanguage,
        },
      }))
      setNotice({ kind: 'ok', text: `The manual ${requestedStyle || 'alternate'} version is ready in ${targetLanguage}. Existing audio candidates were preserved.` })
    } catch (error) {
      activity.fail(error, 'writing_song')
      setNotice({ kind: 'error', text: `The manual song version could not be written: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setProductionBusy(null)
    }
  }

  const adaptMusicCueWithLlm = async (cueId: string, includeLyria = false) => {
    const sourceProjectId = project.id
    const cue = useStoryStore.getState().projects[sourceProjectId]?.music.cues.find(item => item.id === cueId)
    if (!cue) return
    const activity = beginStoryActivity('music_planning', `Story Lab is adapting “${cue.title}”…`, 1)
    setMusicCueBusy(`llm:${cueId}`)
    try {
      const lyricsLanguage = cue.lyricsLanguage || project.language
      const target = cue.kind === 'character'
        ? project.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
        : cue.kind === 'world' ? 'the Story world' : 'the complete Story'
      const written = await api.writeSong({
        ...musicWritingProviderParams,
        target: project.music.mode === 'cover' ? 'minimax' : songWriteTarget(project.music.model),
        model: project.music.model,
        instrumental: cue.instrumental,
        description: `Create an entirely original ${cue.instrumental ? 'instrumental music cue' : 'song'} for ${target}. Purpose in this Story: ${cue.purpose}.`,
        reference_song: cue.referenceSong,
        style_direction: cue.brief,
        lyrics_direction: cue.lyrics,
        story_context: storySongBrief(useStoryStore.getState().projects[sourceProjectId] || project, cue.durationSeconds, lyricsLanguage),
        language: lyricsLanguage,
        duration_seconds: cue.durationSeconds,
        include_lyria: includeLyria,
        max_new_tokens: includeLyria ? 3000 : 1600,
      })
      patchMusicCue(cueId, {
        style: written.style,
        lyrics: written.lyrics,
        lyricsLanguage,
        ...(includeLyria ? { lyriaPrompt: written.lyria_prompt } : {}),
      }, sourceProjectId)
      const lyriaMissing = includeLyria && !written.lyria_prompt.trim()
      setNotice({
        kind: 'ok',
        text: lyriaMissing
          ? `“${cue.title}” has a valid MiniMax prompt${cue.instrumental ? '' : ' and structured lyrics'}. The optional Lyria prompt was omitted, but nothing was discarded.`
          : includeLyria
            ? `“${cue.title}” now has editable MiniMax and Google Lyria prompts${cue.instrumental ? '' : ' with structured lyrics'}.`
            : `“${cue.title}” now has an editable MiniMax prompt${cue.instrumental ? '' : ' with structured lyrics'}. Lyria was not requested.`,
      })
    } catch (error) {
      activity.fail(error, 'music_planning')
      setNotice({ kind: 'error', text: `The music proposal could not be adapted: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setMusicCueBusy('')
    }
  }

  const uploadLyriaResult = async (file?: File) => {
    const cueId = lyriaUploadCueId.current
    if (!file || !cueId) return
    const sourceProjectId = project.id
    const cue = useStoryStore.getState().projects[sourceProjectId]?.music.cues.find(item => item.id === cueId)
    if (!cue) return
    const activity = beginStoryActivity('uploading_music', `Importing Google Lyria result “${file.name}”…`, 1)
    setMusicCueBusy(`lyria-upload:${cueId}`)
    try {
      const uploaded = await api.uploadAudio(file)
      const language = cue.lyricsLanguage || project.language
      const version = nextMusicCandidateVersion(cue.candidates, language, project.language)
      const candidate = {
        id: storyId('song'),
        displayName: `${cue.title} · ${language} · v${version}`,
        title: cue.title,
        language,
        version,
        name: file.name || uploaded.filename,
        source: uploaded.url,
        prompt: cue.lyriaPrompt,
        lyrics: cue.lyrics,
        provider: 'lyria' as const,
        model: 'lyria-3-pro-preview',
        durationSeconds: 0,
        createdAt: new Date().toISOString(),
      }
      updateProjectById(sourceProjectId, current => {
        const target = current.music.cues.find(item => item.id === cueId)
        if (target) {
          target.candidates.push(candidate)
          target.selectedCandidateId = candidate.id
        }
        return current
      })
      setNotice({ kind: 'ok', text: `Google Lyria result imported under “${cue.title}”.` })
    } catch (error) {
      activity.fail(error, 'uploading_music')
      setNotice({ kind: 'error', text: `The Lyria result could not be imported: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setMusicCueBusy('')
      lyriaUploadCueId.current = ''
      if (lyriaUploadRef.current) lyriaUploadRef.current.value = ''
    }
  }

  const uploadCustomMusic = async (file?: File) => {
    if (!file) return
    const cueId = customMusicUploadCueId.current
    const sourceProjectId = project.id
    const current = useStoryStore.getState().projects[sourceProjectId]
    if (!current) return
    const cue = current.music.cues.find(item => item.id === cueId)
    const destination = cue?.title || current.title || 'Story music'
    const activity = beginStoryActivity('uploading_music', `Importing custom audio “${file.name}”…`, 1)
    setMusicCueBusy(`custom-upload:${cueId || 'story'}`)
    try {
      const uploaded = await api.uploadAudio(file)
      const language = cue?.lyricsLanguage || current.music.lyricsLanguage || current.language
      const existing = cue?.candidates || current.music.candidates
      const version = nextMusicCandidateVersion(existing, language, current.language)
      const candidate: StoryMusicCandidate = {
        id: storyId('song'),
        displayName: `${destination} · custom MP3 · v${version}`,
        title: destination,
        language,
        version,
        name: file.name || uploaded.filename,
        source: uploaded.url,
        prompt: cue?.style || current.music.style,
        lyrics: cue?.lyrics || current.music.lyrics,
        provider: 'local',
        model: 'custom-audio-upload',
        durationSeconds: 0,
        createdAt: new Date().toISOString(),
      }
      updateProjectById(sourceProjectId, latest => {
        const target = latest.music.cues.find(item => item.id === cueId)
        if (target) {
          target.candidates.push(candidate)
          target.selectedCandidateId = candidate.id
        } else {
          latest.music.candidates.push(candidate)
          latest.music.selectedCandidateId = candidate.id
        }
        return latest
      })
      setMusicProductionCandidateId(candidate.id)
      setNotice({ kind: 'ok', text: `Custom audio imported and selected under “${destination}”.` })
    } catch (error) {
      activity.fail(error, 'uploading_music')
      setNotice({ kind: 'error', text: `The custom audio could not be imported: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setMusicCueBusy('')
      customMusicUploadCueId.current = ''
      if (customMusicUploadRef.current) customMusicUploadRef.current.value = ''
    }
  }

  const generateMusicCueAudio = async (
    cueId: string,
    queued = false,
    onJobSubmitted?: (jobId: string) => void,
  ): Promise<boolean> => {
    if (!isAceStepMusicModel(useStoryStore.getState().projects[project.id]?.music.model) && !servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services first, or switch the song model to ACE-Step.' })
      return false
    }
    const sourceProjectId = project.id
    const current = useStoryStore.getState().projects[sourceProjectId]
    if (!current) return false
    const cue = current.music.cues.find(item => item.id === cueId)
    if (!cue) return false
    if (!cue.style.trim() || (!cue.instrumental && !cue.lyrics.trim())) {
      setNotice({ kind: 'error', text: `Review or adapt the prompt${cue.instrumental ? '' : ' and lyrics'} for “${cue.title}” first.` })
      return false
    }
    if (!cue.instrumental && !MINIMAX_LYRIC_SECTION.test(cue.lyrics)) {
      setNotice({
        kind: 'error',
        text: `“${cue.title}” needs [Verse], [Chorus] or another supported section tag before generation. Adapt it with the LLM or edit the lyrics first.`,
      })
      return false
    }
    const usingAceStep = isAceStepMusicModel(current.music.model)
    const activity = queued
      ? null
      : beginStoryActivity('generating_music', `${usingAceStep ? 'ACE-Step' : 'MiniMax Music'} is generating “${cue.title}”…`, 1)
    setMusicCueBusy(`audio:${cueId}`)
    try {
      if (usingAceStep) {
        const prompt = cue.style.trim()
        const rendered = await api.generateMusic({
          style: prompt,
          lyrics: cue.instrumental ? '[Instrumental]' : cue.lyrics,
          instrumental: cue.instrumental,
          duration_seconds: current.music.targetDurationSeconds,
          model_type: ACE_STEP_MUSIC_MODEL,
          workspace: activeWorkspace,
          initiator: `Story Lab · ${current.projectType === 'music_video' ? 'Videoclip' : 'Story song'}`,
        })
        const createdAt = new Date().toISOString()
        const language = cue.lyricsLanguage || current.language
        const firstVersion = nextMusicCandidateVersion(cue.candidates, language, current.language)
        const candidates = [{
          id: storyId('song'),
          displayName: `${cue.title} · ${language} · v${firstVersion}`,
          title: cue.title,
          language,
          version: firstVersion,
          name: rendered.filename,
          source: api.getFileUrl(rendered.filename, activeWorkspace),
          prompt,
          lyrics: cue.lyrics,
          provider: 'local' as const,
          model: ACE_STEP_MUSIC_MODEL,
          durationSeconds: current.music.targetDurationSeconds,
          createdAt,
        }]
        updateProjectById(sourceProjectId, latest => {
          const target = latest.music.cues.find(item => item.id === cueId)
          if (!target) return latest
          return {
            ...latest,
            music: {
              ...latest.music,
              cues: latest.music.cues.map(item => item.id === cueId ? {
                ...item,
                candidates: [...item.candidates, ...candidates],
                selectedCandidateId: candidates[0]?.id || item.selectedCandidateId,
              } : item),
            },
          }
        })
        setNotice({ kind: 'ok', text: `ACE-Step generated “${cue.title}”.` })
        return true
      }
      const prompt = cue.style.trim().slice(0, 300)
      const result = await api.generateStoryMusicCandidates({
        prompt,
        lyrics: cue.instrumental ? '' : cue.lyrics,
        instrumental: cue.instrumental,
        count: 1,
        model: current.music.model,
        workspace: activeWorkspace,
      }, {
        onJobSubmitted: job => {
          activeMusicJobId.current = job.jobId
          activity?.handoff(`Continuing as recoverable MiniMax Music job ${job.jobId}`)
          onJobSubmitted?.(job.jobId)
        },
        onProgress: job => activity?.update(
          job.message,
          job.phase === 'waiting_resource' ? 'waiting_resource' : 'generating_music',
          job.current,
          job.total,
        ),
      })
      const createdAt = new Date().toISOString()
      const language = cue.lyricsLanguage || current.language
      const firstVersion = nextMusicCandidateVersion(cue.candidates, language, current.language)
      const candidates = result.candidates.map((candidate, index) => ({
        id: storyId('song'),
        displayName: `${cue.title} · ${language} · v${firstVersion + index}`,
        title: cue.title,
        language,
        version: firstVersion + index,
        name: candidate.filename,
        source: candidate.source,
        prompt,
        lyrics: cue.lyrics,
        provider: 'minimax' as const,
        model: candidate.model,
        durationSeconds: candidate.duration_seconds,
        createdAt,
        taskId: candidate.taskId || candidate.task_id,
        rootTaskId: candidate.rootTaskId || candidate.root_task_id,
      }))
      updateProjectById(sourceProjectId, latest => {
        const target = latest.music.cues.find(item => item.id === cueId)
        if (target) {
          target.candidates.push(...candidates)
          target.selectedCandidateId = candidates[0]?.id || target.selectedCandidateId
        }
        return latest
      })
      if (!queued) {
        setNotice({
          kind: result.status === 'completed' ? 'ok' : 'error',
          text: result.status === 'completed'
            ? `MiniMax generated “${cue.title}”. The result is saved under this proposal.`
            : `${result.message}. Any completed audio was saved under “${cue.title}”.`,
        })
      }
      return result.status === 'completed' || result.status === 'cancelled'
    } catch (error) {
      activity?.fail(error, 'generating_music')
      setNotice({ kind: 'error', text: `“${cue.title}” could not be generated: ${(error as Error).message}` })
      return false
    } finally {
      activeMusicJobId.current = ''
      activity?.finish()
      if (!queued) setMusicCueBusy('')
    }
  }

  const generateAllMusicCues = async () => {
    const cues = useStoryStore.getState().project.music.cues
    if (!cues.length) {
      setNotice({ kind: 'error', text: 'Generate and review the LLM music proposals first.' })
      return
    }
    const incomplete = cues.filter(cue => !cue.style.trim() || (!cue.instrumental && !cue.lyrics.trim()))
    if (incomplete.length) {
      setNotice({ kind: 'error', text: `Review ${incomplete.length} incomplete music proposal${incomplete.length === 1 ? '' : 's'} before generating the complete queue.` })
      return
    }
    if (!servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services first.' })
      return
    }
    if (!window.confirm(
      `Generate ${cues.length} MiniMax track${cues.length === 1 ? '' : 's'} sequentially? This consumes one paid music request per proposal.`,
    )) return
    const ids = cues.map(cue => cue.id)
    const activity = beginStoryActivity(
      'music_queue',
      `MiniMax Music queue ready: 0/${ids.length} tracks generated`,
      ids.length,
    )
    musicQueueCancelRequested.current = false
    setMusicQueue({ ids, index: 0 })
    let completed = 0
    try {
      for (let index = 0; index < ids.length; index += 1) {
        if (musicQueueCancelRequested.current) break
        setMusicQueue({ ids, index })
        const cue = useStoryStore.getState().project.music.cues.find(item => item.id === ids[index])
        activity.update(
          `Generating “${cue?.title || `track ${index + 1}`}” · ${index + 1}/${ids.length}`,
          'music_queue',
          index,
          ids.length,
        )
        const ready = await generateMusicCueAudio(ids[index], true, jobId => activity.handoff(
          `Continuing as recoverable MiniMax Music job ${jobId}`,
        ))
        if (!ready) break
        completed += 1
        activity.update(
          `Completed “${cue?.title || `track ${index + 1}`}” · ${completed}/${ids.length}`,
          'music_queue',
          completed,
          ids.length,
        )
        if (musicQueueCancelRequested.current) break
      }
      if (musicQueueCancelRequested.current) {
        setNotice({ kind: 'ok', text: `Music queue cancelled after ${completed}/${ids.length}; completed tracks were preserved.` })
      } else if (completed === ids.length) {
        setNotice({ kind: 'ok', text: `Music queue completed: ${completed} tracks generated one after another.` })
      } else {
        activity.fail(new Error(`Music queue stopped after ${completed}/${ids.length}`), 'music_queue')
        setNotice(current => current?.kind === 'error' ? current : {
          kind: 'error', text: `Music queue stopped after ${completed}/${ids.length}; completed tracks were preserved.`,
        })
      }
    } finally {
      activity.finish()
      musicQueueCancelRequested.current = false
      setMusicCueBusy('')
      setMusicQueue(null)
    }
  }

  const cancelMusicQueue = () => {
    musicQueueCancelRequested.current = true
    setMusicQueue(current => current ? { ...current, cancelling: true } : current)
    const jobId = activeMusicJobId.current
    if (jobId) {
      void api.cancelStoryMusicCandidatesJob(jobId).catch(error => {
        setNotice({ kind: 'error', text: `Could not request MiniMax cancellation: ${(error as Error).message}` })
      })
    }
    setNotice({ kind: 'ok', text: jobId
      ? 'Cancellation sent to the active MiniMax request; waiting for its safe boundary…'
      : 'Music queue cancellation requested before the next track starts.' })
  }

  const musicCueForCandidate = (source: StoryProject, candidateId?: string) =>
    source.music.cues.find(item => item.candidates.some(candidate => candidate.id === candidateId))

  const musicCandidateById = (source: StoryProject, candidateId?: string) => {
    const cue = musicCueForCandidate(source, candidateId)
    return source.music.candidates.find(item => item.id === candidateId)
      || cue?.candidates.find(item => item.id === candidateId)
  }

  const effectiveMusicCue = (
    source: StoryProject,
    cue: StoryMusicCue | undefined,
    candidate: StoryMusicCandidate,
  ): StoryMusicCue => cue || {
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

  const loadMusicVideoProduction = async (
    source: StoryProject,
    cue: StoryMusicCue | undefined,
    candidate: StoryMusicCandidate,
    autoStart = false,
    pacing: 'cinematic' | 'balanced' | 'rhythmic' = 'balanced',
    excerpt?: { start: number; end: number },
    generationSettings: MusicVideoGenerationSettings = {
      imageModel: filmImageModel,
      videoModel: filmVideoModel,
      resolution: storyVideoResolution,
      aspectRatio: storyVideoAspectRatio,
      generationMode: source.musicVideoGenerationMode,
      directVideoMasterPrompt: source.directVideoMasterPrompt,
      writingProvider: source.provider.writingProvider,
      writingModel: source.provider.writingModel,
      writingBaseUrl: source.provider.writingBaseUrl,
    },
    onDirectorHandoff?: () => void,
  ) => {
    const resolvedCue = effectiveMusicCue(source, cue, candidate)
    const directVideo = generationSettings.generationMode === 'direct_video'
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
    const store = useStore.getState()
    store.setGenerationMode('video')
    if (!directVideo && !directReferences && generationSettings.imageModel) {
      store.selectDirectorImageModel(generationSettings.imageModel)
    }
    if (generationSettings.videoModel) {
      await store.selectDirectorVideoModel(generationSettings.videoModel)
      const selected = useStore.getState().selectedModelPerMode.video
      if (selected !== generationSettings.videoModel) {
        throw new Error(
          `Video model selection did not settle: requested ${generationSettings.videoModel}, effective ${selected || 'none'}.`,
        )
      }
    }
    store.setDirectorResolution(generationSettings.resolution)
    store.setDirectorAspectRatio(generationSettings.aspectRatio)
    store.setSidebarMode('director')
    store.setDirectorSkill('music_video')
    store.setDirectorAutoMode(autoStart)
    store.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
    if (generationSettings.videoModel.startsWith('minimax_h3') && !directVideo) {
      store.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
    }
    store.setDirectorMusicVideoTreatment({
      // Director already has a model-aware direct-reference policy. Keep its
      // normal visual planner but skip generated shot images and feed the
      // approved Story references straight into H3 Ref2VA.
      generation_mode: directVideo ? 'direct_video' : 'image_guided',
      direct_video_master_prompt: generationSettings.directVideoMasterPrompt,
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
      directorSongDuration: excerpt ? excerpt.end - excerpt.start : resolvedCue.durationSeconds,
      directorPacingProfile: pacing,
      directorStep: 'upload',
      directorWritingProvider: generationSettings.writingProvider,
      directorWritingModel: generationSettings.writingModel,
      directorWritingBaseUrl: generationSettings.writingBaseUrl,
    })

    for (const reference of directVideo ? [] : adaptation.characterReferences) {
      const asset = source.assets[reference.assetId]
      if (!asset) continue
      try {
        const blob = await fetch(asset.source).then(response => {
          if (!response.ok) throw new Error('Character reference unavailable')
          return response.blob()
        })
        store.directorAddCharacterRef(new File(
          [blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' },
        ))
        const index = useStore.getState().directorCharacterRefs.length - 1
        useStore.getState().directorSetCharacterRefLabel(index, reference.label)
      } catch { /* The written identity remains available in the visual brief. */ }
    }
    for (const reference of directVideo ? [] : adaptation.locationReferences) {
      const asset = source.assets[reference.assetId]
      if (!asset) continue
      try {
        const blob = await fetch(asset.source).then(response => {
          if (!response.ok) throw new Error('Location reference unavailable')
          return response.blob()
        })
        store.directorAddLocationRef(new File(
          [blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' },
        ))
        const index = useStore.getState().directorLocationRefs.length - 1
        useStore.getState().directorSetLocationRefLabel(index, reference.label)
      } catch { /* The written world bible remains available in the visual brief. */ }
    }

    window.dispatchEvent(new Event('maestro:director-open'))
    const blob = await fetch(api.getPlayableFileUrl(candidate.source, candidate.name, activeWorkspace)).then(response => {
      if (!response.ok) throw new Error('The selected song file is unavailable')
      return response.blob()
    })
    onDirectorHandoff?.()
    await useStore.getState().directorUploadAndAnalyze(new File(
      [blob], candidate.name, { type: blob.type || 'audio/mpeg' },
    ), {
      lyricsHint: resolvedCue.lyrics || undefined,
      trimStart: excerpt?.start,
      trimEnd: excerpt?.end,
    })
    if (autoStart && useStore.getState().directorStep === 'structure') {
      useStore.getState().directorConfirmStructure()
      await useStore.getState().startDirectorPipeline()
      if (!useStore.getState().pipelineId) {
        throw new Error('Director did not return a pipeline ID; video generation was not started.')
      }
    }
    return { adaptation, resolvedCue, pipelineId: useStore.getState().pipelineId, generationSettings }
  }

  const openMusicalTrailer = async (
    candidateId?: string,
    options: {
      autoStart?: boolean
      saveProduction?: boolean
      pacing?: 'cinematic' | 'balanced' | 'rhythmic'
      mode?: 'full' | 'trailer'
      excerpt?: { start: number; end: number }
    } = {},
  ) => {
    const sourceProjectId = project.id
    if (!storyVideoConfigurationReady) {
      setNotice({
        kind: 'error',
        text: legacyVideoOverridePending
          ? 'Restoring this legacy Story’s previous video model and format. Try again in a moment.'
          : 'Checking the selected video model’s supported formats. Try again in a moment.',
      })
      return
    }
    const cue = musicCueForCandidate(project, candidateId)
    const candidate = musicCandidateById(project, candidateId)
    if (!candidate) {
      const director = useStore.getState()
      director.directorReset()
      director.setGenerationMode('video')
      if (filmVideoModel) {
        await director.selectDirectorVideoModel(filmVideoModel)
        const selected = useStore.getState().selectedModelPerMode.video
        if (selected !== filmVideoModel) {
          setNotice({
            kind: 'error',
            text: `Director could not apply this Story’s video model: requested ${filmVideoModel}, effective ${selected || 'none'}.`,
          })
          return
        }
      }
      director.setDirectorResolution(storyVideoResolution)
      director.setDirectorAspectRatio(storyVideoAspectRatio)
      director.setSidebarMode('director')
      director.setDirectorSkill('music_video')
      director.setDirectorAutoMode(false)
      director.setDirectorShotImageGuidance(project.musicVideoGenerationMode === 'direct_video' || project.musicVideoGenerationMode === 'direct_references' ? 'prompt_only' : 'auto')
      if (filmVideoModel.startsWith('minimax_h3') && project.musicVideoGenerationMode !== 'direct_video') {
        director.setDirectorH3ReferenceMode(project.musicVideoGenerationMode === 'direct_references' ? 'references' : 'first_frame')
      }
      director.setDirectorMusicVideoTreatment({
        generation_mode: project.musicVideoGenerationMode === 'direct_video' ? 'direct_video' : 'image_guided',
        direct_video_master_prompt: project.directVideoMasterPrompt,
      })
      useStore.setState({ directorMusicSource: 'generate', directorStep: 'upload' })
      window.dispatchEvent(new Event('maestro:director-open'))
      return
    }
    setProductionBusy('music')
    const activity = beginStoryActivity(
      'preparing_music_video',
      directMusicVideo
        ? `Loading “${candidate.displayName || candidate.title || candidate.name}” for direct text-to-video…`
        : directReferenceVideo
          ? `Loading “${candidate.displayName || candidate.title || candidate.name}” with approved references for H3 Ref2VA…`
        : `Loading “${candidate.displayName || candidate.title || candidate.name}” and its Story references…`,
      3,
    )
    try {
      activity.update(
        directMusicVideo
          ? 'Preparing the immutable master prompt; visual references remain unused…'
          : directReferenceVideo
            ? `Loading ${approvedVisualReferenceCount} approved visual reference${approvedVisualReferenceCount === 1 ? '' : 's'}; no start images will be generated…`
          : 'Loading character and world references…',
        'preparing_music_video', 1, 3,
      )
      const generationSettings: MusicVideoGenerationSettings = {
        imageModel: filmImageModel,
        videoModel: filmVideoModel,
        resolution: storyVideoResolution,
        aspectRatio: storyVideoAspectRatio,
        generationMode: effectiveMusicVideoMode,
        directVideoMasterPrompt: project.directVideoMasterPrompt,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
      }
      const loaded = await loadMusicVideoProduction(
        project,
        cue,
        candidate,
        options.autoStart === true,
        options.pacing || musicProductionPacing,
        options.mode === 'trailer' ? options.excerpt : undefined,
        generationSettings,
        () => activity.handoff('Continuing in Director as a recoverable music-video workflow'),
      )
      activity.update('Saving the independent production snapshot…', 'preparing_music_video', 2, 3)
      if (options.saveProduction !== false) {
        updateProjectById(sourceProjectId, current => ({
          ...current,
          productions: [...current.productions, {
            id: storyId('production'),
            kind: 'music_video',
            title: `${loaded.adaptation.focusLabel} · ${options.mode === 'trailer' ? 'musical trailer' : 'music video'}`,
            createdAt: new Date().toISOString(),
            sourceVersion: current.revision,
            sourceSnapshot: { ...structuredClone(current), productions: [] },
            targetId: loaded.adaptation.focusTargetId,
            targetName: loaded.adaptation.focusLabel,
            targetSnapshot: {
              cueId: loaded.resolvedCue.id,
              candidateId: candidate.id,
              candidateName: candidate.name,
              candidateSource: candidate.source,
              provider: candidate.provider,
              model: candidate.model,
              lyrics: loaded.resolvedCue.lyrics,
              focusKind: loaded.adaptation.focusKind,
              focusTargetId: loaded.adaptation.focusTargetId,
              sceneDescription: loaded.adaptation.sceneDescription,
              pacing: options.pacing || musicProductionPacing,
              mode: options.mode || 'full',
              trimStart: options.mode === 'trailer' ? options.excerpt?.start : undefined,
              trimEnd: options.mode === 'trailer' ? options.excerpt?.end : undefined,
              imageModel: loaded.generationSettings.imageModel,
              videoModel: loaded.generationSettings.videoModel,
              resolution: loaded.generationSettings.resolution,
              aspectRatio: loaded.generationSettings.aspectRatio,
              generationMode: loaded.generationSettings.generationMode,
              directVideoMasterPrompt: loaded.generationSettings.directVideoMasterPrompt,
              writingProvider: loaded.generationSettings.writingProvider,
              writingModel: loaded.generationSettings.writingModel,
              writingBaseUrl: loaded.generationSettings.writingBaseUrl,
              pipelineId: loaded.pipelineId,
            },
            status: 'staged',
          }],
        }))
      }
      setNotice({
        kind: 'ok',
        text: options.autoStart
          ? `The ${options.mode === 'trailer' ? 'musical trailer' : 'music video'} for “${loaded.adaptation.focusLabel}” is running in Director.`
          : loaded.generationSettings.generationMode === 'direct_video'
            ? `The song, lyrics and direct T2V master prompt for “${loaded.adaptation.focusLabel}” are loaded in Director; no images were transferred.`
            : loaded.generationSettings.generationMode === 'direct_references'
              ? `The song, lyrics and approved references for “${loaded.adaptation.focusLabel}” are loaded for H3 Ref2VA; no start-image generation is needed.`
            : `The song, lyrics and visual references for “${loaded.adaptation.focusLabel}” are loaded in Director.`,
      })
    } catch (error) {
      activity.fail(error, 'preparing_music_video')
      setNotice({ kind: 'error', text: `The music video could not load the song: ${(error as Error).message}` })
    } finally {
      activity.finish()
      setProductionBusy(null)
    }
  }

  const stageMusicVideo = async (autoStart = false) => {
    if (!storyVideoConfigurationReady) {
      setNotice({
        kind: 'error',
        text: legacyVideoOverridePending
          ? 'Restoring this legacy Story’s previous video model and format. Try again in a moment.'
          : 'Checking the selected video model’s supported formats. Try again in a moment.',
      })
      return
    }
    if (!selectedMusicOption) {
      setNotice({ kind: 'error', text: 'Generate or import a song in Music before creating a music video.' })
      return
    }
    if (musicProductionMode === 'trailer' && musicTrailerRange.end <= musicTrailerRange.start + 0.99) {
      setNotice({ kind: 'error', text: 'Choose and preview a trailer excerpt of at least one second.' })
      return
    }
    if (!directReferenceVideoReady) {
      setNotice({
        kind: 'error',
        text: directReferenceVideoSupported
          ? 'Approve at least one visual asset before using direct references.'
          : 'Choose a MiniMax H3 video model before using direct references.',
      })
      return
    }
    if (autoStart && !window.confirm(
      `Generate the ${musicProductionMode === 'trailer' ? 'musical trailer' : 'complete music video'} for “${selectedMusicOption.label}”? `
      + `Video model: ${selectedFilmVideoModel?.name || filmVideoModel} (${filmVideoModel}) · ${storyVideoResolution} ${storyVideoAspectRatio}. `
      + (directMusicVideo
        ? 'This sends one pure text-to-video request per planned clip, without creating or uploading images, and may consume video-generation credits.'
        : directReferenceVideo
          ? `This sends ${approvedVisualReferenceCount} approved reference${approvedVisualReferenceCount === 1 ? '' : 's'} directly to H3 Ref2VA and skips start-image generation.`
        : 'This creates one start image and one video render per planned clip and may consume provider credits.'),
    )) return
    await openMusicalTrailer(selectedMusicOption.candidate.id, {
      autoStart,
      pacing: musicProductionPacing,
      mode: musicProductionMode,
      excerpt: musicProductionMode === 'trailer'
        ? { start: musicTrailerRange.start, end: musicTrailerRange.end }
        : undefined,
    })
  }

  const reopenProduction = async (productionId: string) => {
    const production = project.productions.find(item => item.id === productionId)
    if (!production) return
    if (production.kind === 'music_video') {
      const source = normalizeStoryProject(production.sourceSnapshot)
      const candidateId = typeof production.targetSnapshot?.candidateId === 'string'
        ? production.targetSnapshot.candidateId : ''
      const candidate = musicCandidateById(source, candidateId)
      const cue = musicCueForCandidate(source, candidateId)
      if (!candidate) {
        setNotice({ kind: 'error', text: 'The selected song for this production is no longer available.' })
        return
      }
      const pacingValue = production.targetSnapshot?.pacing
      const pacing = pacingValue === 'cinematic' || pacingValue === 'rhythmic'
        ? pacingValue : 'balanced'
      const mode = production.targetSnapshot?.mode === 'trailer' ? 'trailer' : 'full'
      const trimStart = Number(production.targetSnapshot?.trimStart)
      const trimEnd = Number(production.targetSnapshot?.trimEnd)
      const excerpt = mode === 'trailer' && Number.isFinite(trimStart) && Number.isFinite(trimEnd) && trimEnd > trimStart
        ? { start: trimStart, end: trimEnd }
        : undefined
      const savedWritingProvider = production.targetSnapshot?.writingProvider
      const generationSettings: MusicVideoGenerationSettings = {
        imageModel: typeof production.targetSnapshot?.imageModel === 'string'
          ? production.targetSnapshot.imageModel : filmImageModel,
        videoModel: typeof production.targetSnapshot?.videoModel === 'string'
          ? production.targetSnapshot.videoModel : filmVideoModel,
        resolution: savedStoryVideoResolution(
          production.targetSnapshot?.resolution,
          storyVideoResolution,
        ),
        aspectRatio: savedStoryVideoAspect(
          production.targetSnapshot?.aspectRatio,
          storyVideoAspectRatio,
        ),
        generationMode: production.targetSnapshot?.generationMode === 'direct_video'
          ? 'direct_video'
          : production.targetSnapshot?.generationMode === 'direct_references'
            ? 'direct_references'
            : source.musicVideoGenerationMode,
        directVideoMasterPrompt: typeof production.targetSnapshot?.directVideoMasterPrompt === 'string'
          ? production.targetSnapshot.directVideoMasterPrompt : source.directVideoMasterPrompt,
        writingProvider: savedWritingProvider === 'deepseek'
          || savedWritingProvider === 'minimax'
          || savedWritingProvider === 'openai'
          || savedWritingProvider === 'openai-compatible'
          || savedWritingProvider === 'maestro'
          ? savedWritingProvider : source.provider.writingProvider,
        writingModel: typeof production.targetSnapshot?.writingModel === 'string'
          ? production.targetSnapshot.writingModel : source.provider.writingModel,
        writingBaseUrl: typeof production.targetSnapshot?.writingBaseUrl === 'string'
          ? production.targetSnapshot.writingBaseUrl : source.provider.writingBaseUrl,
      }
      const current = useStore.getState()
      const hasWork = Boolean(current.directorSceneDescription.trim() || current.directorPlannedClips.length)
      if (hasWork && !window.confirm(
        'Reopen this music-video production? The current Director draft will be replaced.',
      )) return
      setProductionBusy('music')
      try {
        await loadMusicVideoProduction(source, cue, candidate, false, pacing, excerpt, generationSettings)
      } catch (error) {
        setNotice({ kind: 'error', text: `The music-video production could not be reopened: ${(error as Error).message}` })
      } finally {
        setProductionBusy(null)
      }
      return
    }
    if (production.kind === 'comic') {
      const comic = production.targetSnapshot?.comic
      const request = production.targetSnapshot?.request
      if (!comic || typeof comic !== 'object') {
        setNotice({ kind: 'error', text: 'This legacy adaptation has no reopenable comic snapshot.' })
        return
      }
      if (useComicStore.getState().dirty && !window.confirm(
        'Reopen this staged comic? Unsaved changes in the current comic will be lost.',
      )) return
      useComicStore.getState().setProject(comic as unknown as ComicProject)
      window.localStorage.removeItem('maestro-last-comic-plan-result')
      window.localStorage.removeItem('maestro-last-comic-plan-job')
      if (request && typeof request === 'object') {
        window.localStorage.setItem('maestro-story-comic-draft', JSON.stringify(request))
        window.dispatchEvent(new CustomEvent('maestro:comic-staged', { detail: request }))
      }
      const maestro = useStore.getState()
      maestro.setMediaFilter('comics')
      maestro.setSidebarMode('director')
      maestro.setDirectorSkill('comic')
      window.dispatchEvent(new Event('maestro:director-open'))
      return
    }
    const source = normalizeStoryProject(production.sourceSnapshot)
    const director = useStore.getState()
    const hasWork = Boolean(
      director.directorSceneDescription.trim()
      || director.directorPlannedClips.length
      || director.directorCharacterRefs.length
      || director.directorLocationRefs.length,
    )
    if (hasWork && !window.confirm(
      production.kind === 'trailer'
        ? '¿Reabrir este tráiler? El borrador actual de Director se sustituirá.'
        : 'Reopen this film staging? The current Director draft will be replaced.',
    )) return
    const direction = typeof production.targetSnapshot?.direction === 'string'
      ? production.targetSnapshot.direction
      : production.kind === 'trailer' ? DEFAULT_TRAILER_DIRECTION : DEFAULT_SHORT_FILM_DIRECTION
    const targetDuration = Number(production.targetSnapshot?.targetDuration)
      || (production.kind === 'trailer' ? 60 : 45)
    const preserveVisualStyle = production.targetSnapshot?.preserveVisualStyle !== false
    const videoModel = typeof production.targetSnapshot?.videoModel === 'string'
      ? production.targetSnapshot.videoModel
      : filmVideoModel
    const imageModel = typeof production.targetSnapshot?.imageModel === 'string'
      ? production.targetSnapshot.imageModel
      : filmImageModel
    const resolution = savedStoryVideoResolution(
      production.targetSnapshot?.resolution,
      storyVideoResolution,
    )
    const aspectRatio = savedStoryVideoAspect(
      production.targetSnapshot?.aspectRatio,
      storyVideoAspectRatio,
    )
    const trailerOptions: TrailerAdaptationOptions | undefined = production.kind === 'trailer'
      ? {
          format: production.targetSnapshot?.trailerFormat === 'teaser'
            ? 'teaser' : production.targetSnapshot?.trailerFormat === 'character' ? 'character' : 'theatrical',
          narration: production.targetSnapshot?.trailerNarration === 'voice_over'
            ? 'voice_over' : production.targetSnapshot?.trailerNarration === 'dialogue'
              ? 'dialogue' : production.targetSnapshot?.trailerNarration === 'visual' ? 'visual' : 'hybrid',
          spoiler: production.targetSnapshot?.trailerSpoiler === 'mystery'
            ? 'mystery' : production.targetSnapshot?.trailerSpoiler === 'revealing' ? 'revealing' : 'balanced',
          intensity: production.targetSnapshot?.trailerIntensity === 'relentless'
            ? 'relentless' : production.targetSnapshot?.trailerIntensity === 'prestige' ? 'prestige' : 'rising',
          tagline: typeof production.targetSnapshot?.trailerTagline === 'string'
            ? production.targetSnapshot.trailerTagline : '',
          titleCards: production.targetSnapshot?.trailerTitleCards === true,
          preserveVisualStyle,
        }
      : undefined
    await loadFilmProduction(
      source,
      direction,
      false,
      targetDuration,
      preserveVisualStyle,
      videoModel,
      imageModel,
      resolution,
      aspectRatio,
      trailerOptions,
    )
  }

  const restoreProductionSource = (productionId: string) => {
    const production = project.productions.find(item => item.id === productionId)
    if (!production?.sourceSnapshot) return
    const restored = normalizeStoryProject({
      ...structuredClone(production.sourceSnapshot),
      id: storyId('story'),
      title: `${production.title} · source v${production.sourceVersion}`,
      approvals: {},
      productions: [],
      revision: 1,
    })
    setProject(restored)
    setNotice({ kind: 'ok', text: 'The adaptation source was restored as a new editable story; the current version was preserved.' })
  }

  const tabs: Array<{ id: StoryTab; label: string; icon: typeof BookOpen }> = project.projectType === 'music_video'
    ? [
      { id: 'overview', label: 'Videoclip', icon: Film },
      { id: 'assets', label: 'Imágenes', icon: ImagePlus },
      { id: 'music', label: 'Canción', icon: Music },
      { id: 'trailer', label: 'Tráiler', icon: Film },
      { id: 'productions', label: 'Generar', icon: Sparkles },
      { id: 'assembly', label: 'Montaje', icon: Play },
    ]
    : project.projectType === 'trailer'
      ? [
        { id: 'overview', label: 'Tráiler', icon: Film },
        { id: 'assets', label: 'Imágenes', icon: ImagePlus },
        { id: 'trailer', label: 'Crear tráiler', icon: Sparkles },
        { id: 'assembly', label: 'Montaje', icon: Play },
      ]
      : project.projectType === 'quick_video'
      ? [
        { id: 'overview', label: 'Vídeo rápido', icon: Film },
        { id: 'assets', label: 'Imágenes', icon: ImagePlus },
        { id: 'trailer', label: 'Tráiler', icon: Film },
        { id: 'productions', label: 'Generar', icon: Sparkles },
        { id: 'assembly', label: 'Montaje', icon: Play },
      ]
      : [
        { id: 'overview', label: 'Story', icon: BookOpen },
        { id: 'assets', label: 'Assets', icon: ImagePlus },
        { id: 'world', label: 'World', icon: Boxes },
        { id: 'characters', label: 'Characters', icon: Users },
        { id: 'music', label: 'Music', icon: Music },
        { id: 'relationships', label: 'Relationships', icon: Network },
        { id: 'structure', label: 'Structure', icon: ChevronRight },
        { id: 'trailer', label: 'Tráiler', icon: Film },
        { id: 'productions', label: 'Productions', icon: Film },
        { id: 'assembly', label: 'Assembly', icon: Play },
      ]
  const visibleTabIds = tabs.map(item => item.id)
  const foundationChecks = project.projectType === 'music_video'
    ? [
      Boolean(project.logline && project.synopsis),
      Boolean(project.world.summary),
      project.characters.length > 0,
      project.beats.length >= 4,
      project.music.cues.length > 0,
    ]
    : [
      Boolean(project.logline && project.synopsis),
      Boolean(project.world.summary),
      project.characters.length > 0,
      project.beats.length >= (project.projectType === 'quick_video' ? 3 : 6),
    ]
  const progress = foundationChecks.filter(Boolean).length
  const foundationTotal = foundationChecks.length
  const styledReferenceTargetCount = new Set([
    ...project.world.referenceAssetIds,
    ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ...project.characters.flatMap(character => character.referenceAssetIds),
  ].filter(id => Boolean(project.assets[id]))).size
  useEffect(() => {
    if (!visibleTabIds.includes(tab)) setTab('overview')
  }, [project.projectType, tab]) // eslint-disable-line react-hooks/exhaustive-deps
  const collectProductionIssues = (requiresVisualIdentities: boolean): ProductionReviewIssue[] => {
    if (project.workflowMode === 'automatic') return []
    const required: Array<keyof StoryProject['approvals']> = [
      'overview', 'world', 'characters', 'structure',
    ]
    if (project.projectType === 'full_story' && project.relationships.length) required.push('relationships')
    const sectionLabels: Record<keyof StoryProject['approvals'], string> = {
      overview: project.projectType === 'music_video'
        ? 'Aprobar canción e historia visual'
        : project.projectType === 'trailer' ? 'Aprobar concepto del tráiler' : 'Aprobar concepto',
      world: project.projectType === 'music_video'
        ? 'Aprobar entorno y dirección visual'
        : project.projectType === 'trailer' ? 'Aprobar mundo cinematográfico' : 'Aprobar mundo',
      characters: project.projectType === 'trailer' ? 'Aprobar protagonistas' : 'Aprobar conjunto de personajes',
      relationships: 'Aprobar relaciones',
      structure: project.projectType === 'music_video'
        ? 'Aprobar momentos visuales'
        : project.projectType === 'trailer' ? 'Aprobar arco del tráiler' : 'Aprobar estructura',
    }
    const issues: ProductionReviewIssue[] = required
      .filter(section => section !== 'characters' && !isApproved(section))
      .map(section => ({
        id: `section:${section}`,
        label: sectionLabels[section],
        detail: 'Abre la sección, revisa el contenido y pulsa Aprobar.',
        tab: section as StoryTab,
        anchorId: `story-review-${section}`,
      }))
    const incompleteCharacters = project.characters.filter(character =>
      character.approval !== 'approved'
      || (requiresVisualIdentities && (
        !character.primaryReferenceAssetId
        || project.assets[character.primaryReferenceAssetId]?.approval !== 'approved'
      )))
    if (incompleteCharacters.length) {
      const names = incompleteCharacters.map(character => character.name || 'Sin nombre').join(', ')
      issues.push({
        id: 'characters:items',
        label: requiresVisualIdentities
          ? `Revisar identidades: ${names}`
          : `Aprobar descripciones: ${names}`,
        detail: requiresVisualIdentities
          ? 'Cada personaje necesita una imagen principal aprobada y su identidad confirmada.'
          : 'En vídeo directo no hacen falta imágenes; Aprobar conjunto confirma todas las descripciones de una vez.',
        tab: 'characters',
        anchorId: `story-review-character-${incompleteCharacters[0].id}`,
      })
    } else if (!isApproved('characters')) {
      issues.push({
        id: 'section:characters',
        label: sectionLabels.characters,
        detail: 'Las fichas individuales están listas; sólo falta confirmar el conjunto.',
        tab: 'characters',
        anchorId: 'story-review-characters',
      })
    }
    return issues
  }
  const productionIssues = collectProductionIssues(true)
  const musicProductionIssues = collectProductionIssues(!directMusicVideo)
  const trailerProductionIssues = collectProductionIssues(!directVideo)
  const visibleProductionIssues = project.projectType === 'music_video'
    ? musicProductionIssues
    : project.projectType === 'trailer'
      ? trailerProductionIssues
      : productionIssues

  return (
    <StoryLabVisualsProvider value={{
      imageBusy,
      referenceBatchBusy,
      generateVisual,
      requestUpload: target => {
        setUploadTarget(target)
        uploadRef.current?.click()
      },
      removeReference,
    }}>
    <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-bg-primary overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg-secondary px-3 py-2">
        <div className="mr-auto">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-accent-blue" />
            <span className="text-sm font-semibold text-text-primary">Story Lab</span>
            <span className="text-[10px] text-text-muted">v{project.revision} · {progress}/{foundationTotal} {project.projectType === 'full_story' ? 'foundations' : 'requisitos'}</span>
            {storyLoading
              ? <span className="text-[9px] text-text-muted">loading workspace…</span>
              : storySaveError
                ? <span className="text-[9px] text-red-300" title={storySaveError}>local fallback · save unavailable</span>
                : dirty
                  ? <span className="text-[9px] text-amber-300">saving to workspace…</span>
                  : storyHydrated
                    ? <span className="text-[9px] text-emerald-400">saved in workspace</span>
                    : <span className="text-[9px] text-text-muted">cached locally</span>}
          </div>
          <p className="text-[9px] text-text-muted mt-0.5">
            {STORY_PROJECT_TYPES.find(item => item.id === project.projectType)?.description}
          </p>
          <StoryLibraryConflictNotice conflicts={storyLibraryConflicts} onResolve={resolveStoryLibraryConflict} />
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[9px]">
            <span className="inline-flex items-center gap-1.5 text-violet-200">
              <span className="h-2 w-2 rounded-full bg-violet-400 shadow-[0_0_8px_rgba(139,92,246,0.8)]" /> Campo o preparación necesaria
            </span>
            <span className="inline-flex items-center gap-1.5 text-emerald-200">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]" /> Genera el resultado completo
            </span>
          </div>
        </div>
        <select
          className={`${input} w-44`}
          value={project.id}
          disabled={Boolean(busy || imageBusy || projectOperationBusy)}
          title={`Story Lab library · ${activeWorkspace}`}
          onChange={event => openProject(event.target.value)}
        >
          {Object.values(projects)
            .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
            .map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
        <select
          className={`${input} w-40`}
          value={project.projectType}
          disabled={Boolean(busy || imageBusy || projectOperationBusy)}
          title="Tipo de proyecto Story Lab"
          onChange={event => {
            const projectType = event.target.value as StoryProjectType
            const durationSeconds = projectType === 'quick_video' && project.projectType !== 'quick_video'
              ? 15
              : projectType === 'music_video' && project.projectType !== 'music_video'
                ? 90
                : projectType === 'trailer' && project.projectType !== 'trailer'
                  ? 60
                : project.creativeBrief.durationSeconds
            patch({
              projectType,
              creativeBrief: { ...project.creativeBrief, durationSeconds },
              ...(projectType === 'trailer' && project.projectType !== 'trailer'
                ? { musicVideoGenerationMode: 'image_guided' as const }
                : {}),
            })
          }}
        >
          {STORY_PROJECT_TYPES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <select className={`${input} w-auto`} value={project.workflowMode} onChange={event => patch({ workflowMode: event.target.value as StoryProject['workflowMode'] })}>
          <option value="guided">Guided · approve stages</option>
          <option value="automatic">Automatic · one click</option>
        </select>
        <button className={`${button} ${progress < foundationTotal ? requiredPreparationButton : ''}`} onClick={() => generate('all')}
          disabled={Boolean(busy || referenceBatchBusy)}
          title="Prepara con el LLM todos los campos de texto; no genera audio, imágenes ni vídeo.">
          {busy === 'all' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {jobProgress || (
            project.projectType === 'music_video' ? 'Preparar canción e historia visual · solo texto'
              : project.projectType === 'trailer' ? 'Preparar tráiler cinematográfico · solo texto'
              : project.projectType === 'quick_video' ? 'Preparar vídeo rápido · solo texto'
                : 'Preparar historia completa · solo texto'
          )}
        </button>
        <button className={`${button} ${progress < foundationTotal ? requiredPreparationButton : ''}`} onClick={() => generate('all', { generateImages: true })}
          disabled={Boolean(busy || referenceBatchBusy)}
          title="Prepara todos los textos y después genera las imágenes conceptuales que todavía falten. Puede consumir créditos de imagen.">
          {busy === 'all' || referenceBatchBusy ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
          {project.projectType === 'music_video' ? 'Preparar canción e historia visual + imágenes'
            : project.projectType === 'trailer' ? 'Preparar tráiler cinematográfico + imágenes'
            : project.projectType === 'quick_video' ? 'Preparar vídeo rápido + imágenes'
              : 'Preparar historia completa + imágenes'}
        </button>
        {busy && recoveryJobId && (
          <button className={`${button} border-red-500/50 text-red-300`} onClick={cancelGeneration}>
            Cancel
          </button>
        )}
        {recoveryJobId && !pendingDraft && (
          <button className={button} onClick={resumeGeneration} disabled={Boolean(busy)} title={`Resume ${recoveryJobId}`}>
            Resume
          </button>
        )}
        <button className={button} onClick={exportStorypack}><Download size={13} /> Storypack</button>
        <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> Import</button>
        <button className={button} disabled={smartAssetBusy} onClick={() => {
          setTab('assets')
          smartAssetRef.current?.click()
        }} title="Upload a group of images and let the selected Story Lab LLM classify them">
          {smartAssetBusy ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} Smart assets
        </button>
        <details className="relative">
          <summary className={`${button} list-none cursor-pointer`}><Plus size={13} /> New</summary>
          <div className="absolute right-0 z-40 mt-1 w-64 rounded-lg border border-border bg-bg-primary p-1.5 shadow-xl">
            {STORY_PROJECT_TYPES.map(item => (
              <button key={item.id} type="button" disabled={Boolean(busy || imageBusy || projectOperationBusy)}
                className="block w-full rounded-md px-2.5 py-2 text-left hover:bg-bg-hover disabled:opacity-40"
                onClick={event => {
                  newProject(item.id)
                  const details = event.currentTarget.closest('details') as HTMLDetailsElement | null
                  details?.removeAttribute('open')
                }}>
                <span className="block text-xs font-medium text-text-primary">{item.label}</span>
                <span className="mt-0.5 block text-[9px] text-text-muted">{item.description}</span>
              </button>
            ))}
          </div>
        </details>
        <button className={button} disabled={Boolean(busy || imageBusy || projectOperationBusy)} onClick={() => duplicateProject()} title="Duplicate current story">Duplicate</button>
        <button className={button} onClick={() => {
          if (window.confirm(`Delete "${project.title}" from this workspace's Story Lab library?`)) deleteProject(project.id)
        }} disabled={Boolean(busy || imageBusy || projectOperationBusy)} title="Delete current story"><Trash2 size={13} /></button>
        <input ref={importRef} type="file" accept=".storypack,.zip,.json" className="hidden" onChange={event => importStorypack(event.target.files?.[0])} />
      </div>

      {notice && (
        <div className={`px-3 py-2 text-xs border-b border-border ${notice.kind === 'error' ? 'text-red-300 bg-red-500/10' : 'text-emerald-300 bg-emerald-500/10'}`}>
          {notice.text}
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <StoryLabNavigation
          tabs={tabs}
          activeTab={tab}
          onChange={setTab}
          notes={project.projectType === 'full_story' ? (
            <>
              <p>Manual edits are always authoritative.</p>
              <p>Regeneration preserves existing reference images.</p>
              <p>Adaptations remember the source revision.</p>
            </>
          ) : (
            <>
              <p>Concepto, imágenes y secuencia viven juntos.</p>
              <p>Las referencias aprobadas pasan a Director.</p>
              <p>Puedes editar cualquier resultado antes de generar.</p>
            </>
          )}
        />

        <div className="flex-1 min-w-0 overflow-y-auto p-3 md:p-5">
          <div className="max-w-[1500px] mx-auto">
            {pendingDraft && (
              <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-500/5 p-3">
                <div className="flex flex-col xl:flex-row xl:items-start gap-3">
                  <div className="min-w-56">
                    <p className="text-xs font-semibold text-amber-200">Generated draft · {pendingDraft.scope}</p>
                    <p className="text-[10px] text-text-muted mt-1">Choose exactly which generated items to apply. Existing references are preserved.</p>
                    <label className="mt-2 flex items-center gap-2 text-[10px] text-text-secondary">
                      <input
                        type="checkbox"
                        checked={pendingDraft.replaceCollections}
                        onChange={event => setPendingDraft(current => current ? {
                          ...current, replaceCollections: event.target.checked,
                        } : current)}
                      />
                      Replace complete selected collections
                    </label>
                  </div>
                  <div className="flex-1 grid sm:grid-cols-2 lg:grid-cols-3 gap-1 max-h-36 overflow-y-auto">
                    {draftPaths(pendingDraft.result).map(path => (
                      <label key={path} className="flex items-center gap-2 rounded bg-bg-tertiary px-2 py-1 text-[10px] text-text-secondary">
                        <input
                          type="checkbox"
                          checked={pendingDraft.selected.includes(path)}
                          onChange={event => setPendingDraft(current => {
                            if (!current) return current
                            const selected = event.target.checked
                              ? [...current.selected, path]
                              : current.selected.filter(item => item !== path)
                            return { ...current, selected }
                          })}
                        />
                        <span className="truncate">{path}</span>
                      </label>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button className={`${button} ${requiredPreparationButton}`} disabled={!pendingDraft.selected.length || referenceBatchBusy}
                      onClick={() => void applyPendingGeneratedDraft()}>
                      {referenceBatchBusy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                      {pendingDraft.generateImagesAfterApply ? 'Apply selected + generate images' : 'Apply selected text'}
                    </button>
                    <button className={button} onClick={() => {
                      setPendingDraft(null)
                      window.localStorage.removeItem(storyResultKey(activeWorkspace, project.id))
                      window.localStorage.removeItem(storyJobKey(activeWorkspace, project.id))
                      setRecoveryJobId('')
                    }}>Discard</button>
                    <details className="text-[10px] text-text-muted">
                      <summary className="cursor-pointer py-2">Raw JSON</summary>
                      <pre className="absolute z-30 right-4 mt-1 max-w-[70vw] max-h-[50vh] overflow-auto rounded-lg border border-border bg-bg-primary p-3 shadow-xl whitespace-pre-wrap">
                        {JSON.stringify(pendingDraft.result, null, 2)}
                      </pre>
                    </details>
                  </div>
                </div>
              </div>
            )}
            {tab === 'overview' && (
              <>
                <StoryOverviewTab
                  project={project}
                  patch={patch}
                  update={update}
                  busy={busy}
                  instruction={instruction}
                  setInstruction={setInstruction}
                  generate={generate}
                  approve={approve}
                  isApproved={isApproved}
                  setTrailerDuration={setTrailerDuration}
                  protagonistReferenceReady={protagonistReferenceReady}
                  promptHealthWarnings={promptHealthWarnings}
                  writeStyleIntoPrompts={writeStyleIntoPrompts}
                  regenerateStyledReferences={regenerateStyledReferences}
                  imageBusy={imageBusy}
                  referenceBatchBusy={referenceBatchBusy}
                  styledReferenceTargetCount={styledReferenceTargetCount}
                  onProfileModeChange={setStoryProfileMode}
                />
                {project.projectType !== 'full_story' && (
                  <CompactVideoWorkspace
                    project={project}
                    update={update}
                    busy={busy}
                    generateSection={generate}
                    approveSection={approve}
                    isSectionApproved={isApproved}
                    navigate={setTab}
                    requiresVisualIdentities={!directVideo}
                  />
                )}
              </>
            )}

            {tab === 'assets' && (
              <StoryAssetsTab
                project={project}
                smartAssetBusy={smartAssetBusy}
                smartAssetDescription={smartAssetDescription}
                setSmartAssetDescription={setSmartAssetDescription}
                smartAssetRef={smartAssetRef}
                pendingSmartAssets={pendingSmartAssets}
                setPendingSmartAssets={setPendingSmartAssets}
                analyzeSmartAssets={analyzeSmartAssets}
                applySmartAssets={applySmartAssets}
                patchPendingSmartAsset={patchPendingSmartAsset}
                styleConversion={styleConversion}
                setStyleConversion={setStyleConversion}
                styleConversionModel={styleConversionModel}
                setStyleConversionModel={setStyleConversionModel}
                styleConversionBusy={styleConversionBusy}
                styleModelDownloading={styleModelDownloading}
                setStyleModelDownloadError={setStyleModelDownloadError}
                styleModelDownloadError={styleModelDownloadError}
                localStyleModels={localStyleModels}
                qwenModel={QWEN_STYLE_EDIT_MODEL}
                fluxModel={FLUX_STYLE_EDIT_MODEL}
                styleAssetIds={styleAssetIds}
                setStyleAssetIds={setStyleAssetIds}
                styleUsesMiniMax={styleUsesMiniMax}
                selectedStyleModel={selectedStyleModel}
                styleModelReady={styleModelReady}
                miniMaxIncompatibleSelection={miniMaxIncompatibleSelection}
                installStyleConversionModel={installStyleConversionModel}
                cancelStyleConversion={cancelStyleConversion}
                convertSelectedAssetsToStyle={convertSelectedAssetsToStyle}
                selectedDraftAssetIds={selectedDraftAssetIds}
                deleteSelectedDraftAssets={deleteSelectedDraftAssets}
                toggleStyleAsset={toggleStyleAsset}
                patchVisualAsset={patchVisualAsset}
                visualAssetsNewestFirst={visualAssetsNewestFirst}
              />
            )}

            {tab === 'world' && (
              <StoryWorldTab
                project={project}
                patch={patch}
                update={update}
                busy={busy}
                instruction={instruction}
                setInstruction={setInstruction}
                generate={generate}
                approve={approve}
                isApproved={isApproved}
              />
            )}

            {tab === 'characters' && (
              <StoryCharactersTab
                project={project}
                update={update}
                busy={busy}
                instruction={instruction}
                setInstruction={setInstruction}
                generate={generate}
                approve={approve}
                isApproved={isApproved}
              />
            )}

            {tab === 'relationships' && (
              <StoryRelationshipsTab
                project={project}
                update={update}
                busy={busy}
                instruction={instruction}
                setInstruction={setInstruction}
                generate={generate}
                approve={approve}
                isApproved={isApproved}
              />
            )}

            {tab === 'structure' && (
              <StoryStructureTab
                project={project}
                update={update}
                busy={busy}
                instruction={instruction}
                setInstruction={setInstruction}
                generate={generate}
                approve={approve}
                isApproved={isApproved}
              />
            )}

            {tab === 'music' && (
              <StoryMusicTab
                project={project}
                patch={patch}
                instruction={instruction}
                setInstruction={setInstruction}
                busy={busy}
                productionBusy={productionBusy}
                musicQueue={musicQueue}
                musicCueBusy={musicCueBusy}
                newSongAction={newSongAction}
                musicWritingReady={musicWritingReady}
                minimaxConfigured={Boolean(servicesConfig?.minimax_api_key_set)}
                storyVideoConfigurationReady={storyVideoConfigurationReady}
                workspace={activeWorkspace}
                musicVersionStyle={musicVersionStyle}
                setMusicVersionStyle={setMusicVersionStyle}
                musicVersionLanguage={musicVersionLanguage}
                setMusicVersionLanguage={setMusicVersionLanguage}
                lyricsTranslationLanguage={lyricsTranslationLanguage}
                setLyricsTranslationLanguage={setLyricsTranslationLanguage}
                generate={generate}
                generateAllMusicCues={generateAllMusicCues}
                cancelMusicQueue={cancelMusicQueue}
                createNewMusicVideoSong={createNewMusicVideoSong}
                createAllMusicCueVersions={createAllMusicCueVersions}
                patchMusicCue={patchMusicCue}
                adaptMusicCueWithLlm={adaptMusicCueWithLlm}
                createMusicCueVersion={createMusicCueVersion}
                translateMusicCueLyrics={translateMusicCueLyrics}
                generateMusicCueAudio={generateMusicCueAudio}
                openMusicalTrailer={openMusicalTrailer}
                onImportCustomMp3={cueId => {
                  customMusicUploadCueId.current = cueId
                  customMusicUploadRef.current?.click()
                }}
                onImportLyria={cueId => {
                  lyriaUploadCueId.current = cueId
                  lyriaUploadRef.current?.click()
                }}
                onCopied={text => setNotice({ kind: 'ok', text })}
                musicCoverRef={musicCoverRef}
                uploadCoverReference={uploadCoverReference}
                writeStorySong={writeStorySong}
                adaptStoryLyrics={adaptStoryLyrics}
                translateManualSongLyrics={translateManualSongLyrics}
                createManualSongVersion={createManualSongVersion}
                generateMinimaxSongs={generateMinimaxSongs}
              />
            )}

            {tab === 'trailer' && (
              <StoryTrailerTab
                project={project}
                patch={patch}
                trailerDuration={trailerDuration}
                setTrailerDuration={setTrailerDuration}
                trailerDirection={trailerDirection}
                setTrailerDirection={setTrailerDirection}
                trailerTagline={trailerTagline}
                setTrailerTagline={setTrailerTagline}
                trailerFormat={trailerFormat}
                setTrailerFormat={setTrailerFormat}
                trailerNarration={trailerNarration}
                setTrailerNarration={setTrailerNarration}
                trailerSpoiler={trailerSpoiler}
                setTrailerSpoiler={setTrailerSpoiler}
                trailerIntensity={trailerIntensity}
                setTrailerIntensity={setTrailerIntensity}
                trailerTitleCards={trailerTitleCards}
                setTrailerTitleCards={setTrailerTitleCards}
                trailerPreserveVisualStyle={trailerPreserveVisualStyle}
                setTrailerPreserveVisualStyle={setTrailerPreserveVisualStyle}
                markTrailerTouched={markTrailerTouched}
                directVideo={directVideo}
                directReferenceVideo={directReferenceVideo}
                approvedVisualReferenceCount={approvedVisualReferenceCount}
                directReferenceVideoReady={directReferenceVideoReady}
                directReferenceVideoSupported={directReferenceVideoSupported}
                directVideoMasterReady={directVideoMasterReady}
                filmImageModel={filmImageModel}
                filmVideoModel={filmVideoModel}
                selectableImageModels={selectableImageModels}
                selectableVideoModels={selectableVideoModels}
                selectedFilmImageModel={selectedFilmImageModel}
                selectedFilmVideoModel={selectedFilmVideoModel}
                selectDirectorImageModel={selectDirectorImageModel}
                selectStoryVideoModel={selectStoryVideoModel}
                storyVideoOptionsReady={storyVideoOptionsReady}
                storyVideoConfigurationReady={storyVideoConfigurationReady}
                storyVideoResolution={storyVideoResolution}
                storyVideoAspectRatio={storyVideoAspectRatio}
                storyVideoOptions={storyVideoOptions}
                storyVideoAdjusted={storyVideoFormat.adjusted}
                setStoryVideoFormat={setStoryVideoFormat}
                trailerProductionIssues={trailerProductionIssues}
                productionBusy={productionBusy}
                filmGenerationImageReady={filmGenerationImageReady}
                stageTrailer={stageTrailer}
              />
            )}

            {tab === 'productions' && (
              <StoryProductionsTab
                project={project}
                patch={patch}
                workspace={activeWorkspace}
                productionBusy={productionBusy}
                comicDirection={comicDirection}
                setComicDirection={setComicDirection}
                comicPageCount={comicPageCount}
                setComicPageCount={setComicPageCount}
                comicPanelsPerPage={comicPanelsPerPage}
                setComicPanelsPerPage={setComicPanelsPerPage}
                stageComic={stageComic}
                filmDirection={filmDirection}
                setFilmDirection={setFilmDirection}
                filmDuration={filmDuration}
                setFilmDuration={setFilmDuration}
                filmPreserveVisualStyle={filmPreserveVisualStyle}
                setFilmPreserveVisualStyle={setFilmPreserveVisualStyle}
                stageFilm={stageFilm}
                musicProductionCandidateId={musicProductionCandidateId}
                setMusicProductionCandidateId={setMusicProductionCandidateId}
                musicCandidateOptions={musicCandidateOptions}
                selectedMusicOption={selectedMusicOption}
                musicProductionMode={musicProductionMode}
                setMusicProductionMode={setMusicProductionMode}
                musicProductionPacing={musicProductionPacing}
                setMusicProductionPacing={setMusicProductionPacing}
                musicTrailerRange={musicTrailerRange}
                setMusicTrailerRange={setMusicTrailerRange}
                stageMusicVideo={stageMusicVideo}
                setMusicWritingProvider={setMusicWritingProvider}
                patchMusicWritingProvider={patchMusicWritingProvider}
                directVideo={directVideo}
                directMusicVideo={directMusicVideo}
                directReferenceVideo={directReferenceVideo}
                approvedVisualReferenceCount={approvedVisualReferenceCount}
                directReferenceVideoReady={directReferenceVideoReady}
                directReferenceVideoSupported={directReferenceVideoSupported}
                directVideoMasterReady={directVideoMasterReady}
                protagonistReferenceReady={protagonistReferenceReady}
                musicWritingReady={musicWritingReady}
                musicVideoImageReady={musicVideoImageReady}
                filmImageReady={filmImageReady}
                filmGenerationImageReady={filmGenerationImageReady}
                filmImageModel={filmImageModel}
                filmVideoModel={filmVideoModel}
                selectableImageModels={selectableImageModels}
                selectableVideoModels={selectableVideoModels}
                selectedFilmImageModel={selectedFilmImageModel}
                selectedFilmVideoModel={selectedFilmVideoModel}
                selectDirectorImageModel={selectDirectorImageModel}
                selectStoryVideoModel={selectStoryVideoModel}
                storyVideoOptionsReady={storyVideoOptionsReady}
                storyVideoConfigurationReady={storyVideoConfigurationReady}
                storyVideoResolution={storyVideoResolution}
                storyVideoAspectRatio={storyVideoAspectRatio}
                storyVideoOptions={storyVideoOptions}
                storyVideoAdjusted={storyVideoFormat.adjusted}
                setStoryVideoFormat={setStoryVideoFormat}
                productionIssues={productionIssues}
                musicProductionIssues={musicProductionIssues}
                visibleProductionIssues={visibleProductionIssues}
                onNavigate={setTab}
                onOpenIssue={openProductionReviewIssue}
                minimaxConfigured={Boolean(servicesConfig?.minimax_api_key_set)}
                musicCoverRef={musicCoverRef}
                uploadCoverReference={uploadCoverReference}
                writeStorySong={writeStorySong}
                adaptStoryLyrics={adaptStoryLyrics}
                generateMinimaxSongs={generateMinimaxSongs}
                openMusicalTrailer={openMusicalTrailer}
              />
            )}

            {tab === 'assembly' && (
              <div className={panel}>
                <div className="mb-4"><h2 className="text-lg font-semibold text-text-primary">Montaje de producciones</h2><p className="mt-1 text-xs text-text-muted">Cada trabajo conserva su secuencia completa. El último se abre automáticamente; al acabar una regeneración, su clip vuelve a aparecer en la misma posición.</p></div>
                {project.productions.length ? [...project.productions].reverse().map((item, index) => (
                  <div key={item.id} className="border-b border-border py-3 text-xs last:border-0"><div className="flex flex-col justify-between gap-2 lg:flex-row lg:items-center">
                    <div><span className="text-text-primary capitalize">{item.kind === 'music_video' ? 'Music video' : item.kind} · {item.targetName || item.title}</span><span className="ml-2 text-text-muted">source v{item.sourceVersion} · {new Date(item.createdAt).toLocaleString()}</span>{item.sourceSnapshot?.sectionVersions && JSON.stringify(item.sourceSnapshot.sectionVersions) !== JSON.stringify(project.sectionVersions) && <span className="ml-2 text-amber-300">source changed since staging</span>}</div>
                    <div className="flex gap-2"><button className={button} onClick={() => reopenProduction(item.id)}>Reopen target</button>{item.sourceSnapshot && <button className={button} onClick={() => restoreProductionSource(item.id)}>Restore source as copy</button>}</div>
                  </div><StoryProductionTimeline production={item} initiallyOpen={index === 0} /></div>
                )) : <p className="text-xs text-text-muted">No adaptation has been staged yet.</p>}
              </div>
            )}
          </div>
        </div>
      </div>
      <input ref={uploadRef} type="file" accept="image/*" multiple className="hidden" onChange={event => uploadVisual(event.target.files)} />
      <input ref={smartAssetRef} type="file" accept="image/*" multiple className="hidden"
        onChange={event => void analyzeSmartAssets(Array.from(event.target.files || []))} />
      <input ref={lyriaUploadRef} type="file" accept="audio/*" className="hidden"
        onChange={event => void uploadLyriaResult(event.target.files?.[0])} />
      <input ref={customMusicUploadRef} type="file" accept=".mp3,audio/mpeg,audio/*" className="hidden"
        onChange={event => void uploadCustomMusic(event.target.files?.[0])} />
    </div>
    </StoryLabVisualsProvider>
  )
}
