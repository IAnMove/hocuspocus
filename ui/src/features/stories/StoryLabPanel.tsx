import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import JSZip from 'jszip'
import {
  BookOpen, Boxes, Check, ChevronDown, ChevronRight, ChevronUp, Copy, Download, ExternalLink, Film, ImagePlus, Loader2,
  Languages, Maximize2, Music, Network, Palette, Play, Plus, RefreshCcw, Sparkles, Trash2, Upload, Users, X,
} from 'lucide-react'
import * as api from '../../api/client'
import { getModelMode, resolveResolution, useStore } from '../../stores/useStore'
import { EditableLanguageInput } from '../../components/common/EditableLanguageInput'
import { generateImageAsset } from '../../lib/imageGeneration'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { getOutputReference } from '../../lib/outputReference'
import { resolveSupportedVideoFormat } from '../../lib/productionProfile'
import { StoryProductionTimeline } from './StoryProductionTimeline'
import { readDirectorClipReplacementResult } from './directorClipHandoff'
import { AudioRangeSelector } from './AudioRangeSelector'
import { createStoryActivityLifecycle } from './activityLifecycle'
import { useComicStore } from '../comics/store'
import type { ComicProject } from '../comics/types'
import { syncTrailerDuration, trailerDurationForProject } from './trailerDefaults'
import { resolveStoryWritingProvider } from './provider'
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
import {
  analyzeStoryPromptHealth,
  applyStoryVisualStyle,
  normalizeStoryCharacter,
  storyNegativePromptForStyle,
  storyRenderStyle,
} from './model'
import type {
  StoryAssetKind, StoryBeat, StoryCharacter, StoryGenerationScope, StoryLocation, StoryProject,
  StoryImageProvider, StoryMusicCandidate, StoryMusicCue, StoryProjectType, StoryRelationship, StoryVisualAsset,
  StoryTrailerFormat, StoryTrailerIntensity, StoryTrailerNarration, StoryTrailerSpoiler, StoryWritingProvider,
} from './types'
import type { AspectRatio, ModelOptions, ResolutionPreset } from '../../types'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'
const panel = 'rounded-xl border border-border bg-bg-secondary p-3 md:p-4'
const requiredInput = 'border-violet-400/70 bg-violet-500/5 shadow-[0_0_14px_rgba(139,92,246,0.22)] focus:border-violet-300 focus:shadow-[0_0_18px_rgba(139,92,246,0.32)]'
const requiredPreparationButton = 'border-violet-400/70 bg-violet-500/10 text-violet-200 shadow-[0_0_14px_rgba(139,92,246,0.22)] hover:border-violet-300 hover:bg-violet-500/20 hover:text-violet-100 disabled:shadow-none'
const completeGenerationButton = 'border-emerald-400/70 bg-emerald-500/10 text-emerald-200 shadow-[0_0_16px_rgba(16,185,129,0.24)] hover:border-emerald-300 hover:bg-emerald-500/20 hover:text-emerald-100 disabled:shadow-none'
const CHARACTER_IDENTITY_REFERENCE_LOCK = [
  'CHARACTER IDENTITY REFERENCE: show exactly one character in a clear medium close-up or chest-up portrait.',
  'The face must be large in frame, sharply readable, unobstructed and well lit, with both eyes and defining facial features clearly visible.',
  'Use a frontal or gentle three-quarter view, a neutral readable pose, the canonical wardrobe, and a simple non-distracting background.',
  'Do not use a distant shot, full-body environmental composition, extreme profile, covered face, dramatic occlusion, action pose or additional characters.',
].join(' ')

const CHARACTER_STYLE_PRESETS = [
  ['Realistas', 'Photorealistic live-action people, natural skin texture, anatomically realistic proportions, authentic hair and fabric, cinematic photographic detail'],
  ['Plastilina', 'Handmade claymation characters sculpted from plasticine, visible fingerprints and tool marks, tactile matte clay surfaces, stop-motion proportions'],
  ['Anime', '2D anime characters, clean expressive linework, consistent cel shading, stylized facial proportions, illustrated skin and hair, never photorealistic'],
] as const

function moveItem<T>(items: T[], from: number, to: number): void {
  if (from < 0 || to < 0 || from >= items.length || to >= items.length || from === to) return
  const [item] = items.splice(from, 1)
  items.splice(to, 0, item)
}

function pruneUnusedAssets(project: StoryProject): void {
  const used = new Set([
    ...project.world.referenceAssetIds,
    ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ...project.characters.flatMap(character => character.referenceAssetIds),
  ])
  Object.keys(project.assets).forEach(id => {
    if (!used.has(id)) delete project.assets[id]
  })
}

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

function storySongBrief(
  project: StoryProject,
  durationSeconds: number,
  lyricsLanguage = project.language,
): string {
  const cast = project.characters.slice(0, 5).map(character =>
    `${character.name}: ${character.desire}; arc: ${character.arc}`).join(' | ')
  const beats = project.beats.map(beat => `${beat.title}: ${beat.summary}`).join(' → ')
  return [
    `Create an original theme song that tells the story “${project.title}”.`,
    `Write all lyrics in ${lyricsLanguage}. Target approximately ${durationSeconds} seconds.`,
    `Genre and emotional direction: ${project.genre}; ${project.tone}. Theme: ${project.theme}.`,
    `Premise: ${storyProjectPremise(project)}. Synopsis: ${project.synopsis}. Ending: ${project.ending}.`,
    cast ? `Character journeys: ${cast}.` : '',
    beats ? `Narrative progression: ${beats}.` : '',
    project.world.visualLanguage ? `Choose music that feels native to this visual world: ${project.world.visualLanguage}.` : '',
    'Use a memorable recurring chorus, concrete story imagery, and a clear emotional progression; do not merely summarize the synopsis.',
  ].filter(Boolean).join('\n')
}

const MINIMAX_LYRIC_SECTION = /^\[(Intro|Verse|Pre Chorus|Chorus|Post Chorus|Interlude|Bridge|Transition|Build Up|Break|Hook|Inst|Solo|Outro)\]\s*$/m

function miniMaxCuePayload(cue: StoryMusicCue, model: StoryProject['music']['model']): string {
  return JSON.stringify({
    model,
    prompt: cue.style.trim().slice(0, 300),
    lyrics: cue.instrumental ? '' : cue.lyrics,
    instrumental: cue.instrumental,
    count: 1,
  }, null, 2)
}

function musicCandidateDisplayName(
  candidate: StoryMusicCandidate,
  title: string,
  fallbackLanguage: string,
  fallbackVersion: number,
): string {
  if (candidate.displayName?.trim()) return candidate.displayName
  const language = candidate.language?.trim() || fallbackLanguage.trim() || 'Original'
  const version = candidate.version || fallbackVersion
  return `${candidate.title?.trim() || title.trim() || 'Story song'} · ${language} · v${version}`
}

function nextMusicCandidateVersion(
  candidates: StoryMusicCandidate[],
  language: string,
  fallbackLanguage: string,
): number {
  const normalizedLanguage = (language || fallbackLanguage).trim().toLocaleLowerCase()
  return candidates.reduce((highest, candidate, index) => {
    const candidateLanguage = (candidate.language || fallbackLanguage).trim().toLocaleLowerCase()
    if (candidateLanguage !== normalizedLanguage) return highest
    return Math.max(highest, candidate.version || index + 1)
  }, 0) + 1
}

type StoryTab = 'overview' | 'assets' | 'world' | 'characters' | 'relationships' | 'structure' | 'music' | 'trailer' | 'productions' | 'assembly'
type ProductionReviewIssue = {
  id: string
  label: string
  detail: string
  tab: StoryTab
  anchorId: string
}
type StyledReferenceTarget = {
  target: { kind: 'world' | 'character' | 'location'; id?: string }
  label: string
  prompt: string
}
type PendingSmartAsset = api.StoryAssetSuggestion & { selected: boolean }
type PendingDraft = {
  scope: StoryGenerationScope
  result: Record<string, unknown>
  selected: string[]
  replaceCollections: boolean
  generateImagesAfterApply: boolean
}
type StoryGenerationOptions = { generateImages?: boolean }
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

const STORY_VIDEO_RESOLUTIONS: ResolutionPreset[] = ['480p', '540p', '720p', '1080p']
const STORY_VIDEO_SAVED_RESOLUTIONS: ResolutionPreset[] = [...STORY_VIDEO_RESOLUTIONS, '768p']
const STORY_VIDEO_ASPECTS: Array<{ value: AspectRatio; label: string; detail: string }> = [
  { value: '16:9', label: 'Landscape', detail: '16:9 · standard video' },
  { value: '9:16', label: 'Portrait / Shorts', detail: '9:16 · vertical video' },
]

function savedStoryVideoResolution(value: unknown, fallback: ResolutionPreset): ResolutionPreset {
  return STORY_VIDEO_SAVED_RESOLUTIONS.includes(value as ResolutionPreset)
    ? value as ResolutionPreset
    : fallback
}

function savedStoryVideoAspect(value: unknown, fallback: AspectRatio): AspectRatio {
  return STORY_VIDEO_ASPECTS.some(option => option.value === value)
    ? value as AspectRatio
    : fallback
}

function StoryVideoFormatControls({
  videoModel,
  resolution,
  aspectRatio,
  options,
  disabled,
  inherited,
  adjusted,
  onChange,
}: {
  videoModel: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
  options: ModelOptions | null
  disabled: boolean
  inherited: boolean
  adjusted: boolean
  onChange: (resolution: ResolutionPreset, aspectRatio: AspectRatio) => void
}) {
  const modelOrder = (options?.resolution_preset_order || [])
    .filter(preset => preset !== 'auto' && (preset !== '768p' || videoModel === 'minimax_h3_legacy'))
  const availablePresets = modelOrder.length > 0
    ? modelOrder
    : STORY_VIDEO_RESOLUTIONS
  const visiblePresets = availablePresets.includes(resolution)
    ? availablePresets
    : [resolution, ...availablePresets].filter(preset => preset !== 'auto')
  const outputSize = resolveResolution(options, resolution, aspectRatio)
  const selectedConfig = options?.resolution_presets?.[resolution]
  const selectedAspect = STORY_VIDEO_ASPECTS.find(option => option.value === aspectRatio)
    || STORY_VIDEO_ASPECTS[0]

  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2 sm:col-span-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-[10px] text-text-muted">Resolución
          <select
            className={`${input} mt-1`}
            value={resolution}
            disabled={disabled}
            onChange={event => onChange(event.target.value as ResolutionPreset, aspectRatio)}
          >
            {visiblePresets.map(preset => (
              <option key={preset} value={preset}>
                {options?.resolution_presets?.[preset]?.label || preset}
              </option>
            ))}
          </select>
        </label>
        <div>
          <span className="block text-[10px] text-text-muted">Formato de pantalla</span>
          <div className="mt-1 grid grid-cols-2 gap-1.5">
            {STORY_VIDEO_ASPECTS.map(option => (
              <button
                key={option.value}
                type="button"
                disabled={disabled}
                aria-pressed={aspectRatio === option.value}
                onClick={() => onChange(resolution, option.value)}
                className={`${button} min-h-12 flex-col ${aspectRatio === option.value ? 'border-2 border-accent-blue bg-accent-blue/15 text-text-primary ring-1 ring-accent-blue/30' : ''}`}
              >
                <span className="flex items-center gap-1">{aspectRatio === option.value && <Check size={11} />} {option.label}</span>
                <span className="text-[9px] text-text-muted">{option.detail}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="rounded-md border border-accent-blue/35 bg-accent-blue/10 px-2.5 py-2">
        <p className="text-[9px] uppercase tracking-wide text-accent-blue">Formato seleccionado</p>
        <p className="mt-0.5 text-[11px] font-semibold text-text-primary">
          {selectedAspect.label} · {aspectRatio} · {resolution} · {outputSize}
        </p>
      </div>
      {inherited ? (
        <p className="text-[9px] leading-relaxed text-emerald-300">
          Heredado del perfil global. Al elegir resolución u orientación se guardará automáticamente como ajuste propio de esta Story.
        </p>
      ) : disabled ? (
        <p className="text-[9px] leading-relaxed text-text-muted">
          Comprobando las resoluciones y orientaciones compatibles con este modelo…
        </p>
      ) : null}
      {adjusted && (
        <p className="text-[9px] leading-relaxed text-amber-300">
          Este modelo no admite el lienzo solicitado; Story Lab ha seleccionado el formato compatible más cercano.
        </p>
      )}
      {selectedConfig?.hint && (
        <p className={`text-[9px] leading-relaxed ${selectedConfig.experimental ? 'text-amber-300' : 'text-text-muted'}`}>
          {selectedConfig.hint}
        </p>
      )}
    </div>
  )
}
const storyJobKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-job:${workspace}:${projectId}`
const storyResultKey = (workspace: string, projectId: string) =>
  `maestro-story-plan-result:${workspace}:${projectId}`

const GENRES = [
  'Adventure', 'Action', 'Comedy', 'Drama', 'Fantasy', 'Science fiction', 'Horror',
  'Mystery', 'Thriller', 'Romance', 'Historical', 'Crime', 'Slice of life',
  'Western', 'Cyberpunk', 'Noir', 'Satire',
]
const TONES = [
  'Cinematic', 'Epic', 'Lighthearted', 'Dark', 'Humorous', 'Dramatic',
  'Suspenseful', 'Emotional', 'Hopeful', 'Gritty', 'Whimsical', 'Mysterious',
  'Romantic', 'Melancholic', 'Satirical', 'Family-friendly',
]

const STORY_PROJECT_TYPES: Array<{ id: StoryProjectType; label: string; description: string }> = [
  { id: 'full_story', label: 'Historia completa', description: 'Mundo, personajes, estructura, música y adaptaciones.' },
  { id: 'music_video', label: 'Videoclip', description: 'Canción original y una historia visual construida alrededor de ella.' },
  { id: 'trailer', label: 'Tráiler cinematográfico', description: 'Tráiler de película con tensión, montaje y gancho final; no requiere canción.' },
  { id: 'quick_video', label: 'Vídeo rápido', description: 'Diálogo, meme, parodia, sketch, viral o anuncio breve.' },
]

const TRAILER_ARC = [
  { label: 'Impacto inicial', start: 0, end: 10, detail: 'Una imagen, sonido o frase que abre una pregunta.' },
  { label: 'Promesa', start: 10, end: 30, detail: 'Mundo, protagonista y deseo emocional.' },
  { label: 'Ruptura', start: 30, end: 50, detail: 'Amenaza central y apuestas comprensibles.' },
  { label: 'Escalada', start: 50, end: 80, detail: 'Montaje causal, variedad visual y ritmo creciente.' },
  { label: 'Respiración', start: 80, end: 90, detail: 'Contraste íntimo o caída casi al silencio.' },
  { label: 'Gancho final', start: 90, end: 100, detail: 'La imagen o frase más potente, sin resolver la historia.' },
] as const

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

function storyProjectPremise(project: StoryProject): string {
  const sourceBrief = project.creativeBrief.generalIdea.trim()
  if (project.projectType === 'music_video') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.performer && `Artista o creador: ${project.creativeBrief.performer}`,
      project.creativeBrief.musicStyle && `Estilo musical: ${project.creativeBrief.musicStyle}`,
      project.creativeBrief.songStory && `La canción cuenta: ${project.creativeBrief.songStory}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'quick_video') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonistas: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `Lugar: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Acción o diálogo: ${project.creativeBrief.action}`,
      `Formato: ${project.creativeBrief.quickFormat}`,
    ].filter(Boolean).join('\n')
  }
  if (project.projectType === 'trailer') {
    return [
      sourceBrief,
      project.creativeBrief.context,
      project.creativeBrief.subjects && `Protagonistas: ${project.creativeBrief.subjects}`,
      project.creativeBrief.setting && `Mundo y localizaciones: ${project.creativeBrief.setting}`,
      project.creativeBrief.action && `Conflicto y promesa del tráiler: ${project.creativeBrief.action}`,
      `Duración objetivo del tráiler: ${project.creativeBrief.durationSeconds}s`,
    ].filter(Boolean).join('\n')
  }
  return [sourceBrief, project.premise].filter(Boolean).join('\n')
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

function Field({
  label, value, onChange, rows = 1, placeholder = '', required = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
  required?: boolean
}) {
  const requiredClass = required ? requiredInput : ''
  return (
    <label className={`block text-[10px] ${required ? 'text-violet-200' : 'text-text-muted'}`}>
      {label}{required && <span className="ml-1 text-violet-300" title="Required">●</span>}
      {rows > 1
        ? <textarea className={`${input} ${requiredClass} mt-1`} rows={rows} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} required={required} aria-required={required} />
        : <input className={`${input} ${requiredClass} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} required={required} aria-required={required} />}
    </label>
  )
}

function Choice({
  label, value, options, onChange, required = false,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
  required?: boolean
}) {
  const custom = !options.includes(value)
  return (
    <label className={`block text-[10px] ${required ? 'text-violet-200' : 'text-text-muted'}`}>
      {label}{required && <span className="ml-1 text-violet-300" title="Required">●</span>}
      <select
        className={`${input} ${required ? requiredInput : ''} mt-1`}
        value={custom ? '__other__' : value}
        onChange={event => onChange(event.target.value === '__other__' ? '' : event.target.value)}
        required={required}
        aria-required={required}
      >
        {options.map(option => <option key={option}>{option}</option>)}
        <option value="__other__">Other…</option>
      </select>
      {custom && <input className={`${input} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={`Custom ${label.toLowerCase()}`} />}
    </label>
  )
}

function ProviderPanel({
  project, patch, onProfileModeChange,
}: {
  project: StoryProject
  patch: (patch: Partial<StoryProject>) => void
  onProfileModeChange: (useGlobalProfile: boolean) => void
}) {
  const services = useStore(state => state.servicesConfig)
  const models = useStore(state => state.models)
  const profile = useStore(state => state.productionProfile)
  const resolvedWriting = resolveStoryWritingProvider(profile, project)
  const provider = resolvedWriting.provider
  const effectiveImageProvider = project.provider.useGlobalProfile && profile.image.provider === 'minimax'
    ? 'minimax' : project.provider.imageProvider
  const effectiveImageModel = project.provider.useGlobalProfile
    ? profile.image.model : project.provider.imageModel
  const installedImageModels = models.filter(model =>
    model.is_downloaded !== false
    && getModelMode(model.model_type, model.family) === 'image')
  const writingReady = provider === 'maestro'
    || (provider === 'deepseek' && Boolean(services?.deepseek_api_key_set))
    || (provider === 'minimax' && Boolean(services?.minimax_api_key_set))
    || (provider === 'openai' && Boolean(services?.openai_api_key_set))
    || (provider === 'openai-compatible'
      && Boolean(services?.compatible_api_key_set && services?.compatible_base_url))
  const imageReady = effectiveImageProvider === 'maestro'
    ? installedImageModels.some(model => model.model_type === effectiveImageModel)
    : Boolean(services?.minimax_api_key_set)
  const setProvider = (next: StoryWritingProvider) => {
    const defaults = next === 'deepseek'
      ? { writingModel: 'deepseek-v4-pro', writingBaseUrl: 'https://api.deepseek.com' }
      : next === 'minimax'
        ? { writingModel: 'MiniMax-M3', writingBaseUrl: 'https://api.minimax.io/v1' }
        : next === 'openai'
          ? { writingModel: 'gpt-4.1', writingBaseUrl: 'https://api.openai.com' }
          : next === 'openai-compatible'
            ? { writingModel: '', writingBaseUrl: services?.compatible_base_url || '' }
            : { writingModel: project.provider.writingModel, writingBaseUrl: project.provider.writingBaseUrl }
    patch({ provider: { ...project.provider, writingProvider: next, ...defaults } })
  }
  const patchProvider = (value: Partial<StoryProject['provider']>) =>
    patch({ provider: { ...project.provider, ...value } })
  return (
    <div className={`${panel} space-y-3`}>
      <div>
        <h3 className="text-sm font-semibold text-text-primary">Generation agents</h3>
        <p className="text-[10px] text-text-muted mt-1">Choose global inheritance or freeze explicit writing and concept-art overrides in this story.</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" className={`${button} ${project.provider.useGlobalProfile ? 'border-accent-blue text-accent-blue' : ''}`}
          onClick={() => onProfileModeChange(true)}>Use global profile</button>
        <button type="button" className={`${button} ${!project.provider.useGlobalProfile ? 'border-accent-blue text-accent-blue' : ''}`}
          onClick={() => onProfileModeChange(false)}>Override in this project</button>
      </div>
      {project.provider.useGlobalProfile && (
        <p className="text-[10px] text-emerald-300">
          Global: {resolvedWriting.provider} / {resolvedWriting.model}
          {resolvedWriting.baseUrl && ` · ${resolvedWriting.baseUrl}`}
          {' · '} {profile.image.provider} / {profile.image.model}
          {' · '}video {profile.video.model} · {profile.video.settings.resolution} {profile.video.settings.aspectRatio}
        </p>
      )}
      <fieldset disabled={project.provider.useGlobalProfile} className="space-y-3 disabled:opacity-50">
      <label className="block text-[10px] text-text-muted">Writing LLM
        <select className={`${input} mt-1`} value={provider} onChange={event => setProvider(event.target.value as StoryWritingProvider)}>
          <option value="maestro">Maestro internal · default</option>
          <option value="deepseek">DeepSeek</option>
          <option value="minimax">MiniMax</option>
          <option value="openai">OpenAI</option>
          <option value="openai-compatible">Custom OpenAI-compatible</option>
        </select>
      </label>
      <p className={`text-[10px] ${writingReady ? 'text-emerald-400' : 'text-amber-300'}`}>
        {writingReady ? 'Writing provider ready.' : 'Missing provider credentials in Settings → Services.'}
      </p>
      {provider !== 'maestro' && (
        <label className="block text-[10px] text-text-muted">Writing model
          {provider === 'deepseek' ? (
            <select className={`${input} mt-1`} value={project.provider.writingModel || 'deepseek-v4-pro'} onChange={event => patchProvider({ writingModel: event.target.value })}>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
            </select>
          ) : provider === 'minimax' ? (
            <select className={`${input} mt-1`} value={project.provider.writingModel || 'MiniMax-M3'} onChange={event => patchProvider({ writingModel: event.target.value })}>
              <option value="MiniMax-M3">MiniMax M3</option>
              <option value="MiniMax-M2.7">MiniMax M2.7</option>
              <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed</option>
            </select>
          ) : (
            <input className={`${input} mt-1`} value={project.provider.writingModel} onChange={event => patchProvider({ writingModel: event.target.value })} />
          )}
        </label>
      )}
      <label className="block text-[10px] text-text-muted">Concept-art provider
        <select className={`${input} mt-1`} value={project.provider.imageProvider} onChange={event => patchProvider({ imageProvider: event.target.value as 'maestro' | 'minimax' })}>
          <option value="maestro">Maestro local</option>
          <option value="minimax">MiniMax Image</option>
        </select>
      </label>
      {project.provider.imageProvider === 'maestro' && (
        <label className="block text-[10px] text-text-muted">Maestro image model
          <select
            className={`${input} mt-1`}
            value={project.provider.imageModel}
            onChange={event => patchProvider({ imageModel: event.target.value })}
          >
            {!installedImageModels.some(model => model.model_type === project.provider.imageModel)
              && <option value={project.provider.imageModel}>{project.provider.imageModel || 'Select an installed model'} · unavailable</option>}
            {installedImageModels.map(model => (
              <option key={model.model_type} value={model.model_type}>{model.name}</option>
            ))}
          </select>
        </label>
      )}
      <p className={`text-[10px] ${imageReady ? 'text-emerald-400' : 'text-amber-300'}`}>
        {imageReady
          ? project.provider.imageProvider === 'minimax'
            ? 'MiniMax Image is ready (fixed provider image model).' : 'Local image model is installed.'
          : project.provider.imageProvider === 'minimax'
            ? 'Add the MiniMax API key in Settings → Services.'
            : 'Choose an installed Maestro image model.'}
      </p>
      </fieldset>
    </div>
  )
}

function ReferenceGallery({
  ids, assets, primaryId, onPrimary, onRemove,
}: {
  ids: string[]
  assets: Record<string, StoryVisualAsset>
  primaryId?: string
  onPrimary?: (id: string) => void
  onRemove: (id: string) => void
}) {
  const [previewId, setPreviewId] = useState<string | null>(null)
  const previewAsset = previewId ? assets[previewId] : undefined

  useEffect(() => {
    if (!previewAsset) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('keydown', closeOnEscape)
      document.body.style.overflow = previousOverflow
    }
  }, [previewAsset])

  const confirmRemove = (id: string, asset: StoryVisualAsset) => {
    if (!window.confirm(
      `¿Quitar “${asset.name || 'esta imagen'}” de este bloque? Si no se utiliza en otro lugar, también se eliminará de la biblioteca de Story Lab.`,
    )) return
    onRemove(id)
  }

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
        {ids.map(id => {
          const asset = assets[id]
          if (!asset) return null
          return (
            <div key={id} className={`relative rounded-lg overflow-hidden border ${id === primaryId ? 'border-emerald-400' : 'border-border'} bg-bg-tertiary`}>
              <img src={asset.source} alt={asset.name} className="w-full aspect-square object-cover" />
              <span className={`absolute right-1 top-1 rounded border px-1 py-0.5 text-[8px] ${asset.approval === 'approved'
                ? 'border-emerald-400/70 bg-emerald-950/80 text-emerald-200'
                : 'border-amber-400/60 bg-amber-950/80 text-amber-200'}`}>
                {asset.approval === 'approved' ? 'Approved' : 'Draft'}
              </span>
              <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-black/65 p-1">
                {onPrimary && <button type="button" className="text-[9px] text-white" onClick={() => onPrimary(id)}>{id === primaryId ? 'Primary' : 'Use as primary'}</button>}
                <button
                  type="button"
                  className="ml-auto rounded p-1 text-white hover:bg-white/15"
                  onClick={() => setPreviewId(id)}
                  title="Ampliar imagen"
                  aria-label={`Ampliar ${asset.name || 'imagen'}`}
                >
                  <Maximize2 size={13} />
                </button>
                <button
                  type="button"
                  className="rounded p-1 text-red-300 hover:bg-red-500/20"
                  onClick={() => confirmRemove(id, asset)}
                  title="Quitar imagen"
                  aria-label={`Quitar ${asset.name || 'imagen'}`}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          )
        })}
      </div>
      {previewAsset && createPortal(
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-black/85 p-4 md:p-8"
          onClick={() => setPreviewId(null)}
          role="presentation"
        >
          <div
            className="flex max-h-[94vh] max-w-[96vw] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
            onClick={event => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="story-image-preview-title"
          >
            <div className="flex items-center gap-3 border-b border-border px-3 py-2.5">
              <h2 id="story-image-preview-title" className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">
                {previewAsset.name || 'Imagen de Story Lab'}
              </h2>
              <button
                type="button"
                onClick={() => setPreviewId(null)}
                className="rounded-lg p-1.5 text-text-muted hover:bg-bg-hover hover:text-text-primary"
                title="Cerrar"
                aria-label="Cerrar imagen ampliada"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex min-h-0 items-center justify-center bg-black/35 p-2">
              <img
                src={previewAsset.source}
                alt={previewAsset.name || 'Imagen ampliada de Story Lab'}
                className="max-h-[84vh] max-w-[92vw] object-contain"
              />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function SectionHeader({
  title, description, scope, busy, approved, instruction, setInstruction, onGenerate, onApprove,
}: {
  title: string
  description: string
  scope: StoryGenerationScope
  busy: StoryGenerationScope | null
  approved: boolean
  instruction: string
  setInstruction: (value: string) => void
  onGenerate: (scope: StoryGenerationScope) => void
  onApprove: () => void
}) {
  return (
    <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3 mb-4">
      <div>
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        <p className="text-xs text-text-muted mt-1">{description}</p>
      </div>
      <div className="lg:max-w-[680px]">
        <div className="flex flex-col sm:flex-row gap-2">
          <input className={`${input} sm:w-72`} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="Optional regeneration instruction…" />
          <button className={button} disabled={Boolean(busy)} onClick={() => onGenerate(scope)}
            title="Uses the LLM to generate or rewrite this section's text. It does not generate images.">
            {busy === scope ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate text
          </button>
          <button className={`${button} ${approved ? 'border-emerald-500 text-emerald-400' : ''}`} onClick={onApprove}
            title="Confirms the current version of this section. It does not generate content.">
            <Check size={13} /> {approved ? 'Approved' : 'Approve'}
          </button>
        </div>
        <p className="mt-1.5 text-[9px] leading-relaxed text-text-muted">
          LLM text only: generates or rewrites this section's fields and preserves existing image references; it does not render images. Guided mode lets you review the draft before applying it. Approve only confirms the current version.
        </p>
      </div>
    </div>
  )
}

export function StoryLabPanel() {
  const project = useStoryStore(state => state.project)
  const productionProfile = useStore(state => state.productionProfile)
  const projects = useStoryStore(state => state.projects)
  const dirty = useStoryStore(state => state.dirty)
  const storyHydrated = useStoryStore(state => state.hydrated)
  const storyLoading = useStoryStore(state => state.loading)
  const storySaveError = useStoryStore(state => state.saveError)
  const loadWorkspace = useStoryStore(state => state.loadWorkspace)
  const openProject = useStoryStore(state => state.openProject)
  const duplicateProject = useStoryStore(state => state.duplicateProject)
  const deleteProject = useStoryStore(state => state.deleteProject)
  const patch = useStoryStore(state => state.patchProject)
  const update = useStoryStore(state => state.updateProject)
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
  const [busy, setBusy] = useState<StoryGenerationScope | null>(null)
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
    const musicModel = productionProfile.music.model === 'music-2.6' ? 'music-2.6' : 'music-3.0'
    if (
      project.provider.writingProvider === writingProvider
      && project.provider.writingModel === productionProfile.text.model
      && project.provider.writingBaseUrl === writingBaseUrl
      && project.provider.imageProvider === imageProvider
      && project.provider.imageModel === productionProfile.image.model
      && project.music.model === musicModel
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
      music: { ...project.music, model: musicModel },
    })
  }, [
    patch,
    productionProfile.image.model,
    productionProfile.image.provider,
    productionProfile.music.model,
    productionProfile.text.model,
    productionProfile.text.provider,
    project.music,
    project.provider,
  ])
  const beginStoryActivity = (phase: string, message: string, total = 0) => {
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
      ? 'Maestro internal'
      : project.provider.writingModel || project.provider.writingProvider
    const title = `Story Lab · ${project.title.trim() || 'Untitled story'} · ${writer}`
    return createStoryActivityLifecycle({
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
  const directVideo = project.musicVideoGenerationMode === 'direct_video'
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
  }, [activeWorkspace, project.id])

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
  ) => {
    const chosen = new Set(selected)
    update(current => {
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
    window.localStorage.removeItem(storyResultKey(activeWorkspace, project.id))
    window.localStorage.removeItem(storyJobKey(activeWorkspace, project.id))
    setRecoveryJobId('')
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
      ? overview.title.trim() : project.title || 'Untitled story'
    setNotice({
      kind: 'ok',
      text: `Applied to “${appliedTitle}”: ${characterCount} characters · ${locationCount} locations · ${structure.length} moments · ${musicCount} song${musicCount === 1 ? '' : 's'}.`,
    })
  }

  const generateMissingImagesForScope = async (scope: StoryGenerationScope): Promise<boolean> => {
    const current = useStoryStore.getState().project
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
    applyGeneratedResult(result)
    if (scope === 'all') {
      if (options.generateImages && !await generateMissingImagesForScope(scope)) return
      if (!options.generateImages) {
        setNotice({ kind: 'ok', text: 'Text preparation completed. No images were generated.' })
      }
      setTab(project.projectType === 'music_video' ? 'music' : project.projectType === 'trailer' ? 'trailer' : 'productions')
    } else if (options.generateImages) {
      await generateMissingImagesForScope(scope)
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
      await completeGeneratedDraft(scope, result, options)
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
    applyGeneratedResult(result, selected, replaceCollections)
    if (generateImagesAfterApply && !await generateMissingImagesForScope(scope)) return
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
  ) => {
    update(current => {
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
    } = {},
  ) => {
    if (!prompt.trim()) return
    const key = `${target.kind}:${target.id || 'world'}`
    const current = useStoryStore.getState().project
    const globalProfile = useStore.getState().productionProfile
    const effectiveImageProvider = current.provider.useGlobalProfile && globalProfile.image.provider === 'minimax'
      ? 'minimax' : current.provider.imageProvider
    const effectiveImageModel = current.provider.useGlobalProfile
      ? globalProfile.image.model : current.provider.imageModel
    const sourceProjectId = current.id
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
            update(latest => {
              if (latest.id !== sourceProjectId) return latest
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
      }, target, options.replaceReferences)
      update(latest => {
        if (latest.id !== sourceProjectId) return latest
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
        update(latest => {
          if (latest.id !== sourceProjectId) return latest
          delete latest.visualJobs[jobKey]
          return latest
        })
      }
      options.onError?.(message)
      if (!options.quiet) setNotice({ kind: 'error', text: message })
      return false
    } finally {
      setImageBusy('')
    }
  }

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
    const current = useStoryStore.getState().project
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
    setImageBusy('upload')
    try {
      for (const file of Array.from(files)) {
        const uploaded = await api.uploadImage(file)
        addAsset({
          id: storyId('asset'), name: file.name, source: uploaded.url, prompt: '',
          provider: 'upload', createdAt: new Date().toISOString(),
          approval: 'draft', variantKind: 'original',
        }, uploadTarget)
      }
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      setImageBusy('')
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const analyzeSmartAssets = async (files: File[]) => {
    const images = files.filter(file => file.type.startsWith('image/')).slice(0, 24)
    if (!images.length) {
      setNotice({ kind: 'error', text: 'Choose one or more image files.' })
      return
    }
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
        project,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
        activity_id: activity.id,
      })
      setPendingSmartAssets(result.assets.map(item => ({ ...item, selected: item.kind !== 'ignore' })))
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
      setNotice({ kind: 'ok', text: `Downloading ${selectedStyleModel.name}. You can keep using Maestro while it installs.` })
    } catch (error) {
      setStyleModelDownloading('')
      setStyleModelDownloadError((error as Error).message)
    }
  }

  const convertSelectedAssetsToStyle = async () => {
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
        update(current => {
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
  }

  const importStorypack = async (file?: File) => {
    if (!file) return
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
      setProject(normalized)
      setNotice({ kind: 'ok', text: 'Story project imported with its editable bible and available visual references.' })
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
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
    if (videoModel.startsWith('minimax_h3')) {
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
    setProductionBusy('film')
    try {
      const adaptation = await loadFilmProduction(
        project,
        filmDirection,
        autoStart,
        filmDuration,
        filmPreserveVisualStyle,
      )
      patch({
        productions: [...project.productions, {
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
      })
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
      setProductionBusy(null)
    }
  }

  const stageTrailer = async (autoStart = false) => {
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
      patch({
        productions: [...project.productions, {
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
      })
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
      setProductionBusy(null)
    }
  }

  const writeStorySong = async () => {
    const activity = beginStoryActivity('writing_song', 'Story Lab is writing the song prompt and lyrics…', 1)
    setProductionBusy('music')
    try {
      const brief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds)
      const written = await api.writeSong({
        ...musicWritingProviderParams,
        target: 'minimax',
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: brief,
        style_direction: project.music.style || `${project.genre}, ${project.tone}`,
        lyrics_direction: project.music.lyrics || project.music.sourceLyrics,
        story_context: storySongBrief(project, project.music.targetDurationSeconds),
        language: project.language,
        duration_seconds: project.music.targetDurationSeconds,
      })
      patch({
        music: {
          ...project.music,
          brief,
          style: written.style,
          lyrics: written.lyrics,
          lyricsLanguage: project.language,
        },
      })
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
        target: 'minimax',
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: 'Write completely original replacement lyrics for this Story. Keep only the broad section order, approximate meter and singability of the authorized source; do not copy distinctive wording, names or lines.',
        style_direction: project.music.style || storyBrief,
        lyrics_direction: sourceLyrics,
        story_context: storySongBrief(project, project.music.targetDurationSeconds),
        language: project.language,
        duration_seconds: project.music.targetDurationSeconds,
      })
      patch({
        music: {
          ...project.music,
          brief: storyBrief,
          style: written.style || project.music.style,
          lyrics: written.lyrics,
          lyricsLanguage: project.language,
        },
      })
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
    if (file.size > 50 * 1024 * 1024) {
      setNotice({ kind: 'error', text: 'MiniMax Cover accepts reference audio up to 50 MB.' })
      return
    }
    const activity = beginStoryActivity('uploading_music_reference', `Uploading cover reference “${file.name}”…`, 1)
    setProductionBusy('music')
    try {
      const uploaded = await api.uploadAudio(file)
      patch({
        music: {
          ...project.music,
          mode: 'cover',
          coverReferenceFilename: uploaded.filename,
          coverReferenceName: file.name,
        },
      })
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
          target: 'minimax',
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
      patch({
        music: {
          ...project.music,
          brief,
          style,
          lyrics,
          lyricsLanguage: project.music.lyricsLanguage || project.language,
          candidates: [...project.music.candidates, ...candidates],
          selectedCandidateId: candidates[0]?.id || project.music.selectedCandidateId,
        },
      })
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

  const patchMusicCue = (cueId: string, changes: Partial<StoryMusicCue>) => {
    update(current => {
      const cue = current.music.cues.find(item => item.id === cueId)
      if (cue) Object.assign(cue, changes)
      return current
    })
  }

  const translateMusicCueLyrics = async (cueId: string) => {
    const cue = useStoryStore.getState().project.music.cues.find(item => item.id === cueId)
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
      patchMusicCue(cueId, { lyrics: translated.lyrics, lyricsLanguage: translated.targetLanguage })
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
      patch({ music: { ...project.music, lyrics: translated.lyrics, lyricsLanguage: translated.targetLanguage } })
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
  ) => {
    const latest = useStoryStore.getState().project
    const targetLanguage = requestedLanguage.trim() || cue.lyricsLanguage || latest.language
    const targetStyle = requestedStyle.trim() || cue.style || cue.brief
    const target = cue.kind === 'character'
      ? latest.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
      : cue.kind === 'world' ? 'the Story world' : 'the complete Story'
    return api.writeSong({
      writingProvider: latest.provider.writingProvider,
      writingModel: latest.provider.writingModel,
      writingBaseUrl: latest.provider.writingBaseUrl,
      target: 'minimax',
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
      const rewritten = await rewriteMusicCueDraft(cue, instruction, '')
      if (existingCue) {
        patchMusicCue(cue.id, rewritten)
      } else {
        update(latest => {
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
    const cue = useStoryStore.getState().project.music.cues.find(item => item.id === cueId)
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
      const rewritten = await rewriteMusicCueDraft(cue, requestedStyle, requestedLanguage)
      patchMusicCue(cueId, rewritten)
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
    const cues = useStoryStore.getState().project.music.cues
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
        const currentCue = useStoryStore.getState().project.music.cues.find(item => item.id === cues[index].id)
        if (!currentCue) continue
        activity.update(`Rewriting “${currentCue.title}” · ${index + 1}/${cues.length}`, 'writing_song', index, cues.length)
        const rewritten = await rewriteMusicCueDraft(currentCue, requestedStyle, requestedLanguage)
        patchMusicCue(currentCue.id, rewritten)
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
        target: 'minimax',
        model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
        description: 'Create a complete new version of this Story song. Recompose the arrangement and rewrite every lyric line from scratch; preserve only its Story meaning and emotional progression.',
        style_direction: requestedStyle || project.music.style || `${project.genre}, ${project.tone}`,
        lyrics_direction: `Write entirely new lyrics in ${targetLanguage}. Treat these previous lyrics only as narrative source material and do not copy their lines:\n\n${project.music.lyrics}`,
        story_context: storySongBrief(project, project.music.targetDurationSeconds, targetLanguage),
        language: targetLanguage,
        duration_seconds: project.music.targetDurationSeconds,
      })
      patch({
        music: {
          ...project.music,
          style: written.style,
          lyrics: written.lyrics,
          lyricsLanguage: targetLanguage,
        },
      })
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
    const cue = useStoryStore.getState().project.music.cues.find(item => item.id === cueId)
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
        target: 'minimax',
        model: project.music.model,
        instrumental: cue.instrumental,
        description: `Create an entirely original ${cue.instrumental ? 'instrumental music cue' : 'song'} for ${target}. Purpose in this Story: ${cue.purpose}.`,
        reference_song: cue.referenceSong,
        style_direction: cue.brief,
        lyrics_direction: cue.lyrics,
        story_context: storySongBrief(project, cue.durationSeconds, lyricsLanguage),
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
      })
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
    const cue = useStoryStore.getState().project.music.cues.find(item => item.id === cueId)
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
      update(current => {
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
    const current = useStoryStore.getState().project
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
      update(latest => {
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
    if (!servicesConfig?.minimax_api_key_set) {
      setNotice({ kind: 'error', text: 'Add the MiniMax API key in Settings → Services first.' })
      return false
    }
    const current = useStoryStore.getState().project
    const cue = current.music.cues.find(item => item.id === cueId)
    if (!cue) return false
    if (!cue.style.trim() || (!cue.instrumental && !cue.lyrics.trim())) {
      setNotice({ kind: 'error', text: `Review or adapt the prompt${cue.instrumental ? '' : ' and lyrics'} for “${cue.title}” first.` })
      return false
    }
    if (!cue.instrumental && !MINIMAX_LYRIC_SECTION.test(cue.lyrics)) {
      setNotice({
        kind: 'error',
        text: `“${cue.title}” needs [Verse], [Chorus] or another supported section tag before MiniMax generation. Adapt it with the LLM or edit the lyrics first.`,
      })
      return false
    }
    const activity = queued
      ? null
      : beginStoryActivity('generating_music', `MiniMax Music is generating “${cue.title}”…`, 1)
    setMusicCueBusy(`audio:${cueId}`)
    try {
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
      update(latest => {
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
    store.setDirectorShotImageGuidance(directReferences ? 'prompt_only' : 'auto')
    if (generationSettings.videoModel.startsWith('minimax_h3')) {
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
    const blob = await fetch(candidate.source).then(response => {
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
      director.setDirectorShotImageGuidance(project.musicVideoGenerationMode === 'direct_references' ? 'prompt_only' : 'auto')
      if (filmVideoModel.startsWith('minimax_h3')) {
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
        generationMode: project.musicVideoGenerationMode,
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
        patch({
          productions: [...project.productions, {
            id: storyId('production'),
            kind: 'music_video',
            title: `${loaded.adaptation.focusLabel} · ${options.mode === 'trailer' ? 'musical trailer' : 'music video'}`,
            createdAt: new Date().toISOString(),
            sourceVersion: project.revision,
            sourceSnapshot: { ...structuredClone(project), productions: [] },
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
        })
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
          disabled={Boolean(busy || imageBusy)}
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
          disabled={Boolean(busy || imageBusy)}
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
              <button key={item.id} type="button" disabled={Boolean(busy || imageBusy)}
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
        <button className={button} disabled={Boolean(busy || imageBusy)} onClick={() => duplicateProject()} title="Duplicate current story">Duplicate</button>
        <button className={button} onClick={() => {
          if (window.confirm(`Delete "${project.title}" from this workspace's Story Lab library?`)) deleteProject(project.id)
        }} disabled={Boolean(busy || imageBusy)} title="Delete current story"><Trash2 size={13} /></button>
        <input ref={importRef} type="file" accept=".storypack,.zip,.json" className="hidden" onChange={event => importStorypack(event.target.files?.[0])} />
      </div>

      {notice && (
        <div className={`px-3 py-2 text-xs border-b border-border ${notice.kind === 'error' ? 'text-red-300 bg-red-500/10' : 'text-emerald-300 bg-emerald-500/10'}`}>
          {notice.text}
        </div>
      )}
      <div className="flex-1 min-h-0 flex">
        <nav className="w-36 md:w-48 shrink-0 border-r border-border bg-bg-secondary p-2 overflow-y-auto">
          {tabs.map(item => (
            <button key={item.id} onClick={() => setTab(item.id)} className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs mb-1 ${tab === item.id ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'}`}>
              <item.icon size={14} /> {item.label}
            </button>
          ))}
          <div className="mt-4 border-t border-border pt-3 text-[9px] text-text-muted space-y-1.5">
            {project.projectType === 'full_story' ? (
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
          </div>
        </nav>

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
                <div id="story-review-overview" className="scroll-mt-4">
                  <SectionHeader
                    title={project.projectType === 'music_video'
                      ? 'Canción e historia visual'
                      : project.projectType === 'trailer'
                        ? 'Concepto de tráiler cinematográfico'
                        : project.projectType === 'quick_video' ? 'Concepto de vídeo rápido' : 'Story and intent'}
                    description={project.projectType === 'music_video'
                      ? 'Con cinco decisiones podemos escribir la canción y preparar un videoclip coherente.'
                      : project.projectType === 'trailer'
                        ? 'Define la película, protagonistas, conflicto, promesa y gancho sin revelar el desenlace.'
                      : project.projectType === 'quick_video'
                        ? 'Una idea directa, sus protagonistas, el lugar y lo que debe ocurrir.'
                        : 'Define what the story is about before choosing shots or panels.'}
                    scope="overview" busy={busy} approved={isApproved('overview')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('overview')}
                  />
                </div>
                <div className={`${panel} mb-4 border-accent-blue/30 bg-accent-blue/5`}>
                  <Field
                    required
                    label="Idea general, estilo, avatar y prompts de referencia"
                    value={project.creativeBrief.generalIdea}
                    onChange={generalIdea => patch({ creativeBrief: { ...project.creativeBrief, generalIdea } })}
                    rows={9}
                    placeholder="Describe libremente el proyecto. Puedes indicar protagonista/avatar, época, estilo, propósito y pegar un prompt que ya te funcionó como guía. Story Lab separará identidad, dirección artística, canción y acciones sin repetir literalmente el ejemplo en cada plano."
                  />
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <p className="text-[10px] text-text-muted">El LLM interpreta este texto y propone cada campo; en modo Guided puedes aprobarlos uno a uno.</p>
                    <button type="button" className={`${button} ${requiredPreparationButton}`} disabled={Boolean(busy)} onClick={() => generate('all')}>
                      <Sparkles size={13} /> Interpretar y rellenar todo
                    </button>
                  </div>
                </div>
                {project.projectType === 'music_video' && (
                  <div className={`${panel} mb-4 grid md:grid-cols-2 gap-3 border-pink-500/20`}>
                    <div className="md:col-span-2"><Field required label="Contexto" value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={4} placeholder="Dónde nace la canción, situación, época, atmósfera y cualquier dato imprescindible." /></div>
                    <Field required label="Artista / quién canta, graba o produce" value={project.creativeBrief.performer} onChange={performer => patch({ creativeBrief: { ...project.creativeBrief, performer } })} rows={3} placeholder="Voz, personalidad artística, presencia escénica o productor." />
                    <Field required label="Estilo musical" value={project.creativeBrief.musicStyle} onChange={musicStyle => patch({ creativeBrief: { ...project.creativeBrief, musicStyle }, music: { ...project.music, style: musicStyle } })} rows={3} placeholder="Género, instrumentación, voz, energía y producción." />
                    <div className="md:col-span-2"><Field required label="Qué queremos que cuente la canción" value={project.creativeBrief.songStory} onChange={songStory => patch({ creativeBrief: { ...project.creativeBrief, songStory }, music: { ...project.music, brief: songStory } })} rows={5} placeholder="Historia, punto de vista, emoción inicial, cambio y recuerdo final." /></div>
                    <label className="block text-[10px] text-text-muted">
                      Duración objetivo · {project.creativeBrief.durationSeconds}s
                      <input type="range" min={30} max={360} step={5} className="mt-2 w-full accent-accent-blue" value={project.creativeBrief.durationSeconds}
                        onChange={event => {
                          const durationSeconds = Number(event.target.value)
                          patch({ creativeBrief: { ...project.creativeBrief, durationSeconds }, music: { ...project.music, targetDurationSeconds: durationSeconds } })
                        }} />
                    </label>
                    <p className="self-end text-[10px] text-text-muted">El LLM generará una canción, un intérprete visualizable, un mundo compacto y 4–10 momentos utilizables como planos.</p>
                  </div>
                )}
                {project.projectType === 'trailer' && (
                  <div className={`${panel} mb-4 grid gap-3 border-amber-500/20 md:grid-cols-2`}>
                    <div className="md:col-span-2"><Field required label="Contexto de la película" value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={4} placeholder="Época, situación inicial, género, tono y aquello que el público debe comprender." /></div>
                    <Field required label="Protagonistas y antagonistas" value={project.creativeBrief.subjects} onChange={subjects => patch({ creativeBrief: { ...project.creativeBrief, subjects } })} rows={4} placeholder="Quién conduce la película, qué desea y quién o qué se le opone." />
                    <Field required label="Mundo y localizaciones" value={project.creativeBrief.setting} onChange={setting => patch({ creativeBrief: { ...project.creativeBrief, setting } })} rows={4} placeholder="El mundo visual de la película y sus localizaciones esenciales." />
                    <div className="md:col-span-2"><Field required label="Conflicto, promesa y material del tráiler" value={project.creativeBrief.action} onChange={action => patch({ creativeBrief: { ...project.creativeBrief, action } })} rows={5} placeholder="Qué amenaza irrumpe, qué grandes imágenes o decisiones deben prometerse y qué misterio debe quedar abierto." /></div>
                    <label className="block text-[10px] text-text-muted">
                      Duración objetivo · {project.creativeBrief.durationSeconds}s
                      <input type="range" min={15} max={180} step={5} className="mt-2 w-full accent-amber-400" value={project.creativeBrief.durationSeconds}
                        onChange={event => {
                          const durationSeconds = Number(event.target.value)
                          setTrailerDuration(durationSeconds)
                          patch({ creativeBrief: { ...project.creativeBrief, durationSeconds } })
                        }} />
                    </label>
                    <p className="self-end text-[10px] text-text-muted">El LLM preparará concepto, mundo, protagonistas y 6–12 momentos de tráiler. No escribirá ni exigirá una canción.</p>
                  </div>
                )}
                {project.projectType === 'quick_video' && (
                  <div className={`${panel} mb-4 grid md:grid-cols-2 gap-3 border-cyan-500/20`}>
                    <div className="md:col-span-2"><Field required label="Contexto" value={project.creativeBrief.context} onChange={context => patch({ creativeBrief: { ...project.creativeBrief, context } })} rows={3} placeholder="Qué está pasando y qué debe entender el espectador sin explicación adicional." /></div>
                    <Field required label="Protagonistas" value={project.creativeBrief.subjects} onChange={subjects => patch({ creativeBrief: { ...project.creativeBrief, subjects } })} rows={3} placeholder="Por ejemplo: Trump y Marco Rubio." />
                    <Field required label="Lugar" value={project.creativeBrief.setting} onChange={setting => patch({ creativeBrief: { ...project.creativeBrief, setting } })} rows={3} placeholder="Por ejemplo: despacho de la Casa Blanca, de día." />
                    <div className="md:col-span-2"><Field required label="Qué ocurre / diálogo" value={project.creativeBrief.action} onChange={action => patch({ creativeBrief: { ...project.creativeBrief, action } })} rows={5} placeholder="Acción, conversación, remate o mensaje que debe aparecer." /></div>
                    <label className="block text-[10px] text-text-muted">Formato
                      <select className={`${input} mt-1`} value={project.creativeBrief.quickFormat}
                        onChange={event => patch({ creativeBrief: { ...project.creativeBrief, quickFormat: event.target.value as StoryProject['creativeBrief']['quickFormat'] } })}>
                        <option value="dialogue">Diálogo</option><option value="meme">Meme</option><option value="parody">Parodia</option>
                        <option value="sketch">Sketch</option><option value="viral">Viral</option><option value="announcement">Anuncio</option>
                      </select>
                    </label>
                    <label className="block text-[10px] text-text-muted">
                      Duración objetivo · {project.creativeBrief.durationSeconds}s
                      <input type="range" min={5} max={120} step={5} className="mt-2 w-full accent-accent-blue" value={project.creativeBrief.durationSeconds}
                        onChange={event => patch({ creativeBrief: { ...project.creativeBrief, durationSeconds: Number(event.target.value) } })} />
                    </label>
                  </div>
                )}
                <div className="grid xl:grid-cols-[1fr_360px] gap-4">
                  <div className={`${panel} grid md:grid-cols-2 gap-3`}>
                    <Field required label="Title" value={project.title} onChange={title => patch({ title })} />
                    <label className="block text-[10px] text-violet-200">
                      Language<span className="ml-1 text-violet-300" title="Required">●</span>
                      <EditableLanguageInput
                        className={`${input} ${requiredInput} mt-1`}
                        value={project.language}
                        onChange={language => patch({ language })}
                        required
                      />
                    </label>
                    <label className="block text-[10px] text-violet-200">
                      Idioma hablado del vídeo
                      <select className={`${input} mt-1`} value={project.spokenLanguage} onChange={event => patch({ spokenLanguage: event.target.value })}>
                        <option value="">Automático según el diálogo</option>
                        <option value="Español de España">Español de España</option>
                        <option value="Español latinoamericano">Español latinoamericano</option>
                        <option value="English">English</option>
                        <option value="French">Français</option>
                        <option value="Italian">Italiano</option>
                      </select>
                      <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">Fuerza el idioma en cada prompt. El acento regional depende de la adherencia del modelo.</span>
                    </label>
                    {project.projectType === 'music_video' && <label className="block text-[10px] text-violet-200">
                      Variedad de localizaciones
                      <select className={`${input} mt-1`} value={project.locationVariety} onChange={event => patch({ locationVariety: event.target.value as StoryProject['locationVariety'] })}>
                        <option value="balanced">Equilibrada · mínimo 3 entornos</option>
                        <option value="single_location">Una sola localización intencionada</option>
                      </select>
                    </label>}
                    <div className="md:col-span-2 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 space-y-2">
                      <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
                        <input type="checkbox" checked={project.protagonistConsistency} onChange={event => patch({ protagonistConsistency: event.target.checked, protagonistCharacterId: event.target.checked ? (project.protagonistCharacterId || project.characters[0]?.id || '') : project.protagonistCharacterId, ...(event.target.checked && project.musicVideoGenerationMode === 'direct_video' ? { musicVideoGenerationMode: 'image_guided' as const } : {}) })} className="mt-0.5 accent-violet-400" />
                        <span><span className="block text-violet-200">Crear primero y fijar protagonista</span><span className="block text-[9px] text-text-muted">Opcional. Exige una identidad principal aprobada y la coloca como primera referencia en todos los vídeos compatibles.</span></span>
                      </label>
                      {project.protagonistConsistency && <select className={input} value={project.protagonistCharacterId} onChange={event => patch({ protagonistCharacterId: event.target.value })}>
                        <option value="">Selecciona protagonista</option>
                        {project.characters.map(character => <option key={character.id} value={character.id}>{character.name || 'Sin nombre'}</option>)}
                      </select>}
                      {project.protagonistConsistency && <p className={`text-[9px] ${protagonistReferenceReady ? 'text-emerald-200' : 'text-amber-300'}`}>{protagonistReferenceReady ? 'Identidad principal aprobada y lista.' : 'Ve a Personajes, crea o sube la identidad del protagonista, selecciónala como principal y apruébala.'}</p>}
                    </div>
                    {promptHealthWarnings.length > 0 && <div className="md:col-span-2 rounded-lg border border-amber-500/35 bg-amber-500/5 p-3">
                      <p className="text-[10px] font-medium text-amber-200">Análisis preventivo del prompt</p>
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-[9px] leading-relaxed text-amber-100">{promptHealthWarnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
                    </div>}
                    {project.projectType === 'full_story' && (
                      <>
                        <Choice required label="Genre" value={project.genre} options={GENRES} onChange={genre => patch({ genre })} />
                        <Choice required label="Tone" value={project.tone} options={TONES} onChange={tone => patch({ tone })} />
                        <Field label="Audience" value={project.audience} onChange={audience => patch({ audience })} />
                        <Field label="Theme" value={project.theme} onChange={theme => patch({ theme })} />
                        <Field required label="What the story is about / premise" value={project.premise} onChange={premise => patch({ premise })} rows={5} placeholder="Who wants what, what stops them, and what happens if they fail?" />
                      </>
                    )}
                    <Field required label="Visual style / independent art direction" value={project.visualStyle} onChange={visualStyle => patch({ visualStyle })} rows={5} placeholder="For example: hand-painted 2D animation, watercolor backgrounds, clean ink contours, warm muted palette…" />
                    <div className="space-y-1.5">
                      <Field
                        required
                        label="Estilo visual de los personajes"
                        value={project.characterVisualStyle}
                        onChange={characterVisualStyle => patch({ characterVisualStyle })}
                        rows={5}
                        placeholder="Realistas, plastilina, anime… Describe aquí el material, proporciones y acabado que deben compartir todas las personas."
                      />
                      <div className="flex flex-wrap gap-1.5">
                        {CHARACTER_STYLE_PRESETS.map(([label, value]) => (
                          <button
                            key={label}
                            type="button"
                            className={`${button} px-2 py-1 text-[10px] ${project.characterVisualStyle === value ? 'border-accent-blue text-accent-blue' : ''}`}
                            onClick={() => patch({ characterVisualStyle: value, enforceVisualStyle: true })}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="md:col-span-2 rounded-lg border border-border bg-bg-tertiary/50 p-3 space-y-2">
                      <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={project.enforceVisualStyle}
                          onChange={event => patch({ enforceVisualStyle: event.target.checked })}
                        />
                        <span>
                          <span className="font-medium text-text-primary">Enforce these styles on every Story image</span>
                          <span className="block mt-0.5 text-[10px] text-text-muted">Adds the global art direction and character rendering as highest-priority locks, so every visible person keeps the selected medium.</span>
                        </span>
                      </label>
                      <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={project.allowClipText}
                          onChange={event => patch({ allowClipText: event.target.checked })}
                        />
                        <span>
                          <span className="font-medium text-text-primary">Permitir generar clips con textos</span>
                          <span className="block mt-0.5 text-[10px] text-text-muted">Desactivado por defecto. Las letras y diálogos siguen guiando el audio y la acción, pero no se convierten en subtítulos, carteles ni palabras visibles.</span>
                        </span>
                      </label>
                      <div className="flex flex-wrap gap-2">
                        <button className={button} disabled={!storyRenderStyle(project)} onClick={writeStyleIntoPrompts}>
                          <Palette size={13} /> Write/replace style lock in existing prompts
                        </button>
                        <button className={button} disabled={!storyRenderStyle(project) || !styledReferenceTargetCount || Boolean(imageBusy) || referenceBatchBusy} onClick={regenerateStyledReferences}>
                          <RefreshCcw size={13} /> Prepare {styledReferenceTargetCount} reference{styledReferenceTargetCount === 1 ? '' : 's'} for style conversion
                        </button>
                      </div>
                      <p className="text-[9px] leading-relaxed text-text-muted">
                        Opens all attached references in Images with the current art direction prefilled. Originals are preserved; new variants remain drafts until you approve them.
                      </p>
                    </div>
                    <div className="md:col-span-2 border-t border-border pt-3">
                      <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-text-muted">
                        {project.projectType === 'full_story' ? 'Story treatment' : 'Tratamiento generado y editable'}
                      </p>
                      <div className="space-y-3">
                        <Field label="Logline" value={project.logline} onChange={logline => patch({ logline })} rows={2} />
                        <Field label="Synopsis" value={project.synopsis} onChange={synopsis => patch({ synopsis })} rows={8} />
                        <Field label="Ending / final image" value={project.ending} onChange={ending => patch({ ending })} rows={3} />
                      </div>
                    </div>
                  </div>
                  <ProviderPanel project={project} patch={patch} onProfileModeChange={setStoryProfileMode} />
                </div>
                {project.projectType !== 'full_story' && (
                  <CompactVideoWorkspace
                    project={project}
                    update={update}
                    busy={busy}
                    imageBusy={imageBusy}
                    referenceBatchBusy={referenceBatchBusy}
                    generateSection={generate}
                    approveSection={approve}
                    isSectionApproved={isApproved}
                    generateVisual={generateVisual}
                    upload={target => {
                      setUploadTarget(target)
                      uploadRef.current?.click()
                    }}
                    removeReference={removeReference}
                    navigate={setTab}
                    requiresVisualIdentities={!directVideo}
                  />
                )}
              </>
            )}

            {tab === 'assets' && (
              <>
                <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Smart asset importer</h2>
                    <p className="mt-1 max-w-3xl text-xs text-text-muted">
                      Drop related images as one batch. The selected Story Lab LLM identifies characters, locations,
                      world references, props and style references, and groups alternate views before anything changes.
                    </p>
                  </div>
                  <div className="rounded-md border border-border bg-bg-tertiary px-3 py-2 text-[10px] text-text-muted">
                    Analyzer: {project.provider.writingProvider === 'maestro'
                      ? 'Maestro current LLM'
                      : `${project.provider.writingProvider} · ${project.provider.writingModel || 'configured model'}`}
                  </div>
                </div>

                <div className={`${panel} mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]`}>
                  <button
                    type="button"
                    disabled={smartAssetBusy}
                    className="min-h-44 rounded-xl border-2 border-dashed border-border bg-bg-tertiary/40 p-6 text-center transition-colors hover:border-accent-blue hover:bg-accent-blue/5 disabled:opacity-50"
                    onClick={() => smartAssetRef.current?.click()}
                    onDragOver={event => event.preventDefault()}
                    onDrop={event => {
                      event.preventDefault()
                      void analyzeSmartAssets(Array.from(event.dataTransfer.files))
                    }}
                  >
                    {smartAssetBusy
                      ? <Loader2 size={28} className="mx-auto mb-3 animate-spin text-accent-blue" />
                      : <Upload size={28} className="mx-auto mb-3 text-accent-blue" />}
                    <span className="block text-sm font-medium text-text-primary">
                      {smartAssetBusy ? 'Uploading and analyzing the batch…' : 'Drop images here or choose files'}
                    </span>
                    <span className="mt-2 block text-[10px] text-text-muted">
                      Up to 24 images per batch. Several views of one subject can be assigned to the same entity.
                    </span>
                  </button>
                  <div>
                    <Field
                      label="Optional context for the complete batch"
                      value={smartAssetDescription}
                      onChange={setSmartAssetDescription}
                      rows={6}
                      placeholder="For example: photos of Córdoba for a contemporary mystery; the woman in red is the protagonist and the old station is the main location."
                    />
                    <p className="mt-2 text-[9px] text-text-muted">
                      This context is sent once with the ordered image batch. Maestro proposes changes; you review every assignment below.
                    </p>
                  </div>
                </div>

                {pendingSmartAssets.length > 0 && (
                  <section className="mb-5">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-text-primary">Review proposed assignments</h3>
                        <p className="text-[10px] text-text-muted">Names, prompts, types and destinations remain editable. Uncheck anything you do not want to import.</p>
                      </div>
                      <div className="flex gap-2">
                        <button className={button} onClick={() => setPendingSmartAssets([])}>Discard batch</button>
                        <button className={`${button} border-emerald-500/50 text-emerald-300`}
                          disabled={!pendingSmartAssets.some(item => item.selected && item.kind !== 'ignore')}
                          onClick={applySmartAssets}>
                          <Check size={13} /> Apply selected
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {pendingSmartAssets.map((item, index) => {
                        const newKey = stableTextKey(`${item.name}-${index}`)
                        const targetOptions = item.kind === 'character'
                          ? [
                            ...project.characters.map(character => ({ id: character.id, label: `Existing · ${character.name}` })),
                            { id: item.targetId.startsWith('new-character:') ? item.targetId : `new-character:${newKey}`, label: `New character · ${item.name}` },
                          ]
                          : item.kind === 'location'
                            ? [
                              ...project.world.locations.map(location => ({ id: location.id, label: `Existing · ${location.name}` })),
                              { id: item.targetId.startsWith('new-location:') ? item.targetId : `new-location:${newKey}`, label: `New location · ${item.name}` },
                            ]
                            : [{ id: 'world', label: item.kind === 'prop' ? 'World library · prop' : item.kind === 'style' ? 'World library · style' : 'World references' }]
                        return (
                          <article key={`${item.source}-${index}`} className={`${panel} ${item.selected ? '' : 'opacity-60'}`}>
                            <div className="grid gap-3 lg:grid-cols-[140px_minmax(0,1fr)_minmax(260px,0.7fr)]">
                              <div>
                                <img src={item.source} alt={item.name} className="h-32 w-full rounded-lg border border-border object-cover" />
                                <label className="mt-2 flex items-center gap-2 text-[10px] text-text-secondary">
                                  <input type="checkbox" checked={item.selected}
                                    onChange={event => patchPendingSmartAsset(index, { selected: event.target.checked })} />
                                  Import this image
                                </label>
                                <p className="mt-1 truncate text-[9px] text-text-muted" title={item.nameOriginal}>{item.nameOriginal}</p>
                              </div>
                              <div className="space-y-3">
                                <Field label="Editable name" value={item.name}
                                  onChange={name => patchPendingSmartAsset(index, { name })} />
                                <Field label="What the image contains" value={item.description}
                                  onChange={description => patchPendingSmartAsset(index, { description })} rows={3} />
                                <Field label="Reusable visual prompt" value={item.visualPrompt}
                                  onChange={visualPrompt => patchPendingSmartAsset(index, { visualPrompt })} rows={3} />
                              </div>
                              <div className="space-y-3">
                                <label className="block text-[10px] text-text-muted">Asset type
                                  <select className={`${input} mt-1`} value={item.kind} onChange={event => {
                                    const kind = event.target.value as StoryAssetKind
                                    const targetId = kind === 'character'
                                      ? (project.characters[0]?.id || `new-character:${newKey}`)
                                      : kind === 'location'
                                        ? (project.world.locations[0]?.id || `new-location:${newKey}`)
                                        : 'world'
                                    patchPendingSmartAsset(index, { kind, targetId, selected: kind !== 'ignore' })
                                  }}>
                                    <option value="character">Character</option>
                                    <option value="location">Location</option>
                                    <option value="world">World</option>
                                    <option value="prop">Prop</option>
                                    <option value="style">Style reference</option>
                                    <option value="ignore">Ignore</option>
                                  </select>
                                </label>
                                {item.kind !== 'ignore' && (
                                  <label className="block text-[10px] text-text-muted">Destination
                                    <select className={`${input} mt-1`} value={targetOptions.some(option => option.id === item.targetId) ? item.targetId : targetOptions[0]?.id}
                                      onChange={event => patchPendingSmartAsset(index, { targetId: event.target.value })}>
                                      {targetOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
                                    </select>
                                  </label>
                                )}
                                <div className="rounded-md border border-border bg-bg-tertiary/60 p-2 text-[9px] text-text-muted">
                                  <p>Confidence: {Math.round(item.confidence * 100)}%</p>
                                  <p className="mt-1">{item.reason}</p>
                                </div>
                              </div>
                            </div>
                          </article>
                        )
                      })}
                    </div>
                  </section>
                )}

                <section className={`${panel} mb-5 border-violet-500/30 bg-violet-500/5`}>
                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div>
                      <h3 className="text-sm font-semibold text-violet-100">Convert selected images to a style</h3>
                      <p className="mt-1 text-[10px] leading-relaxed text-text-muted">
                        Choose the editing engine for this batch. Qwen prioritizes strict source preservation; Flux 2 Klein
                        performs fast four-step prompt-driven image editing; MiniMax preserves character identity but is not a scene editor.
                        Originals remain intact and every generated variant stays in Draft until you approve it.
                      </p>
                      <textarea
                        className={`${input} mt-3 min-h-24 resize-y`}
                        value={styleConversion}
                        onChange={event => setStyleConversion(event.target.value)}
                        placeholder="For example: GTA V promotional artwork, grounded proportions, saturated cinematic color grading, crisp painted edges…"
                        aria-label="Destination style for selected images"
                      />
                      {/photoreal|photo-real|fotorreal/i.test(styleConversion) && (
                        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-[9px] leading-relaxed text-amber-200">
                          If the inputs are already photographs, a photorealistic remake will look almost unchanged. For a GTA conversion, describe the target as a stylized game screenshot or painted promotional key art and avoid “photorealistic remake”.
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col justify-end gap-2">
                      <label className="block text-[10px] text-text-muted">Style conversion model
                        <select
                          className={`${input} mt-1`}
                          value={styleConversionModel}
                          disabled={styleConversionBusy || Boolean(styleModelDownloading)}
                          onChange={event => {
                            setStyleConversionModel(event.target.value)
                            setStyleModelDownloadError('')
                          }}
                        >
                          <optgroup label="External API">
                            <option value={MINIMAX_IMAGE_API_MODEL}>MiniMax Image-01 · characters only</option>
                          </optgroup>
                          <optgroup label="Maestro local · true image editing">
                            {localStyleModels.map(model => (
                              <option key={model.model_type} value={model.model_type}>
                                {model.name}{model.model_type === QWEN_STYLE_EDIT_MODEL ? ' · strict preservation' : model.model_type === FLUX_STYLE_EDIT_MODEL ? ' · fast 4-step edit' : ''}{model.is_downloaded ? ' · installed' : ' · not installed'}
                              </option>
                            ))}
                          </optgroup>
                        </select>
                      </label>
                      <div className="rounded-md border border-border bg-bg-primary/40 p-2 text-[10px] text-text-muted">
                        {styleAssetIds.length} image{styleAssetIds.length === 1 ? '' : 's'} selected · {styleUsesMiniMax
                          ? 'MiniMax Image-01 API · paid subject reference'
                          : `${selectedStyleModel?.name || styleConversionModel} · local · ${selectedStyleModel?.is_downloaded ? 'ready' : 'installation required'}`}
                      </div>
                      {!styleUsesMiniMax && !styleModelReady && !styleModelDownloading && (
                        <button className={`${button} border-sky-500/60 text-sky-200`} onClick={() => void installStyleConversionModel()}>
                          <Download size={13} /> Install selected local editor
                        </button>
                      )}
                      {styleModelDownloading && (
                        <div className="rounded-md border border-sky-500/40 bg-sky-500/5 p-2 text-[10px] text-sky-200">
                          <Loader2 size={12} className="mr-1 inline animate-spin" /> Downloading model files… progress is also shown in Activity.
                        </div>
                      )}
                      {styleModelDownloadError && <p className="text-[9px] text-red-300">{styleModelDownloadError}</p>}
                      {miniMaxIncompatibleSelection && (
                        <p className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-[9px] leading-relaxed text-amber-200">
                          This selection contains non-character images. MiniMax cannot preserve their layout; choose Qwen Image Edit or Flux 2 Klein.
                        </p>
                      )}
                      {styleConversionBusy ? (
                        <button className={`${button} border-amber-500/60 text-amber-200`} onClick={cancelStyleConversion}>
                          <Loader2 size={13} className="animate-spin" /> Stop after current image
                        </button>
                      ) : (
                        <button
                          className={`${button} border-violet-400/60 text-violet-200`}
                          disabled={!styleAssetIds.length || !styleConversion.trim() || !styleModelReady || miniMaxIncompatibleSelection || Boolean(styleModelDownloading)}
                          onClick={() => void convertSelectedAssetsToStyle()}
                        >
                          <Palette size={13} /> Convert selected to style
                        </button>
                      )}
                      <p className="text-[9px] leading-relaxed text-text-muted">
                        Qwen and Flux both send the original as the main landscape/subject (`KI`) and use the nearest supported aspect ratio. Flux freezes its distilled 4-step edit recipe. MiniMax remains available only for people and character identity.
                      </p>
                    </div>
                  </div>
                </section>

                <section>
                  <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-text-primary">Visual reference library · {Object.keys(project.assets).length}</h3>
                      <p className="mt-0.5 text-[9px] text-text-muted">
                        {Object.values(project.assets).filter(asset => asset.approval === 'approved').length} approved for Director. Newest images appear first; only approved images leave Story Lab with a production.
                      </p>
                    </div>
                    {Object.keys(project.assets).length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        <button
                          className={button}
                          onClick={() => setStyleAssetIds(styleAssetIds.length === Object.keys(project.assets).length
                            ? [] : Object.keys(project.assets))}
                        >
                          {styleAssetIds.length === Object.keys(project.assets).length ? 'Clear selection' : 'Select all'}
                        </button>
                        <button
                          className={`${button} border-red-500/60 text-red-300`}
                          disabled={!selectedDraftAssetIds.length || styleConversionBusy}
                          onClick={deleteSelectedDraftAssets}
                          title="Remove only the selected Draft records from this Story; approved images and Gallery files are protected"
                        >
                          <Trash2 size={13} /> Delete selected Draft ({selectedDraftAssetIds.length})
                        </button>
                      </div>
                    )}
                  </div>
                  {Object.keys(project.assets).length ? (
                    <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                      {visualAssetsNewestFirst.map(asset => (
                        <div key={asset.id} className={`${panel} p-2.5 ${asset.approval === 'approved' ? 'border-emerald-500/40' : ''}`}>
                          <div className="relative">
                            <img src={asset.source} alt={asset.name} className="h-44 w-full rounded-md border border-border object-cover" />
                            <label className="absolute left-2 top-2 flex items-center gap-1.5 rounded bg-black/75 px-2 py-1 text-[9px] text-white">
                              <input type="checkbox" checked={styleAssetIds.includes(asset.id)} onChange={() => toggleStyleAsset(asset.id)} />
                              Select
                            </label>
                            <span className={`absolute right-2 top-2 rounded border px-1.5 py-0.5 text-[9px] ${asset.approval === 'approved'
                              ? 'border-emerald-400/70 bg-emerald-950/80 text-emerald-200'
                              : 'border-amber-400/60 bg-amber-950/80 text-amber-200'}`}>
                              {asset.approval === 'approved' ? 'Approved' : 'Draft'}
                            </span>
                          </div>
                          <input className={`${input} mt-2`} value={asset.name}
                            onChange={event => patchVisualAsset(asset.id, { name: event.target.value })}
                            aria-label={`Name for ${asset.name}`} />
                          <div className="mt-1 flex flex-wrap items-center gap-1 text-[9px] uppercase tracking-wide text-text-muted">
                            <span>{asset.assetKind || asset.provider}</span>
                            <span>·</span>
                            <span>{asset.variantKind === 'styled' ? 'styled variant' : 'original'}</span>
                            {asset.model && <><span>·</span><span>{asset.provider}/{asset.model}</span></>}
                            <span>·</span><span>{new Date(asset.createdAt).toLocaleString()}</span>
                          </div>
                          <textarea className={`${input} mt-2 min-h-16 resize-y`} value={asset.description || ''}
                            onChange={event => patchVisualAsset(asset.id, { description: event.target.value })}
                            placeholder="What is visibly present in this image?" aria-label={`Description for ${asset.name}`} />
                          <textarea className={`${input} mt-2 min-h-20 resize-y`} value={asset.prompt}
                            onChange={event => patchVisualAsset(asset.id, { prompt: event.target.value })}
                            placeholder="Reusable prompt for this reference" aria-label={`Prompt for ${asset.name}`} />
                          {asset.stylePrompt && <p className="mt-1 text-[9px] text-violet-200">Style: {asset.stylePrompt}</p>}
                          <button
                            className={`${button} mt-2 w-full ${asset.approval === 'approved' ? 'border-emerald-500/60 text-emerald-300' : 'border-amber-500/50 text-amber-200'}`}
                            onClick={() => patchVisualAsset(asset.id, {
                              approval: asset.approval === 'approved' ? 'draft' : 'approved',
                            })}
                          >
                            <Check size={13} /> {asset.approval === 'approved' ? 'Approved for production' : 'Approve for production'}
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : <div className={`${panel} py-10 text-center text-xs text-text-muted`}>No visual assets have been imported yet.</div>}
                </section>
              </>
            )}

            {tab === 'world' && (
              <>
                <div id="story-review-world" className="scroll-mt-4">
                  <SectionHeader title="World bible" description="Rules, places and a visual language that every production can reuse." scope="world" busy={busy} approved={isApproved('world')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('world')} />
                </div>
                <div className={`${panel} grid md:grid-cols-2 gap-3`}>
                  <div className="md:col-span-2"><Field label="World summary" value={project.world.summary} onChange={summary => patch({ world: { ...project.world, summary } })} rows={5} /></div>
                  {(['period', 'geography', 'society', 'technology'] as const).map(key => (
                    <Field key={key} label={key[0].toUpperCase() + key.slice(1)} value={project.world[key]} onChange={value => patch({ world: { ...project.world, [key]: value } })} rows={2} />
                  ))}
                  <div className="md:col-span-2"><Field label="Rules — one per line" value={project.world.rules.join('\n')} onChange={value => patch({ world: { ...project.world, rules: value.split('\n').filter(Boolean) } })} rows={4} /></div>
                  <div className="md:col-span-2"><Field label="World-specific visual language (lighting, palette, motifs)" value={project.world.visualLanguage} onChange={visualLanguage => patch({ world: { ...project.world, visualLanguage } })} rows={3} /></div>
                  <Field label="World concept content prompt" value={project.world.visualPrompt} onChange={visualPrompt => patch({ world: { ...project.world, visualPrompt } })} rows={4} />
                  <Field label="Negative visual prompt" value={project.world.negativePrompt} onChange={negativePrompt => patch({ world: { ...project.world, negativePrompt } })} rows={4} />
                  <div className="md:col-span-2 flex gap-2">
                    <button className={button} disabled={Boolean(imageBusy) || referenceBatchBusy || !project.world.visualPrompt.trim()} onClick={() => generateVisual({ kind: 'world' }, project.world.visualPrompt)}>
                      {imageBusy === 'world:world' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {project.world.referenceAssetIds.length ? 'Generate another world concept' : 'Generate world concept'}
                    </button>
                    <button className={button} onClick={() => { setUploadTarget({ kind: 'world' }); uploadRef.current?.click() }}><Upload size={13} /> Add reference</button>
                  </div>
                  <div className="md:col-span-2"><ReferenceGallery ids={project.world.referenceAssetIds} assets={project.assets} onRemove={id => removeReference('world', undefined, id)} /></div>
                </div>
                <div className="mt-4 space-y-3">
                  <div className="flex justify-between items-center">
                    <h3 className="text-sm font-semibold text-text-primary">Locations</h3>
                    <button className={button} onClick={() => update(current => {
                      current.world.locations.push({ id: storyId('location'), name: 'New location', purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [] })
                      return current
                    })}><Plus size={13} /> Location</button>
                  </div>
                  {project.world.locations.map((location, index) => (
                    <LocationEditor key={location.id} location={location} index={index} total={project.world.locations.length} project={project} update={update} imageBusy={imageBusy} generateVisual={generateVisual} upload={() => { setUploadTarget({ kind: 'location', id: location.id }); uploadRef.current?.click() }} removeReference={id => removeReference('location', location.id, id)} />
                  ))}
                </div>
              </>
            )}

            {tab === 'characters' && (
              <>
                <div id="story-review-characters" className="scroll-mt-4">
                  <SectionHeader title="Characters" description="Personality, dramatic function, voice and approved visual identity live together." scope="characters" busy={busy} approved={isApproved('characters')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('characters')} />
                </div>
                <div className="flex justify-end mb-3">
                  <button className={button} onClick={() => update(current => {
                    current.characters.push(emptyCharacter())
                    return current
                  })}><Plus size={13} /> Character</button>
                </div>
                <div className="space-y-4">
                  {project.characters.map((character, index) => (
                    <CharacterEditor key={character.id} character={character} index={index} total={project.characters.length} project={project} update={update} imageBusy={imageBusy} generateVisual={generateVisual} upload={() => { setUploadTarget({ kind: 'character', id: character.id }); uploadRef.current?.click() }} removeReference={id => removeReference('character', character.id, id)} />
                  ))}
                  {!project.characters.length && <div className={`${panel} text-sm text-text-muted text-center py-12`}>Generate the cast or add the first character manually.</div>}
                </div>
              </>
            )}

            {tab === 'relationships' && (
              <>
                <div id="story-review-relationships" className="scroll-mt-4">
                  <SectionHeader title="Relationships" description="Conflict and change often live between characters, not inside isolated biographies." scope="relationships" busy={busy} approved={isApproved('relationships')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('relationships')} />
                </div>
                <div className="flex justify-end mb-3">
                  <button className={button} disabled={project.characters.length < 2} onClick={() => update(current => {
                    current.relationships.push({ id: storyId('relationship'), fromCharacterId: current.characters[0]?.id || '', toCharacterId: current.characters[1]?.id || '', label: '', dynamic: '', evolution: '' })
                    return current
                  })}><Plus size={13} /> Relationship</button>
                </div>
                <div className="space-y-3">
                  {project.relationships.map(relationship => (
                    <RelationshipEditor key={relationship.id} relationship={relationship} project={project} update={update} />
                  ))}
                </div>
              </>
            )}

            {tab === 'structure' && (
              <>
                <div id="story-review-structure" className="scroll-mt-4">
                  <SectionHeader title="Dramatic structure" description="A causal sequence: every beat changes the situation and motivates the next." scope="structure" busy={busy} approved={isApproved('structure')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('structure')} />
                </div>
                <div className="flex justify-end mb-3">
                  <button className={button} onClick={() => update(current => {
                    current.beats.push({ id: storyId('beat'), stage: 'New beat', title: '', summary: '', goal: '', conflict: '', turn: '' })
                    return current
                  })}><Plus size={13} /> Beat</button>
                </div>
                <div className="space-y-3">
                  {project.beats.map((beat, index) => <BeatEditor key={beat.id} beat={beat} index={index} total={project.beats.length} update={update} />)}
                </div>
              </>
            )}

            {tab === 'music' && (
              <>
                <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-3 mb-4">
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Music bible</h2>
                    <p className="text-xs text-text-muted mt-1">
                      {project.projectType === 'music_video'
                        ? 'One LLM-authored song built from the creative brief, ready to edit, generate and turn into a videoclip. No MiniMax music credits are used until you generate audio.'
                        : 'LLM-authored ambience, character presentation themes and three story songs. Suggestions cost no MiniMax music credits until you generate audio.'}
                    </p>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2 xl:max-w-[920px]">
                    <input className={`${input} sm:w-72`} value={instruction}
                      onChange={event => setInstruction(event.target.value)}
                      placeholder="Optional music direction…" />
                    {project.projectType === 'music_video' ? <>
                      <button className={`${button} border-violet-400/60 bg-violet-500/10 text-violet-200`}
                        disabled={Boolean(busy || musicQueue || musicCueBusy) || !musicWritingReady}
                        onClick={() => void createNewMusicVideoSong(false)}>
                        {newSongAction === 'prompts' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
                        Generar prompts de una nueva canción
                      </button>
                      <button className={`${button} ${completeGenerationButton}`}
                        disabled={Boolean(busy || musicQueue || musicCueBusy) || !musicWritingReady || !servicesConfig?.minimax_api_key_set}
                        onClick={() => void createNewMusicVideoSong(true)}
                        title={servicesConfig?.minimax_api_key_set
                          ? 'Crea prompts y letra nuevos y genera inmediatamente una canción con MiniMax'
                          : 'Configura la clave de MiniMax en Settings → Services'}>
                        {newSongAction === 'audio' ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />}
                        Generar nueva canción
                      </button>
                      <button className={button} disabled={Boolean(busy || musicQueue || musicCueBusy)} onClick={() => {
                        customMusicUploadCueId.current = project.music.cues.find(cue => cue.kind === 'story')?.id || ''
                        customMusicUploadRef.current?.click()
                      }}>
                        <Upload size={13} /> Import custom MP3
                      </button>
                    </> : <>
                      <button className={button} disabled={Boolean(busy || musicQueue)} onClick={() => generate('music')}>
                        {busy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate LLM suggestions
                      </button>
                      {musicQueue ? (
                        <button className={`${button} border-red-400/60 text-red-300`} onClick={cancelMusicQueue} disabled={musicQueue.cancelling === true}>
                          {musicQueue.cancelling ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                          {musicQueue.cancelling ? 'Cancelling active request…' : `Cancel queue ${musicQueue.index + 1}/${musicQueue.ids.length}`}
                        </button>
                      ) : (
                        <button className={`${button} ${completeGenerationButton}`}
                          disabled={Boolean(busy || musicCueBusy) || !project.music.cues.length || !servicesConfig?.minimax_api_key_set}
                          onClick={() => void generateAllMusicCues()}>
                          <Music size={13} /> Generate all sequentially
                        </button>
                      )}
                    </>}
                  </div>
                </div>

                {project.projectType === 'music_video' && (
                  <p className="-mt-2 mb-4 text-right text-[9px] text-text-muted">
                    “Prompts” no genera audio. “Nueva canción” reescribe prompt y letra y lanza una nueva versión automáticamente; las canciones anteriores se conservan.
                  </p>
                )}

                <div className={`${panel} mb-4 grid md:grid-cols-[1fr_1fr_2fr] gap-3 items-end`}>
                  <label className="block text-[10px] text-text-muted">MiniMax model for proposed tracks
                    <select className={`${input} mt-1`} value={project.music.model}
                      onChange={event => patch({ music: { ...project.music, model: event.target.value === 'music-2.6' ? 'music-2.6' : 'music-3.0' } })}>
                      <option value="music-3.0">Music 3.0 · recommended</option>
                      <option value="music-2.6">Music 2.6 · compatibility</option>
                    </select>
                  </label>
                  <div className="text-[10px] text-text-muted">
                    One audio result per proposal and click. Repeating a cue adds another candidate without deleting the previous one.
                  </div>
                  <div className={`rounded-md border px-3 py-2 text-[10px] ${servicesConfig?.minimax_api_key_set ? 'border-emerald-500/30 text-emerald-300' : 'border-amber-500/40 text-amber-300'}`}>
                    {servicesConfig?.minimax_api_key_set
                      ? 'MiniMax is configured. Audio generation is available and always remains explicit.'
                      : 'Configure the shared MiniMax key in Settings → Services before generating audio.'}
                  </div>
                </div>

                <div className={`${panel} mb-4 border-purple-500/30 bg-purple-500/5`}>
                  <div className="mb-2 flex items-start gap-2">
                    <Palette size={17} className="mt-0.5 shrink-0 text-purple-300" />
                    <div>
                      <h3 className="text-xs font-semibold text-purple-200">Create a new version of every music proposal</h3>
                      <p className="mt-0.5 text-[9px] text-text-muted">Changes style, language, or both. Prompts and lyrics are rewritten sequentially; generated audio candidates are never deleted.</p>
                    </div>
                  </div>
                  <div className="grid md:grid-cols-[1fr_0.7fr_auto] gap-2 items-end">
                    <label className="block text-[10px] text-text-muted">New style · optional
                      <input className={`${input} mt-1`} value={musicVersionStyle.all || ''}
                        onChange={event => setMusicVersionStyle(current => ({ ...current, all: event.target.value }))}
                        placeholder="Rap, boom bap, female flow, dark bass…" />
                    </label>
                    <label className="block text-[10px] text-text-muted">New lyrics language · optional
                      <input className={`${input} mt-1`} value={musicVersionLanguage.all || ''}
                        onChange={event => setMusicVersionLanguage(current => ({ ...current, all: event.target.value }))}
                        placeholder="Spanish, Japanese…" />
                    </label>
                    <button className={`${button} border-purple-500/60 text-purple-200`}
                      disabled={Boolean(busy || musicQueue || musicCueBusy) || !musicWritingReady || !project.music.cues.length}
                      onClick={() => void createAllMusicCueVersions()}>
                      {musicCueBusy === 'version:all' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
                      Rewrite all drafts
                    </button>
                  </div>
                </div>

                {(['world', 'character', 'story'] as const).map(kind => {
                  const cues = project.music.cues.filter(cue => cue.kind === kind)
                  if (!cues.length) return null
                  const heading = kind === 'world' ? 'World ambience'
                    : kind === 'character' ? 'Character presentation themes' : 'Three songs of the Story'
                  return (
                    <section key={kind} className="mb-5">
                      <h3 className="mb-2 text-sm font-semibold text-text-primary">{heading}</h3>
                      <div className="space-y-3">
                        {cues.map(cue => {
                          const targetName = cue.kind === 'character'
                            ? project.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
                            : cue.kind === 'world' ? (project.title || 'Story world') : cue.targetId
                          const generatingAudio = musicCueBusy === `audio:${cue.id}`
                          const adapting = musicCueBusy === `llm:${cue.id}`
                          const translating = musicCueBusy === `translate:${cue.id}`
                          const versioning = musicCueBusy === `version:${cue.id}`
                          const queued = musicQueue?.ids.includes(cue.id)
                          return (
                            <article key={cue.id} className={`${panel} space-y-3 ${generatingAudio ? 'border-pink-500/60' : ''}`}>
                              <div className="flex items-start justify-between gap-2">
                                <div>
                                  <span className="text-[9px] uppercase tracking-wide text-pink-300">{kind} · {targetName}</span>
                                  <input className={`${input} mt-1 font-medium`} value={cue.title}
                                    onChange={event => patchMusicCue(cue.id, { title: event.target.value })}
                                    aria-label={`Music title for ${targetName}`} />
                                </div>
                                {queued && <span className="rounded bg-pink-500/10 px-2 py-1 text-[9px] text-pink-300">queued</span>}
                              </div>
                              <div className="grid xl:grid-cols-[minmax(0,0.85fr)_minmax(360px,1.15fr)] gap-3">
                                <div className="space-y-2.5">
                                  <Field label="Purpose in this Story" value={cue.purpose}
                                    onChange={purpose => patchMusicCue(cue.id, { purpose })} rows={2} />
                                  <Field label="Example song · editable LLM input" value={cue.referenceSong}
                                    onChange={referenceSong => patchMusicCue(cue.id, { referenceSong })} rows={2}
                                    placeholder="Song title — Artist" />
                                  <p className="text-[9px] text-text-muted">The LLM uses only high-level tempo, instrumentation and emotional architecture; the resulting melody and wording must be original.</p>
                                  <Field label="Desired style + Story role · editable LLM input" value={cue.brief}
                                    onChange={brief => patchMusicCue(cue.id, { brief })} rows={3} />
                                  <div className="grid grid-cols-2 gap-2">
                                    <label className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-[10px] text-text-secondary">
                                      <input type="checkbox" checked={cue.instrumental}
                                        onChange={event => patchMusicCue(cue.id, { instrumental: event.target.checked })} />
                                      Instrumental
                                    </label>
                                    <label className="block text-[10px] text-text-muted">Target duration for lyrics · seconds
                                      <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                                        value={cue.durationSeconds}
                                        onChange={event => patchMusicCue(cue.id, { durationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) })} />
                                    </label>
                                  </div>
                                  <p className="text-[9px] text-text-muted">MiniMax has no exact duration setting; this guides the LLM’s lyric length, while the rendered track can vary with tempo and arrangement.</p>
                                  <button className={`${button} w-full`} disabled={Boolean(musicCueBusy || musicQueue) || !cue.referenceSong.trim()}
                                    onClick={() => void adaptMusicCueWithLlm(cue.id)}>
                                    {adapting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Adapt provider prompt{cue.instrumental ? '' : ' + lyrics'} with LLM
                                  </button>
                                  <div className="space-y-2 rounded-lg border border-purple-500/30 bg-purple-500/5 p-2.5">
                                    <div className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-200"><Palette size={12} /> Create a completely new version</div>
                                    <input className={input} value={musicVersionStyle[cue.id] || ''}
                                      onChange={event => setMusicVersionStyle(current => ({ ...current, [cue.id]: event.target.value }))}
                                      placeholder="New style, e.g. cinematic rap / boom bap…" />
                                    <input className={input} value={musicVersionLanguage[cue.id] || ''}
                                      onChange={event => setMusicVersionLanguage(current => ({ ...current, [cue.id]: event.target.value }))}
                                      placeholder={`New language, optional · current: ${cue.lyricsLanguage || project.language}`} />
                                    <button className={`${button} w-full border-purple-500/60 text-purple-200`}
                                      disabled={Boolean(musicCueBusy || musicQueue) || !musicWritingReady}
                                      onClick={() => void createMusicCueVersion(cue.id)}>
                                      {versioning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />} Rewrite style{cue.instrumental ? '' : ' + lyrics'}
                                    </button>
                                    <p className="text-[9px] text-text-muted">Leave either field empty to retain its current value. Existing generated tracks remain available below.</p>
                                  </div>
                                </div>
                                <div className="space-y-3">
                                <div className="space-y-2.5 rounded-lg border border-pink-500/30 bg-pink-500/5 p-3">
                                  <div className="flex items-start justify-between gap-2">
                                    <div>
                                      <h4 className="text-xs font-semibold text-pink-200">Exact MiniMax request · editable</h4>
                                      <p className="mt-0.5 text-[9px] text-text-muted">Maestro sends style and lyrics as separate fields. Editing these fields changes the next request.</p>
                                    </div>
                                    <span className="shrink-0 rounded border border-pink-500/30 px-2 py-1 text-[9px] text-pink-200">{project.music.model}</span>
                                  </div>
                                  <Field required label={`prompt · ${cue.style.trim().length}/300 characters`} value={cue.style}
                                    onChange={style => patchMusicCue(cue.id, { style })} rows={3} />
                                  <p className="text-[9px] text-text-muted">Genre, mood, instruments, voice, tempo and production. Anything after character 300 is not sent.</p>
                                  {!cue.instrumental && <Field required label="lyrics · structured separately" value={cue.lyrics}
                                    onChange={lyrics => patchMusicCue(cue.id, { lyrics })} rows={10} />}
                                  {!cue.instrumental && (
                                    <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                                      <label className="block text-[10px] text-text-muted">Translate lyrics to
                                        <input className={`${input} mt-1`} value={lyricsTranslationLanguage[cue.id] || ''}
                                          onChange={event => setLyricsTranslationLanguage(current => ({ ...current, [cue.id]: event.target.value }))}
                                          placeholder="English, French, Japanese…" />
                                      </label>
                                      <button className={`${button} self-end`} disabled={Boolean(musicCueBusy || musicQueue) || !musicWritingReady || !cue.lyrics.trim()}
                                        onClick={() => void translateMusicCueLyrics(cue.id)}>
                                        {translating ? <Loader2 size={13} className="animate-spin" /> : <Languages size={13} />} Translate
                                      </button>
                                    </div>
                                  )}
                                  {!cue.instrumental && <p className="text-[9px] text-text-muted">Uses the selected Story Lab LLM and replaces these editable lyrics. MiniMax section tags stay unchanged.</p>}
                                  {!cue.instrumental && cue.lyrics.trim() && !MINIMAX_LYRIC_SECTION.test(cue.lyrics) && (
                                    <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[9px] text-amber-200">
                                      These lyrics have no supported section tags. Use the LLM adaptation or add [Verse], [Pre Chorus], [Chorus], [Bridge] and [Outro] before generating.
                                    </p>
                                  )}
                                  <details className="rounded border border-border bg-bg-tertiary/70 p-2">
                                    <summary className="cursor-pointer text-[9px] text-text-secondary">Inspect the complete Maestro → MiniMax payload</summary>
                                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[9px] text-text-muted">{miniMaxCuePayload(cue, project.music.model)}</pre>
                                  </details>
                                  <div className="grid sm:grid-cols-3 gap-2">
                                    <button className={button} onClick={() => {
                                      void navigator.clipboard.writeText(miniMaxCuePayload(cue, project.music.model))
                                      setNotice({ kind: 'ok', text: `MiniMax payload for “${cue.title}” copied.` })
                                    }}><Copy size={12} /> Copy exact payload</button>
                                    <button className={`${button} ${completeGenerationButton}`}
                                      disabled={Boolean(musicCueBusy || musicQueue) || !servicesConfig?.minimax_api_key_set || !cue.style.trim() || (!cue.instrumental && (!cue.lyrics.trim() || !MINIMAX_LYRIC_SECTION.test(cue.lyrics)))}
                                      onClick={() => void generateMusicCueAudio(cue.id)}>
                                      {generatingAudio ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />} Generate this track
                                    </button>
                                    <button className={button} disabled={Boolean(musicCueBusy || musicQueue)} onClick={() => {
                                      customMusicUploadCueId.current = cue.id
                                      customMusicUploadRef.current?.click()
                                    }}><Upload size={12} /> Import custom MP3</button>
                                  </div>
                                </div>
                                <div className="space-y-2.5 rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
                                  <div className="flex items-start justify-between gap-2">
                                    <div>
                                      <h4 className="text-xs font-semibold text-blue-200">Google Lyria 3 Pro · manual workflow</h4>
                                      <p className="mt-0.5 text-[9px] text-text-muted">The LLM prepares the prompt here. Copy it to Google AI Studio, generate there, then import the MP3 result.</p>
                                    </div>
                                    <span className="shrink-0 rounded border border-blue-500/30 px-2 py-1 text-[9px] text-blue-200">lyria-3-pro-preview</span>
                                  </div>
                                  <Field label="Paste-ready Lyria prompt · editable" value={cue.lyriaPrompt}
                                    onChange={lyriaPrompt => patchMusicCue(cue.id, { lyriaPrompt })} rows={14}
                                    placeholder="Generate provider prompts with the LLM to create a timed composition breakdown…" />
                                  <p className="text-[9px] text-text-muted">Uses contiguous timestamps, section names, intensity, arrangement and separated lyrics. Lyria Pro targets up to about 3:00; longer Story durations are condensed in this prompt.</p>
                                  <div className="grid sm:grid-cols-2 gap-2">
                                    <button className={button} disabled={Boolean(musicCueBusy || musicQueue) || !musicWritingReady}
                                      onClick={() => void adaptMusicCueWithLlm(cue.id, true)}>
                                      {adapting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate / refresh Lyria prompt
                                    </button>
                                    <button className={button} disabled={!cue.lyriaPrompt.trim()} onClick={() => {
                                      void navigator.clipboard.writeText(cue.lyriaPrompt)
                                      setNotice({ kind: 'ok', text: `Lyria prompt for “${cue.title}” copied.` })
                                    }}><Copy size={12} /> Copy Lyria prompt</button>
                                    <a className={button} href="https://aistudio.google.com/u/1/new_music?model=lyria-3-pro-preview"
                                      target="_blank" rel="noreferrer">
                                      <ExternalLink size={12} /> Open Lyria in Google AI Studio
                                    </a>
                                    <button className={button} disabled={Boolean(musicCueBusy || musicQueue)} onClick={() => {
                                      lyriaUploadCueId.current = cue.id
                                      lyriaUploadRef.current?.click()
                                    }}><Upload size={12} /> Import generated audio</button>
                                  </div>
                                </div>
                                </div>
                              </div>
                              {cue.candidates.length > 0 && (
                                <div className="space-y-2 border-t border-border pt-2">
                                  {cue.candidates.map(candidate => {
                                    const selected = cue.selectedCandidateId === candidate.id
                                    const label = musicCandidateDisplayName(candidate, cue.title, cue.lyricsLanguage || project.language, cue.candidates.indexOf(candidate) + 1)
                                    return (
                                      <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                                        <button type="button" className="w-full flex items-center justify-between gap-2 text-left text-[10px]"
                                          onClick={() => patchMusicCue(cue.id, { selectedCandidateId: candidate.id })}>
                                          <span className="text-text-primary">{label} · {candidate.model}</span>
                                          <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : 'duration on playback'}</span>
                                        </button>
                                        <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                                        <button className={`${button} w-full`} disabled={Boolean(musicCueBusy || musicQueue) || !storyVideoConfigurationReady}
                                          onClick={() => void openMusicalTrailer(candidate.id)}>
                                          <Film size={12} /> Use in musical trailer
                                        </button>
                                      </div>
                                    )
                                  })}
                                </div>
                              )}
                            </article>
                          )
                        })}
                      </div>
                    </section>
                  )
                })}

                {!project.music.cues.length && (
                  <div className={`${panel} mb-5 py-12 text-center`}>
                    <Music size={30} className="mx-auto mb-3 text-pink-400" />
                    <p className="text-sm text-text-primary">No music bible yet</p>
                    <p className="mt-1 text-xs text-text-muted">Generate the complete Story or click “Generate LLM suggestions” here. No MiniMax music credits are used at this stage.</p>
                  </div>
                )}

                <details className={`${panel} group`}>
                  <summary className="cursor-pointer list-none flex items-center justify-between gap-2">
                    <span>
                      <span className="block text-sm font-semibold text-text-primary">Manual song / cover and musical trailer</span>
                      <span className="block text-[10px] text-text-muted mt-1">The original free-form workflow remains available for a custom song outside the LLM suggestions.</span>
                    </span>
                    <ChevronDown size={15} className="group-open:rotate-180 transition-transform" />
                  </summary>
                  <div className="mt-4 grid lg:grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <label className="block text-[10px] text-text-muted">Mode
                          <select className={`${input} mt-1`} value={project.music.mode}
                            onChange={event => patch({ music: { ...project.music, mode: event.target.value === 'cover' ? 'cover' : 'original' } })}>
                            <option value="original">Original song</option><option value="cover">Cover</option>
                          </select>
                        </label>
                        <label className="block text-[10px] text-text-muted">Candidates
                          <select className={`${input} mt-1`} value={project.music.candidateCount}
                            onChange={event => patch({ music: { ...project.music, candidateCount: Number(event.target.value) === 3 ? 3 : 2 } })}>
                            <option value={2}>2</option><option value={3}>3</option>
                          </select>
                        </label>
                      </div>
                      {project.music.mode === 'cover' && <>
                        <input ref={musicCoverRef} type="file" accept="audio/*" className="hidden"
                          onChange={event => void uploadCoverReference(event.target.files?.[0])} />
                        <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => musicCoverRef.current?.click()}>
                          <Upload size={13} /> {project.music.coverReferenceName ? `Replace ${project.music.coverReferenceName}` : 'Upload cover reference'}
                        </button>
                      </>}
                      <Field label="Song brief" value={project.music.brief || storySongBrief(project, project.music.targetDurationSeconds)}
                        onChange={brief => patch({ music: { ...project.music, brief } })} rows={5} />
                      <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => void writeStorySong()}>
                        <Sparkles size={13} /> Write prompt + lyrics with LLM
                      </button>
                      <Field label="Source lyrics / structure to adapt" value={project.music.sourceLyrics}
                        onChange={sourceLyrics => patch({ music: { ...project.music, sourceLyrics } })} rows={5} />
                      <button className={`${button} w-full`} disabled={productionBusy === 'music' || !project.music.sourceLyrics.trim()}
                        onClick={() => void adaptStoryLyrics()}><Sparkles size={13} /> Adapt lyrics to this Story</button>
                    </div>
                    <div className="space-y-2">
                      <Field required label="Final MiniMax prompt · English · max 300 characters" value={project.music.style}
                        onChange={style => patch({ music: { ...project.music, style } })} rows={3} />
                      <Field required label="Editable lyrics" value={project.music.lyrics}
                        onChange={lyrics => patch({ music: { ...project.music, lyrics } })} rows={8} />
                      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                        <label className="block text-[10px] text-text-muted">Translate lyrics to
                          <input className={`${input} mt-1`} value={lyricsTranslationLanguage.manual || ''}
                            onChange={event => setLyricsTranslationLanguage(current => ({ ...current, manual: event.target.value }))}
                            placeholder="English, French, Japanese…" />
                        </label>
                        <button className={`${button} self-end`} disabled={productionBusy === 'music' || !musicWritingReady || !project.music.lyrics.trim()}
                          onClick={() => void translateManualSongLyrics()}><Languages size={13} /> Translate</button>
                      </div>
                      <p className="text-[9px] text-text-muted">Uses the selected Story Lab LLM and replaces the editable lyrics, preserving MiniMax section tags.</p>
                      <div className="space-y-2 rounded-lg border border-purple-500/30 bg-purple-500/5 p-2.5">
                        <div className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-200"><Palette size={12} /> Create a completely new manual version</div>
                        <div className="grid sm:grid-cols-2 gap-2">
                          <input className={input} value={musicVersionStyle.manual || ''}
                            onChange={event => setMusicVersionStyle(current => ({ ...current, manual: event.target.value }))}
                            placeholder="New style, e.g. rap…" />
                          <input className={input} value={musicVersionLanguage.manual || ''}
                            onChange={event => setMusicVersionLanguage(current => ({ ...current, manual: event.target.value }))}
                            placeholder={`Language · ${project.music.lyricsLanguage || project.language}`} />
                        </div>
                        <button className={`${button} w-full border-purple-500/60 text-purple-200`}
                          disabled={productionBusy === 'music' || !musicWritingReady}
                          onClick={() => void createManualSongVersion()}><RefreshCcw size={13} /> Rewrite style + lyrics</button>
                        <p className="text-[9px] text-text-muted">Use either field or both. The current draft supplies the Story meaning, but its arrangement and sung lines are rebuilt from scratch.</p>
                      </div>
                      <label className="block text-[10px] text-text-muted">Target duration for lyrics · seconds
                        <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                          value={project.music.targetDurationSeconds}
                          onChange={event => patch({ music: { ...project.music, targetDurationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) } })} />
                      </label>
                      <p className="text-[9px] text-text-muted">MiniMax Music does not expose an exact duration parameter; the target guides lyric writing and the render can vary.</p>
                      <button className={`${button} ${completeGenerationButton} w-full`}
                        disabled={productionBusy === 'music' || !servicesConfig?.minimax_api_key_set}
                        onClick={() => void generateMinimaxSongs()}><Music size={13} /> Generate manual candidates</button>
                      {project.music.candidates.map(candidate => (
                        <div key={candidate.id} className="rounded border border-border p-2 space-y-1.5">
                          <span className="text-[10px] text-text-primary">{musicCandidateDisplayName(candidate, project.title || 'Story song', project.music.lyricsLanguage || project.language, project.music.candidates.indexOf(candidate) + 1)} · {candidate.model}</span>
                          <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                          <button className={`${button} w-full`} disabled={!storyVideoConfigurationReady} onClick={() => void openMusicalTrailer(candidate.id)}><Film size={12} /> Use in musical trailer</button>
                        </div>
                      ))}
                      <button className={`${button} w-full`} disabled={!storyVideoConfigurationReady} onClick={() => void openMusicalTrailer()}>
                        <ChevronRight size={13} /> Open Musical Video Director
                      </button>
                    </div>
                  </div>
                </details>
              </>
            )}

            {tab === 'trailer' && (
              <div className="space-y-4">
                <div className="overflow-hidden rounded-2xl border border-amber-400/30 bg-gradient-to-br from-amber-500/10 via-bg-secondary to-purple-500/10 p-4 md:p-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="max-w-2xl">
                      <div className="mb-2 flex items-center gap-2 text-amber-200"><Film size={22} /><span className="text-[10px] font-semibold uppercase tracking-[0.2em]">Story Lab · Trailer Creator</span></div>
                      <h2 className="text-xl font-semibold text-text-primary">Creador de tráileres cinematográficos</h2>
                      <p className="mt-2 text-xs leading-relaxed text-text-muted">Convierte el canon de esta Story en clips ordenados que cuentan una mini-historia épica: presentación, amenaza, escalada, respiración y un gancho final que no revela el desenlace.</p>
                    </div>
                    <div className="grid min-w-56 grid-cols-2 gap-2 text-center text-[10px]">
                      <div className="rounded-lg border border-border bg-bg-primary/50 p-2"><span className="block text-lg font-semibold text-amber-200">{trailerDuration}s</span>duración objetivo</div>
                      <div className="rounded-lg border border-border bg-bg-primary/50 p-2"><span className="block text-lg font-semibold text-purple-200">6</span>fases narrativas</div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
                  <div className={`${panel} space-y-4`}>
                    <div><h3 className="text-sm font-semibold text-text-primary">Dirección narrativa</h3><p className="mt-1 text-[10px] text-text-muted">Todo es editable antes de abrir Director o gastar créditos.</p></div>
                    <label className="block text-[10px] text-text-muted">Qué debe prometer este tráiler
                      <textarea className={`${input} mt-1`} rows={4} value={trailerDirection} onChange={event => { markTrailerTouched(); setTrailerDirection(event.target.value) }} aria-label="Trailer creative direction" />
                    </label>
                    <label className="block text-[10px] text-text-muted">Tagline final opcional
                      <input className={`${input} mt-1`} value={trailerTagline} onChange={event => { markTrailerTouched(); setTrailerTagline(event.target.value) }} placeholder={project.logline || 'Una última frase memorable…'} />
                    </label>
                    <div>
                      <p className="mb-1.5 text-[10px] text-text-muted">Duración</p>
                      <div className="grid grid-cols-4 gap-1.5">
                        {[30, 45, 60, 90].map(seconds => <button key={seconds} type="button" className={`${button} ${trailerDuration === seconds ? 'border-amber-400/70 bg-amber-500/10 text-amber-100' : ''}`} onClick={() => { markTrailerTouched(); setTrailerDuration(seconds) }}>{seconds}s</button>)}
                      </div>
                      <input className={`${input} mt-2`} type="number" min={15} max={180} step={5} value={trailerDuration} onChange={event => { markTrailerTouched(); setTrailerDuration(Math.max(15, Math.min(180, Number(event.target.value) || 60))) }} />
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="block text-[10px] text-text-muted">Formato
                        <select className={`${input} mt-1`} value={trailerFormat} onChange={event => { markTrailerTouched(); setTrailerFormat(event.target.value as StoryTrailerFormat) }}>
                          <option value="theatrical">Theatrical · arco completo</option>
                          <option value="teaser">Teaser · misterio</option>
                          <option value="character">Personaje · arco emocional</option>
                        </select>
                      </label>
                      <label className="block text-[10px] text-text-muted">Voces
                        <select className={`${input} mt-1`} value={trailerNarration} onChange={event => { markTrailerTouched(); setTrailerNarration(event.target.value as StoryTrailerNarration) }}>
                          <option value="hybrid">Narrador + diálogo selectivo</option>
                          <option value="voice_over">Voz en off principal</option>
                          <option value="dialogue">Solo diálogo de personajes</option>
                          <option value="visual">Solo imagen, música y efectos</option>
                        </select>
                      </label>
                      <label className="block text-[10px] text-text-muted">Nivel de revelación
                        <select className={`${input} mt-1`} value={trailerSpoiler} onChange={event => { markTrailerTouched(); setTrailerSpoiler(event.target.value as StoryTrailerSpoiler) }}>
                          <option value="mystery">Misterio · protege casi todo</option>
                          <option value="balanced">Equilibrado · premisa y apuestas</option>
                          <option value="revealing">Revelador · grandes set pieces</option>
                        </select>
                      </label>
                      <label className="block text-[10px] text-text-muted">Curva de intensidad
                        <select className={`${input} mt-1`} value={trailerIntensity} onChange={event => { markTrailerTouched(); setTrailerIntensity(event.target.value as StoryTrailerIntensity) }}>
                          <option value="rising">Creciente · clásico épico</option>
                          <option value="relentless">Implacable · urgencia continua</option>
                          <option value="prestige">Prestige · atmósfera y escala</option>
                        </select>
                      </label>
                    </div>
                    <label className={`flex items-start gap-2 rounded-md border p-2 ${trailerTitleCards && !project.allowClipText ? 'border-amber-400/50 bg-amber-500/10' : 'border-border bg-bg-primary/30'}`}>
                      <input type="checkbox" checked={trailerTitleCards} onChange={event => { markTrailerTouched(); setTrailerTitleCards(event.target.checked) }} className="mt-0.5 accent-amber-400" />
                      <span><span className="block text-[10px] font-medium text-text-primary">Cartelas mínimas: gancho, título y tagline</span><span className="block text-[9px] text-text-muted">Nunca convierte el diálogo en subtítulos. Requiere “Permitir texto visible” en Story.</span></span>
                    </label>
                    {trailerTitleCards && !project.allowClipText && <button type="button" className={`${button} w-full border-amber-400/50 text-amber-200`} onClick={() => patch({ allowClipText: true })}>Permitir texto visible en esta Story</button>}
                  </div>

                  <div className={`${panel} space-y-3`}>
                    <div><h3 className="text-sm font-semibold text-text-primary">Arco temporal</h3><p className="mt-1 text-[10px] text-text-muted">Los segundos se recalculan al cambiar la duración.</p></div>
                    {TRAILER_ARC.map((phase, index) => {
                      const start = Math.round(trailerDuration * phase.start / 100)
                      const end = Math.round(trailerDuration * phase.end / 100)
                      return <div key={phase.label} className="grid grid-cols-[2rem_minmax(0,1fr)_3.5rem] items-start gap-2 rounded-lg border border-border bg-bg-primary/35 p-2.5">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 text-[10px] font-semibold text-amber-200">{index + 1}</span>
                        <span><span className="block text-[10px] font-medium text-text-primary">{phase.label}</span><span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{phase.detail}</span></span>
                        <span className="text-right text-[9px] font-medium text-amber-200">{start}–{end}s</span>
                      </div>
                    })}
                  </div>
                </div>

                <div className={`${panel} space-y-4`}>
                  <div><h3 className="text-sm font-semibold text-text-primary">Producción de clips</h3><p className="mt-1 text-[10px] text-text-muted">Usa el mismo pipeline recuperable del montaje: clips ordenados, Play all, edición/regeneración en su posición y unión final.</p></div>
                  <div className="grid gap-3 lg:grid-cols-2">
                    <div className="rounded-lg border border-border bg-bg-primary/30 p-3 space-y-2">
                      <p className="text-[10px] font-medium text-text-primary">Guía visual</p>
                      <p className="text-[9px] leading-relaxed text-text-muted">Elige fotogramas generados, referencias aprobadas o texto puro sin imágenes.</p>
                      <div className="grid gap-1.5 md:grid-cols-3">
                        <button type="button" className={`${button} flex-col ${!directVideo && !directReferenceVideo ? 'border-purple-400/60 text-purple-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}><span>Imágenes iniciales</span><span className="text-[9px] text-text-muted">Genera start frames</span></button>
                        <button type="button" className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}><span>Referencias directas</span><span className="text-[9px] text-text-muted">H3 Ref2VA</span></button>
                        <button type="button" className={`${button} flex-col ${directVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'direct_video', protagonistConsistency: false })}><span>Vídeo directo</span><span className="text-[9px] text-text-muted">T2V · sin imágenes</span></button>
                      </div>
                      {project.protagonistConsistency && <p className="text-[9px] text-amber-300">Al elegir T2V puro se desactivará la consistencia visual estricta del protagonista, porque no se enviarán imágenes.</p>}
                      {directReferenceVideo && <div className={`rounded-md border p-2 text-[9px] leading-relaxed ${directReferenceVideoReady ? 'border-emerald-500/35 bg-emerald-500/5 text-emerald-100' : 'border-amber-500/40 bg-amber-500/5 text-amber-200'}`}>
                        {directReferenceVideoReady
                          ? `${approvedVisualReferenceCount} referencia${approvedVisualReferenceCount === 1 ? '' : 's'} aprobada${approvedVisualReferenceCount === 1 ? '' : 's'} se enviará${approvedVisualReferenceCount === 1 ? '' : 'n'} directamente a H3; no se generarán start frames.`
                          : directReferenceVideoSupported
                            ? 'Aprueba al menos una imagen en Imágenes antes de generar.'
                            : 'Elige un modelo MiniMax H3; Ref2VA no está disponible con otros modelos.'}
                      </div>}
                      {directVideo && <div className="rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 p-2 space-y-2">
                        <p className="text-[10px] font-medium text-fuchsia-200">T2V puro · sin imágenes ni referencias</p>
                        <p className="text-[9px] leading-relaxed text-text-muted">Director repetirá este contrato visual en cada clip y sólo añadirá la situación concreta del tráiler.</p>
                        <label className="block text-[9px] text-violet-200">Prompt maestro de mundo y estilo<span className="ml-1 text-violet-300" title="Required">●</span>
                          <textarea className={`${input} ${requiredInput} mt-1 min-h-32 resize-y leading-relaxed`} value={project.directVideoMasterPrompt}
                            onChange={event => patch({ directVideoMasterPromptMode: 'custom', directVideoMasterPrompt: event.target.value })}
                            placeholder="Define el mundo, personajes y estilo que deben repetirse en todos los clips" required aria-required="true" />
                        </label>
                        <span className={`block text-[9px] leading-relaxed ${directVideoMasterReady ? 'text-fuchsia-200/80' : 'text-amber-300'}`}>
                          {directVideoMasterReady ? 'No se ejecutará el modelo de imagen ni se enviarán referencias a H3.' : 'Completa este prompt antes de generar.'}
                        </span>
                      </div>}
                      <label className={`flex items-start gap-2 pt-1 ${directVideo ? 'opacity-45' : ''}`}><input type="checkbox" disabled={directVideo} checked={trailerPreserveVisualStyle} onChange={event => { markTrailerTouched(); setTrailerPreserveVisualStyle(event.target.checked) }} className="mt-0.5 accent-purple-400" /><span><span className="block text-[10px] text-text-primary">Conservar el estilo visual de Story</span><span className="block text-[9px] text-text-muted">{directVideo ? 'En T2V el estilo procede exclusivamente del prompt maestro.' : 'Mantiene medio, paleta, diseño y referencias aprobadas.'}</span></span></label>
                    </div>
                    <div className="rounded-lg border border-border bg-bg-primary/30 p-3 space-y-2">
                      <label className="block text-[10px] text-text-muted">Modelo de imagen
                        <select className={`${input} mt-1`} value={filmImageModel} disabled={directVideo || directReferenceVideo} onChange={event => selectDirectorImageModel(event.target.value)}>
                          {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>}
                          <optgroup label="External API"><option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option></optgroup>
                          <optgroup label="Maestro local">{selectableImageModels.map(model => <option key={model.model_type} value={model.model_type}>{model.name}{model.is_downloaded === false ? ' · downloads on first use' : ''}</option>)}</optgroup>
                        </select>
                      </label>
                      <label className="block text-[10px] text-text-muted">Modelo de vídeo
                        <select className={`${input} mt-1`} value={filmVideoModel} disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady} onChange={event => selectStoryVideoModel(event.target.value)}>
                          {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>}
                          {selectableVideoModels.map(model => <option key={model.model_type} value={model.model_type}>{model.name}{model.is_downloaded === false ? ' · downloads on first use' : ''}</option>)}
                        </select>
                      </label>
                    </div>
                  </div>
                  <StoryVideoFormatControls videoModel={filmVideoModel} resolution={storyVideoResolution} aspectRatio={storyVideoAspectRatio} options={storyVideoOptions} disabled={!storyVideoOptionsReady} inherited={project.provider.useGlobalProfile} adjusted={storyVideoFormat.adjusted} onChange={setStoryVideoFormat} />
                  {trailerProductionIssues.length > 0 && <div className="rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[10px] text-amber-200">Revisa {trailerProductionIssues.length} requisito{trailerProductionIssues.length === 1 ? '' : 's'} de Story antes de generar.</div>}
                  <div className="grid gap-2 sm:grid-cols-2">
                    <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(trailerProductionIssues.length) || Boolean(productionBusy) || !filmGenerationImageReady || !directReferenceVideoReady || !directVideoMasterReady || !storyVideoConfigurationReady || (trailerTitleCards && !project.allowClipText)} onClick={() => void stageTrailer(true)}>{productionBusy === 'trailer' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generar tráiler completo</button>
                    <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(trailerProductionIssues.length) || Boolean(productionBusy) || !directVideoMasterReady || !storyVideoConfigurationReady || (trailerTitleCards && !project.allowClipText)} onClick={() => void stageTrailer(false)}><ChevronRight size={13} /> Abrir y revisar en Director</button>
                  </div>
                  <p className="text-[9px] text-text-muted">La generación completa crea un trabajo recuperable. “Imágenes iniciales” consume imagen y vídeo; Ref2VA y T2V puro omiten el modelo de imagen.</p>
                </div>
              </div>
            )}

            {tab === 'productions' && (
              <>
                <div className="mb-4">
                  <h2 className="text-lg font-semibold text-text-primary">{project.projectType === 'music_video' ? 'Generar videoclip' : project.projectType === 'quick_video' ? 'Generar vídeo rápido' : 'Productions'}</h2>
                  <p className="text-xs text-text-muted mt-1">{project.projectType === 'full_story'
                    ? 'Adapt the same approved material without destroying the source story.'
                    : 'Revisa los modelos, el formato y las referencias aprobadas antes de iniciar Director.'}</p>
                </div>
                <div className="grid md:grid-cols-2 gap-4">
                  {project.projectType === 'full_story' && (
                  <div className={`${panel} space-y-3`}>
                    <BookOpen size={26} className="text-accent-blue" />
                    <h3 className="font-semibold text-text-primary">Comic adaptation</h3>
                    <p className="text-xs text-text-muted">Creates a self-contained chapter inside the master canon. Director receives every arc, relationship, location and approved identity image.</p>
                    <textarea className={input} rows={4} value={comicDirection} onChange={event => setComicDirection(event.target.value)} aria-label="Comic chapter direction" />
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block text-[10px] text-text-muted">Pages
                        <input
                          className={`${input} mt-1`}
                          type="number"
                          min={1}
                          max={100}
                          value={comicPageCount}
                          onChange={event => setComicPageCount(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}
                        />
                      </label>
                      <label className="block text-[10px] text-text-muted">Panels per page
                        <input
                          className={`${input} mt-1`}
                          type="number"
                          min={1}
                          max={12}
                          value={comicPanelsPerPage}
                          onChange={event => setComicPanelsPerPage(Math.max(1, Math.min(12, Number(event.target.value) || 1)))}
                        />
                      </label>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {[4, 12, 24].map(count => (
                        <button
                          key={count}
                          type="button"
                          className={`${button} ${comicPageCount === count ? 'border-accent-blue text-accent-blue' : ''}`}
                          onClick={() => setComicPageCount(count)}
                        >
                          {count === 4 ? '4 · quick test' : `${count} pages`}
                        </button>
                      ))}
                    </div>
                    <p className="text-[9px] text-text-muted">
                      Planned size: {comicPageCount * comicPanelsPerPage} panels. Longer chapters take proportionally more planning time and image credits.
                    </p>
                    <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(true)}><Sparkles size={13} /> Generate complete comic chapter</button>
                    <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(false)}><ChevronRight size={13} /> Open in Comic Director</button>
                    <p className="text-[9px] text-text-muted">Complete generation creates the plan and artwork and may consume provider credits. Director mode lets you review every field first.</p>
                  </div>
                  )}
                  {project.projectType !== 'music_video' && (
                  <div className={`${panel} space-y-3`}>
                    <Film size={26} className="text-purple-400" />
                    <h3 className="font-semibold text-text-primary">{project.projectType === 'quick_video' ? 'Vídeo rápido' : 'Film adaptation'}</h3>
                    <p className="text-xs text-text-muted">{project.projectType === 'quick_video'
                      ? 'Convierte directamente el concepto, diálogo y 3–8 momentos en un vídeo ensamblado, conservando protagonistas, lugar y estilo.'
                      : 'Creates a short narrative episode instead of compressing the whole story. The cast, world and visual references remain attached.'}</p>
                    <textarea className={input} rows={4} value={filmDirection} onChange={event => setFilmDirection(event.target.value)} aria-label="Short-film episode direction" />
                    <label className="block text-[10px] text-text-muted">Target duration · seconds
                      <input
                        className={`${input} mt-1`}
                        type="number"
                        min={10}
                        max={1800}
                        step={5}
                        value={filmDuration}
                        onChange={event => setFilmDuration(Math.max(10, Math.min(1800, Number(event.target.value) || 45)))}
                      />
                    </label>
                    <div className="rounded-md border border-violet-500/25 bg-violet-500/5 p-2.5 space-y-2">
                      <p className="text-[10px] font-medium text-violet-100">Visual guidance</p>
                      <div className="grid grid-cols-2 gap-1.5">
                        <button
                          type="button"
                          className={`${button} flex-col ${!directReferenceVideo ? 'border-purple-400/60 text-purple-200' : ''}`}
                          onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}
                        >
                          <span>Generate start images</span>
                          <span className="text-[9px] text-text-muted">Traditional image-guided pipeline</span>
                        </button>
                        <button
                          type="button"
                          className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`}
                          onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}
                        >
                          <span>Direct approved references</span>
                          <span className="text-[9px] text-text-muted">H3 Ref2VA · no start images</span>
                        </button>
                      </div>
                      {directReferenceVideo && (
                        <p className={`text-[9px] ${directReferenceVideoReady ? 'text-emerald-200' : 'text-amber-300'}`}>
                          {directReferenceVideoReady
                            ? `${approvedVisualReferenceCount} approved reference${approvedVisualReferenceCount === 1 ? '' : 's'} ready for H3.`
                            : directReferenceVideoSupported
                              ? 'Approve at least one image in Imágenes.'
                              : 'Choose a MiniMax H3 video model.'}
                        </p>
                      )}
                    </div>
                    <label className="block text-[10px] text-text-muted">Image model
                      <select
                        className={`${input} mt-1`}
                        value={filmImageModel}
                        disabled={directReferenceVideo}
                        onChange={event => selectDirectorImageModel(event.target.value)}
                      >
                        {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && (
                          <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>
                        )}
                        <optgroup label="External API">
                          <option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option>
                        </optgroup>
                        <optgroup label="Maestro local">
                          {selectableImageModels.map(model => (
                            <option key={model.model_type} value={model.model_type}>
                              {model.name}{model.is_downloaded === false ? ' · downloads on first use' : ''}
                            </option>
                          ))}
                        </optgroup>
                      </select>
                      <span className={`mt-1 block text-[9px] leading-relaxed ${filmImageReady ? 'text-text-muted' : 'text-amber-300'}`}>
                        {directReferenceVideo
                          ? 'Not used in direct-reference mode; approved Story images go straight to H3 Ref2VA.'
                          : filmImageModel === MINIMAX_IMAGE_API_MODEL
                          ? filmImageReady
                            ? 'MiniMax Image-01 runs through the external API and does not use local VRAM. It is independent from the local H3 video model.'
                            : 'Add the MiniMax API key in Settings → Services before starting complete generation.'
                          : 'Generates every shot frame locally with the selected Maestro image model.'}
                      </span>
                    </label>
                    <label className="block text-[10px] text-text-muted">Video model
                      <select
                        className={`${input} mt-1`}
                        value={filmVideoModel}
                        disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady}
                        onChange={event => selectStoryVideoModel(event.target.value)}
                      >
                        {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && (
                          <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>
                        )}
                        {selectableVideoModels.map(model => (
                          <option key={model.model_type} value={model.model_type}>
                            {model.name}{model.is_downloaded === false ? ' · downloads on first use' : ''}
                          </option>
                        ))}
                      </select>
                      <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">
                        {!storyVideoOptionsReady
                          ? 'Checking this model’s supported formats…'
                          : project.provider.useGlobalProfile
                            ? 'Inherited from the global production profile. Choose “Override in this project” above to edit it only for this Story.'
                            : filmVideoModel === 'minimax_h3_legacy'
                          ? 'H3 Legacy Quality uses its 20-step ConvRot recipe. A 7–10s shot at 720p can take tens of minutes even on an RTX 4090; choose 540p/480p or a Turbo-capable H3 variant when speed matters.'
                          : filmVideoModel.startsWith('minimax_h3')
                          ? 'MiniMax H3 renders every planned shot locally at up to 768p with native stereo audio. Longer shots are continued and assembled automatically.'
                          : 'LTX uses Maestro’s multi-shot Director pipeline and requires its bundled Gemma 3 12B text encoder. Gemma may download on first use; it is an LTX dependency, not a separate setting. This choice is saved only in this Story.'}
                      </span>
                    </label>
                    <StoryVideoFormatControls
                      videoModel={filmVideoModel}
                      resolution={storyVideoResolution}
                      aspectRatio={storyVideoAspectRatio}
                      options={storyVideoOptions}
                      disabled={!storyVideoOptionsReady}
                      inherited={project.provider.useGlobalProfile}
                      adjusted={storyVideoFormat.adjusted}
                      onChange={setStoryVideoFormat}
                    />
                    <label className="flex items-start gap-2 rounded-md border border-purple-500/30 bg-purple-500/10 p-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={filmPreserveVisualStyle}
                        onChange={event => setFilmPreserveVisualStyle(event.target.checked)}
                        className="mt-0.5 accent-purple-400"
                      />
                      <span>
                        <span className="block text-[10px] font-medium text-purple-200">Preserve Story visual style</span>
                        <span className="block text-[9px] leading-relaxed text-text-muted">
                          Keeps anime, comic, illustration, palette and character design across generated frames and video. Disable only to intentionally reinterpret the adaptation.
                        </span>
                      </span>
                    </label>
                    <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy) || !filmGenerationImageReady || !directReferenceVideoReady || !storyVideoConfigurationReady} onClick={() => stageFilm(true)}>{productionBusy === 'film' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {project.projectType === 'quick_video' ? 'Generar vídeo rápido completo' : 'Generate complete short film'}</button>
                    <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy) || !storyVideoConfigurationReady} onClick={() => stageFilm(false)}><ChevronRight size={13} /> {project.projectType === 'quick_video' ? 'Abrir en Director' : 'Open in Short Film Director'}</button>
                    <p className="text-[9px] text-text-muted">Complete generation launches a recoverable Director pipeline and may consume image/video credits.</p>
                  </div>
                  )}
                  {project.projectType !== 'quick_video' && (
                  <div className={`${panel} space-y-3 md:col-span-2`}>
                    <div className="flex items-start gap-3">
                      <Music size={26} className="shrink-0 text-pink-400" />
                      <div>
                        <h3 className="font-semibold text-text-primary">Music video or musical trailer</h3>
                        <p className="mt-1 text-xs text-text-muted">
                          Selects an existing Story song and builds the visuals around what that cue represents. Character themes keep that character and approved identity references at the center.
                        </p>
                      </div>
                    </div>
                    {musicCandidateOptions.length ? (
                      <>
                        <label className="block text-[10px] text-text-muted">Song
                          <select
                            className={`${input} mt-1`}
                            value={musicProductionCandidateId}
                            onChange={event => setMusicProductionCandidateId(event.target.value)}
                          >
                            {musicCandidateOptions.map(option => (
                              <option key={option.candidate.id} value={option.candidate.id}>
                                {option.label} · {option.candidate.durationSeconds
                                  ? `${Math.floor(option.candidate.durationSeconds / 60)}:${Math.round(option.candidate.durationSeconds % 60).toString().padStart(2, '0')}`
                                  : 'duration on playback'}
                              </option>
                            ))}
                          </select>
                        </label>
                        {selectedMusicOption && (
                          <div className="rounded-lg border border-pink-500/25 bg-pink-500/5 p-2.5 space-y-2">
                            <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
                              <span className="font-medium text-pink-200">
                                {selectedMusicOption.cue
                                  ? `${selectedMusicOption.cue.kind === 'character' ? 'Character' : selectedMusicOption.cue.kind === 'world' ? 'World' : 'Story'} focus · ${selectedMusicOption.cue.title}`
                                  : 'Story-wide focus'}
                              </span>
                              <span className="text-text-muted">
                                {getOutputReference({ name: selectedMusicOption.candidate.name, type: 'audio' })} · {selectedMusicOption.candidate.provider}/{selectedMusicOption.candidate.model}
                              </span>
                            </div>
                            {selectedMusicOption.cue?.purpose && (
                              <p className="text-[10px] text-text-secondary">{selectedMusicOption.cue.purpose}</p>
                            )}
                            <audio src={selectedMusicOption.candidate.source} controls preload="metadata" className="h-8 w-full" />
                          </div>
                        )}
                        <div className="rounded-lg border border-fuchsia-500/35 bg-fuchsia-500/5 p-2.5 space-y-2.5">
                          <div>
                            <p className="text-[10px] font-medium text-fuchsia-200">Cómo generar los planos</p>
                            <p className="mt-0.5 text-[9px] leading-relaxed text-text-muted">
                              Elige fotogramas generados, referencias aprobadas directas mediante H3 Ref2VA, o texto puro sin ninguna imagen.
                            </p>
                          </div>
                          <div className="grid gap-1.5 md:grid-cols-3">
                            <button
                              type="button"
                              onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}
                              className={`${button} flex-col ${project.musicVideoGenerationMode === 'image_guided' ? 'border-pink-500/60 text-pink-300' : ''}`}
                            >
                              <span>Con imágenes</span>
                              <span className="text-[9px] text-text-muted">Crea un fotograma inicial</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}
                              className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`}
                            >
                              <span>Directo con referencias</span>
                              <span className="text-[9px] text-text-muted">H3 Ref2VA · sin start frames</span>
                            </button>
                            <button
                              type="button"
                              disabled={project.protagonistConsistency}
                              onClick={() => patch({ musicVideoGenerationMode: 'direct_video' })}
                              className={`${button} flex-col ${directMusicVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`}
                            >
                              <span>Vídeo directo · sin imágenes</span>
                              <span className="text-[9px] text-text-muted">T2V puro</span>
                            </button>
                          </div>
                          {project.protagonistConsistency && <p className="text-[9px] text-amber-300">El modo de protagonista fijo necesita imágenes: usa “Con imágenes” o “Directo con referencias”.</p>}
                          {directReferenceVideo && (
                            <div className={`rounded-md border p-2 text-[9px] leading-relaxed ${directReferenceVideoReady
                              ? 'border-emerald-500/35 bg-emerald-500/5 text-emerald-100'
                              : 'border-amber-500/40 bg-amber-500/5 text-amber-200'}`}>
                              {directReferenceVideoReady
                                ? `${approvedVisualReferenceCount} approved image${approvedVisualReferenceCount === 1 ? '' : 's'} will be routed by character/location labels directly into H3 Ref2VA. The image model is not run.`
                                : directReferenceVideoSupported
                                  ? 'Approve at least one image in Imágenes before generating.'
                                  : 'Choose a MiniMax H3 video model; this mode is unavailable for LTX and other start-frame models.'}
                            </div>
                          )}
                          {directMusicVideo && (
                            <div className="block text-[10px] text-violet-200">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span>Prompt maestro de mundo y estilo<span className="ml-1 text-violet-300" title="Required">●</span></span>
                                <span className={`rounded-full border px-1.5 py-0.5 text-[9px] ${project.directVideoMasterPromptMode === 'inherit'
                                  ? 'border-violet-400/50 bg-violet-500/10 text-violet-200'
                                  : 'border-sky-400/50 bg-sky-500/10 text-sky-200'}`}>
                                  {project.directVideoMasterPromptMode === 'inherit' ? 'Heredado de estilos' : 'Personalizado'}
                                </span>
                                {project.directVideoMasterPromptMode === 'custom' && (
                                  <button
                                    type="button"
                                    onClick={() => patch({ directVideoMasterPromptMode: 'inherit' })}
                                    className="ml-auto inline-flex items-center gap-1 rounded border border-violet-400/45 px-1.5 py-0.5 text-[9px] text-violet-200 hover:bg-violet-500/15"
                                    title="Reemplazar el prompt personalizado por los estilos actuales del proyecto"
                                  >
                                    <RefreshCcw size={10} /> Usar estilos actuales
                                  </button>
                                )}
                              </div>
                              <textarea
                                className={`${input} ${requiredInput} mt-1 min-h-36 resize-y leading-relaxed`}
                                value={project.directVideoMasterPrompt}
                                onChange={event => patch({
                                  directVideoMasterPromptMode: 'custom',
                                  directVideoMasterPrompt: event.target.value,
                                })}
                                placeholder="Este contrato se repetirá completo en cada clip y segmento"
                                required
                                aria-required="true"
                              />
                              <span className={`mt-1 block text-[9px] leading-relaxed ${directVideoMasterReady ? 'text-fuchsia-200/80' : 'text-amber-300'}`}>
                                {directVideoMasterReady
                                  ? project.directVideoMasterPromptMode === 'inherit'
                                    ? 'Se actualiza automáticamente desde Estilo visual y Estilo visual de los personajes. Al editarlo pasa a Personalizado. No se enviarán imágenes ni referencias H3.'
                                    : 'Prompt personalizado: el LLM sólo añadirá la situación concreta. No se enviarán imágenes ni referencias H3.'
                                  : 'Completa Estilo visual o escribe aquí un prompt maestro antes de generar.'}
                              </span>
                            </div>
                          )}
                        </div>
                        <div className="rounded-lg border border-border bg-bg-tertiary/40 p-2.5 space-y-2">
                          <div>
                            <p className="text-[10px] font-medium text-text-secondary">Generation models</p>
                            <p className="mt-0.5 text-[9px] text-text-muted">These exact choices are sent to Director and saved with this music-video production for later iterations.</p>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                            <label className="block text-[10px] text-text-muted">Planning LLM
                              <select
                                className={`${input} mt-1`}
                                value={project.provider.writingProvider}
                                onChange={event => setMusicWritingProvider(event.target.value as StoryWritingProvider)}
                              >
                                <option value="maestro">Maestro internal</option>
                                <option value="deepseek">DeepSeek</option>
                                <option value="minimax">MiniMax</option>
                                <option value="openai">OpenAI</option>
                                <option value="openai-compatible">Custom OpenAI-compatible</option>
                              </select>
                            </label>
                            {project.provider.writingProvider !== 'maestro' && (
                              <label className="block text-[10px] text-text-muted">LLM model
                                {project.provider.writingProvider === 'deepseek' ? (
                                  <select className={`${input} mt-1`} value={project.provider.writingModel || 'deepseek-v4-pro'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                                    <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                                    <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
                                  </select>
                                ) : project.provider.writingProvider === 'minimax' ? (
                                  <select className={`${input} mt-1`} value={project.provider.writingModel || 'MiniMax-M3'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                                    <option value="MiniMax-M3">MiniMax M3</option>
                                    <option value="MiniMax-M2.7">MiniMax M2.7</option>
                                    <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed</option>
                                  </select>
                                ) : (
                                  <input className={`${input} mt-1`} value={project.provider.writingModel} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })} />
                                )}
                              </label>
                            )}
                            {directMusicVideo || directReferenceVideo ? (
                              <div className="rounded-md border border-fuchsia-500/25 bg-fuchsia-500/5 px-2 py-1.5 text-[10px] text-text-muted">
                                <span className="block font-medium text-fuchsia-200">Image model · no usado</span>
                                <span className="mt-1 block text-[9px]">
                                  {directReferenceVideo
                                    ? 'No crea start frames: envía únicamente las referencias aprobadas directamente a H3 Ref2VA.'
                                    : 'No se generará, cargará ni enviará ninguna imagen.'}
                                </span>
                              </div>
                            ) : (
                              <label className="block text-[10px] text-text-muted">Image model
                                <select className={`${input} mt-1`} value={filmImageModel} onChange={event => selectDirectorImageModel(event.target.value)}>
                                  {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && (
                                    <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>
                                  )}
                                  <optgroup label="External API">
                                    <option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option>
                                  </optgroup>
                                  <optgroup label="Maestro local">
                                    {selectableImageModels.map(model => (
                                      <option key={model.model_type} value={model.model_type}>{model.name}</option>
                                    ))}
                                  </optgroup>
                                </select>
                              </label>
                            )}
                            <label className="block text-[10px] text-text-muted">Video model
                              <select
                                className={`${input} mt-1`}
                                value={filmVideoModel}
                                disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady}
                                onChange={event => selectStoryVideoModel(event.target.value)}
                              >
                                {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && (
                                  <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>
                                )}
                                {selectableVideoModels.map(model => (
                                  <option key={model.model_type} value={model.model_type}>
                                    {model.name}{model.is_downloaded === false ? ' · downloads on first use' : ''}
                                  </option>
                                ))}
                              </select>
                              <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">
                                {!storyVideoOptionsReady
                                  ? 'Checking this model’s supported formats…'
                                  : project.provider.useGlobalProfile
                                    ? 'Inherited from the global production profile. Choose “Override in this project” above to make a Story-only selection.'
                                    : filmVideoModel === 'minimax_h3_legacy'
                                  ? 'H3 Legacy Quality renders 20 full quality steps per shot. At 720p this can take tens of minutes; 540p/480p or a Turbo-capable H3 variant is the faster choice.'
                                  : filmVideoModel.startsWith('ltx2')
                                  ? 'LTX also downloads/loads Gemma 3 12B as its required text encoder. Gemma is not another selected model.'
                                  : 'This exact MiniMax H3 selection is saved only in this Story and sent to Director when production opens.'}
                              </span>
                            </label>
                            <StoryVideoFormatControls
                              videoModel={filmVideoModel}
                              resolution={storyVideoResolution}
                              aspectRatio={storyVideoAspectRatio}
                              options={storyVideoOptions}
                              disabled={!storyVideoOptionsReady}
                              inherited={project.provider.useGlobalProfile}
                              adjusted={storyVideoFormat.adjusted}
                              onChange={setStoryVideoFormat}
                            />
                          </div>
                          {project.provider.writingProvider === 'openai-compatible' && (
                            <label className="block text-[10px] text-text-muted">Compatible API base URL
                              <input className={`${input} mt-1`} value={project.provider.writingBaseUrl} onChange={event => patchMusicWritingProvider({ writingBaseUrl: event.target.value })} placeholder="https://…/v1" />
                            </label>
                          )}
                          <p className={`text-[9px] ${musicWritingReady && musicVideoImageReady && directVideoMasterReady && directReferenceVideoReady ? 'text-text-muted' : 'text-amber-300'}`}>
                            {musicWritingReady && musicVideoImageReady && directVideoMasterReady && directReferenceVideoReady
                              ? directMusicVideo
                                ? `Ready: ${project.provider.writingProvider === 'maestro' ? 'Maestro internal' : project.provider.writingModel} · T2V without images · ${selectedFilmVideoModel?.name || filmVideoModel}`
                                : directReferenceVideo
                                  ? `Ready: ${project.provider.writingProvider === 'maestro' ? 'Maestro internal' : project.provider.writingModel} · ${approvedVisualReferenceCount} approved references · ${selectedFilmVideoModel?.name || filmVideoModel}`
                                : `Ready: ${project.provider.writingProvider === 'maestro' ? 'Maestro internal' : project.provider.writingModel} · ${selectedFilmImageModel?.name || filmImageModel} · ${selectedFilmVideoModel?.name || filmVideoModel}`
                              : !musicWritingReady
                                ? 'Configure the selected planning LLM in Settings → Services before generating.'
                                : !directVideoMasterReady
                                  ? 'Define the direct-video master prompt before generating.'
                                  : !directReferenceVideoReady
                                    ? directReferenceVideoSupported
                                      ? 'Approve at least one image in the visual reference library.'
                                      : 'Direct references require a MiniMax H3 video model.'
                                  : 'Configure MiniMax in Settings → Services before using MiniMax Image.'}
                          </p>
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                          <button
                            type="button"
                            onClick={() => setMusicProductionMode('full')}
                            className={`${button} flex-col ${musicProductionMode === 'full' ? 'border-pink-500/60 text-pink-300' : ''}`}
                          >
                            <span>Complete music video</span>
                            <span className="text-[9px] text-text-muted">Uses the entire song</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setMusicProductionMode('trailer')}
                            className={`${button} flex-col ${musicProductionMode === 'trailer' ? 'border-pink-500/60 text-pink-300' : ''}`}
                          >
                            <span>Musical trailer</span>
                            <span className="text-[9px] text-text-muted">Uses a selected excerpt</span>
                          </button>
                        </div>
                        {musicProductionMode === 'trailer' && selectedMusicOption && (
                          <AudioRangeSelector
                            key={selectedMusicOption.candidate.id}
                            src={selectedMusicOption.candidate.source}
                            durationHint={selectedMusicOption.candidate.durationSeconds}
                            start={musicTrailerRange.start}
                            end={musicTrailerRange.end}
                            onChange={setMusicTrailerRange}
                          />
                        )}
                        <div>
                          <div className="mb-1.5 flex items-center justify-between">
                            <span className="text-[10px] text-text-muted">Editing rhythm</span>
                            <span className="text-[9px] text-text-muted">Balanced is recommended</span>
                          </div>
                          <div className="grid grid-cols-3 gap-1.5">
                            {([
                              ['cinematic', 'Cinematic', '8–16s'],
                              ['balanced', 'Balanced', '5–8s'],
                              ['rhythmic', 'Rhythmic', '3–5s'],
                            ] as const).map(([value, label, duration]) => (
                              <button
                                key={value}
                                type="button"
                                onClick={() => setMusicProductionPacing(value)}
                                className={`${button} flex-col ${musicProductionPacing === value ? 'border-pink-500/60 text-pink-300' : ''}`}
                              >
                                <span>{label}</span><span className="text-[9px] text-text-muted">{duration}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                        <label className="flex items-start gap-2 rounded-md border border-border bg-bg-tertiary/40 p-2.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={project.allowClipText}
                            onChange={event => patch({ allowClipText: event.target.checked })}
                            className="mt-0.5 accent-pink-400"
                          />
                          <span>
                            <span className="block text-[10px] font-medium text-text-secondary">Permitir generar clips con textos</span>
                            <span className="block text-[9px] leading-relaxed text-text-muted">Si está desactivado, las letras solo guían el ritmo, la interpretación y el significado visual; nunca se copian como texto dentro del plano.</span>
                          </span>
                        </label>
                        <div className="grid gap-2 sm:grid-cols-2">
                          <button
                            className={`${button} ${completeGenerationButton} w-full`}
                            disabled={Boolean(productionBusy) || Boolean(musicProductionIssues.length) || !protagonistReferenceReady || !musicWritingReady || !musicVideoImageReady || !directVideoMasterReady || !directReferenceVideoReady || !storyVideoConfigurationReady}
                            onClick={() => void stageMusicVideo(true)}
                          >
                            {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                            Generate {musicProductionMode === 'trailer' ? 'musical trailer' : 'complete music video'}
                          </button>
                          <button
                            className={`${button} w-full`}
                            disabled={Boolean(productionBusy) || Boolean(musicProductionIssues.length) || !protagonistReferenceReady || !musicWritingReady || !musicVideoImageReady || !directVideoMasterReady || !directReferenceVideoReady || !storyVideoConfigurationReady}
                            onClick={() => void stageMusicVideo(false)}
                          >
                            <ChevronRight size={13} /> Open {musicProductionMode === 'trailer' ? 'trailer' : 'music video'} in Director
                          </button>
                        </div>
                        <p className="text-[9px] text-text-muted">
                          {directMusicVideo
                            ? 'The selected song, structured lyrics, direct-video master prompt and pacing are saved in Adaptation history. Images remain in the Story library but are not sent to this production.'
                            : directReferenceVideo
                              ? 'The selected song, structured lyrics, approved custom references and pacing are saved in Adaptation history. H3 Ref2VA receives them directly without generating start images.'
                            : 'The selected song, structured lyrics, focus character/world, approved images and pacing are saved in Adaptation history and can be reopened independently.'}
                        </p>
                      </>
                    ) : (
                      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
                        No generated or imported songs are available yet.{' '}
                        <button type="button" className="underline" onClick={() => setTab('music')}>Open Music</button>
                        {' '}to generate with MiniMax or import a Google Lyria result.
                      </div>
                    )}
                  </div>
                  )}
                  <div className="hidden" aria-hidden="true">
                    <Music size={26} className="text-pink-400" />
                    <h3 className="font-semibold text-text-primary">Musical trailer</h3>
                    <p className="text-xs text-text-muted">Turns the Story into a song-led video. Maestro analyzes the selected track’s duration, BPM, sections and beats, then plans cuts to fit the complete song.</p>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block text-[10px] text-text-muted">Generation mode
                        <select className={`${input} mt-1`} value={project.music.mode}
                          onChange={event => patch({ music: { ...project.music, mode: event.target.value === 'cover' ? 'cover' : 'original' } })}>
                          <option value="original">Original song</option>
                          <option value="cover">Cover from reference</option>
                        </select>
                      </label>
                      <label className="block text-[10px] text-text-muted">MiniMax model
                        <select className={`${input} mt-1`} value={project.music.mode === 'cover' ? 'music-cover' : project.music.model}
                          disabled={project.music.mode === 'cover'}
                          onChange={event => patch({ music: { ...project.music, model: event.target.value === 'music-2.6' ? 'music-2.6' : 'music-3.0' } })}>
                          {project.music.mode === 'cover'
                            ? <option value="music-cover">Music Cover</option>
                            : <>
                              <option value="music-3.0">Music 3.0 · recommended</option>
                              <option value="music-2.6">Music 2.6 · compatibility</option>
                            </>}
                        </select>
                      </label>
                    </div>
                    {project.music.mode === 'cover' && (
                      <div className="space-y-1.5 rounded-md border border-pink-500/30 bg-pink-500/5 p-2">
                        <input ref={musicCoverRef} type="file" accept="audio/*" className="hidden"
                          onChange={event => void uploadCoverReference(event.target.files?.[0])} />
                        <button className={`${button} w-full`} disabled={productionBusy === 'music'}
                          onClick={() => musicCoverRef.current?.click()}>
                          <Upload size={13} /> {project.music.coverReferenceName ? 'Replace cover reference' : 'Upload cover reference'}
                        </button>
                        {project.music.coverReferenceName && <p className="text-[9px] text-pink-200">Reference: {project.music.coverReferenceName}</p>}
                        <p className="text-[9px] text-text-muted">MiniMax accepts 6 seconds–6 minutes and up to 50 MB. Leave final lyrics empty to retain/extract the original, or provide your editable Story lyrics below.</p>
                      </div>
                    )}
                    <textarea
                      className={input}
                      rows={6}
                      value={project.music.brief || storySongBrief(project, project.music.targetDurationSeconds)}
                      onChange={event => patch({ music: { ...project.music, brief: event.target.value } })}
                      aria-label="Story song brief"
                    />
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block text-[10px] text-text-muted">Approx. duration · seconds
                        <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                          value={project.music.targetDurationSeconds}
                          onChange={event => patch({ music: { ...project.music, targetDurationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) } })} />
                      </label>
                      <label className="block text-[10px] text-text-muted">Candidates
                        <select className={`${input} mt-1`} value={project.music.candidateCount}
                          onChange={event => patch({ music: { ...project.music, candidateCount: Number(event.target.value) === 3 ? 3 : 2 } })}>
                          <option value={2}>2 songs</option>
                          <option value={3}>3 songs</option>
                        </select>
                      </label>
                    </div>
                    <button className={`${button} w-full`} disabled={productionBusy === 'music'} onClick={() => void writeStorySong()}>
                      {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Write song prompt + lyrics
                    </button>
                    <div className="space-y-1.5 rounded-md border border-border p-2">
                      <textarea className={input} rows={6} value={project.music.sourceLyrics}
                        placeholder="Optional source lyrics / section structure to adapt into this Story…"
                        onChange={event => patch({ music: { ...project.music, sourceLyrics: event.target.value } })}
                        aria-label="Source lyrics to adapt" />
                      <button className={`${button} w-full`} disabled={productionBusy === 'music' || !project.music.sourceLyrics.trim()}
                        onClick={() => void adaptStoryLyrics()}>
                        <Sparkles size={13} /> Adapt lyrics automatically to this Story
                      </button>
                      <p className="text-[9px] text-text-muted">Creates new wording from the Story while preserving only broad structure and singability. Use source material you are allowed to adapt.</p>
                    </div>
                    {project.music.style && (
                      <textarea className={input} rows={3} value={project.music.style}
                        onChange={event => patch({ music: { ...project.music, style: event.target.value } })}
                        aria-label="MiniMax Music style prompt" />
                    )}
                    {project.music.lyrics && (
                      <textarea className={input} rows={8} value={project.music.lyrics}
                        onChange={event => patch({ music: { ...project.music, lyrics: event.target.value } })}
                        aria-label="Song lyrics" />
                    )}
                    <button className={`${button} ${completeGenerationButton} w-full`}
                      disabled={productionBusy === 'music' || !servicesConfig?.minimax_api_key_set}
                      onClick={() => void generateMinimaxSongs()}>
                      {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />}
                      Generate {project.music.candidateCount} {project.music.mode === 'cover' ? 'covers' : 'songs'} with MiniMax {project.music.mode === 'cover' ? 'Music Cover' : project.music.model === 'music-3.0' ? 'Music 3.0' : 'Music 2.6'}
                    </button>
                    {!servicesConfig?.minimax_api_key_set && <p className="text-[9px] text-amber-300">Configure MiniMax in Settings → Services to generate candidates.</p>}
                    <p className="text-[9px] text-text-muted">Optional local generation is also supported through Director’s internal ACE-Step engine; it can be selected instead of MiniMax without changing the video workflow.</p>
                    {project.music.candidates.length > 0 && (
                      <div className="space-y-2">
                        {project.music.candidates.map(candidate => {
                          const selected = project.music.selectedCandidateId === candidate.id
                          const label = musicCandidateDisplayName(candidate, project.title || 'Story song', project.music.lyricsLanguage || project.language, project.music.candidates.indexOf(candidate) + 1)
                          return (
                            <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                              <button type="button" onClick={() => patch({ music: { ...project.music, selectedCandidateId: candidate.id } })}
                                className="w-full flex items-center justify-between text-[10px] text-left">
                                <span className="text-text-primary">{label} · {candidate.model}</span>
                                <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : 'duration on playback'}</span>
                              </button>
                              <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                              <button className={`${button} w-full ${selected ? 'border-pink-500/50 text-pink-300' : ''}`}
                                onClick={() => void openMusicalTrailer(candidate.id)} disabled={productionBusy === 'music' || !storyVideoConfigurationReady}>
                                <Film size={12} /> Use this song in musical trailer
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    )}
                    <button className={`${button} w-full`} onClick={() => void openMusicalTrailer()} disabled={productionBusy === 'music' || !storyVideoConfigurationReady}>
                      <ChevronRight size={13} /> Open Musical Video Director
                    </button>
                    <p className="text-[9px] text-text-muted">Uploaded songs work too. Beat-aware cuts synchronize editing rhythm; generated motion itself is not guaranteed to hit every beat semantically.</p>
                  </div>
                </div>
                {visibleProductionIssues.length > 0 && (
                  <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
                    <p className="font-medium">Falta revisar {visibleProductionIssues.length === 1 ? 'un apartado' : `${visibleProductionIssues.length} apartados`} antes de generar.</p>
                    <p className="mt-1 text-[10px] leading-relaxed text-amber-200/80">
                      {directMusicVideo && project.projectType === 'music_video'
                        ? 'Estás en vídeo directo: sólo se aprueban textos y descripciones; no necesitas generar ni seleccionar imágenes.'
                        : 'Abre cada pendiente, revisa su contenido y pulsa Aprobar. No se genera nada al aprobar.'}
                    </p>
                    <div className="mt-2 grid gap-1.5 md:grid-cols-2">
                      {visibleProductionIssues.map(issue => (
                        <button key={issue.id} type="button" onClick={() => openProductionReviewIssue(issue)}
                          className="flex items-start gap-2 rounded-md border border-amber-400/25 bg-bg-primary/30 px-2.5 py-2 text-left hover:border-amber-300/60 hover:bg-amber-500/10">
                          <ChevronRight size={14} className="mt-0.5 shrink-0" />
                          <span>
                            <span className="block font-medium">{issue.label}</span>
                            <span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{issue.detail}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {project.productions.length > 0 && <div className={`${panel} mt-4 flex flex-wrap items-center gap-3`}><div className="mr-auto"><h3 className="text-sm font-semibold text-text-primary">Hay {project.productions.length} producción{project.productions.length === 1 ? '' : 'es'} en el montaje</h3><p className="mt-1 text-[10px] text-text-muted">Ábrelas en orden, reprodúcelas completas y sustituye clips desde su posición.</p></div><button className={button} onClick={() => setTab('assembly')}><Play size={13} />Abrir montaje</button></div>}
              </>
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
  )
}

function emptyCharacter(): StoryCharacter {
  return {
    id: storyId('character'), name: 'New character', role: '', age: '', pronouns: '',
    personality: '', desire: '', need: '', flaw: '', conflict: '', arc: '', voice: '',
    appearance: '', wardrobe: '', visualPrompt: '', negativePrompt: '',
    referenceAssetIds: [], approval: 'draft',
  }
}

function CompactVideoWorkspace({
  project, update, busy, imageBusy, referenceBatchBusy, generateSection, approveSection,
  isSectionApproved, generateVisual, upload, removeReference, navigate, requiresVisualIdentities,
}: {
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  busy: StoryGenerationScope | null
  imageBusy: string
  referenceBatchBusy: boolean
  generateSection: (scope: StoryGenerationScope, options?: StoryGenerationOptions) => void
  approveSection: (scope: keyof StoryProject['approvals']) => void
  isSectionApproved: (scope: keyof StoryProject['approvals']) => boolean
  generateVisual: (
    target: { kind: 'world' | 'character' | 'location'; id?: string },
    prompt: string,
  ) => Promise<unknown>
  upload: (target: { kind: 'world' | 'character' | 'location'; id?: string }) => void
  removeReference: (target: 'world' | 'character' | 'location', targetId: string | undefined, assetId: string) => void
  navigate: (tab: StoryTab) => void
  requiresVisualIdentities: boolean
}) {
  const isMusicVideo = project.projectType === 'music_video'
  const isTrailer = project.projectType === 'trailer'
  const worldReady = Boolean(project.world.summary.trim() && project.world.visualLanguage.trim())
  const castReady = project.characters.length > 0 && project.characters.every(character =>
    character.approval === 'approved'
    && (!requiresVisualIdentities
      || Boolean(character.primaryReferenceAssetId
        && project.assets[character.primaryReferenceAssetId]?.approval === 'approved')))
  const sequenceReady = project.beats.length >= 3 && project.beats.every(beat =>
    Boolean(beat.summary.trim() && beat.conflict.trim() && beat.turn.trim()))
  const status = (ready: boolean, approved: boolean) => (
    <span className={`rounded-full border px-2 py-1 text-[9px] ${ready
      ? approved ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      : 'border-border bg-bg-tertiary text-text-muted'}`}>
      {ready ? approved ? 'Aprobado' : 'Listo para aprobar' : 'Pendiente'}
    </span>
  )

  return (
    <section className={`${panel} mt-4 ${isMusicVideo ? 'border-pink-500/25' : 'border-cyan-500/25'}`}>
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className={`text-[9px] font-semibold uppercase tracking-[0.18em] ${isMusicVideo ? 'text-pink-300' : 'text-cyan-300'}`}>
            Mesa de preparación
          </p>
          <h3 className="mt-1 text-base font-semibold text-text-primary">
            {isMusicVideo ? 'Imágenes y secuencia del videoclip' : isTrailer ? 'Mundo, protagonistas y arco del tráiler' : 'Imágenes y secuencia del vídeo rápido'}
          </h3>
          <p className="mt-1 max-w-3xl text-xs text-text-muted">
            {isMusicVideo
              ? 'Aquí sólo viven el entorno visual, el artista o protagonistas y los momentos que acompañarán la canción. No necesitas una biblia de mundo ni relaciones dramáticas.'
              : isTrailer
                ? 'Aquí se prepara el material de una película que el tráiler podrá prometer: mundo, protagonistas, amenaza, escalada y gancho final. No depende de ninguna canción.'
              : 'Aquí sólo viven la localización, las personas que deben aparecer y la sucesión breve de acciones o diálogo. Los campos internos compatibles con Director se mantienen detrás de esta vista.'}
          </p>
          <p className="mt-2 rounded-md border border-accent-blue/20 bg-accent-blue/5 px-2.5 py-1.5 text-[9px] leading-relaxed text-text-muted">
            <span className="font-medium text-accent-blue">“Solo texto” usa únicamente el LLM.</span> Conserva las referencias y no renderiza imágenes. Los botones “+ imágenes”, “Generar imagen” y “Crear identidad” sí ejecutan el proveedor visual y pueden consumir créditos.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={button} onClick={() => navigate('assets')}><ImagePlus size={13} /> Importar imágenes</button>
          {isMusicVideo && <button className={button} onClick={() => navigate('music')}><Music size={13} /> Editar canción</button>}
          <button className={`${button} border-accent-blue/60 text-accent-blue`} onClick={() => navigate(isTrailer ? 'trailer' : 'productions')}><Film size={13} /> {isTrailer ? 'Crear tráiler' : 'Ir a generar'}</button>
        </div>
      </div>

      <div className="space-y-4">
        <article id="story-review-world" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">1 · Entorno y dirección visual</h4>
              <p className="text-[9px] text-text-muted">Una base visual reutilizable, no una sección de worldbuilding.</p>
            </div>
            {status(worldReady, isSectionApproved('world'))}
          </div>
          <Field label={isMusicVideo ? 'Escenario visual del videoclip' : isTrailer ? 'Mundo cinematográfico' : 'Localización del vídeo'} value={project.world.summary}
            onChange={summary => update(current => { current.world.summary = summary; return current })} rows={3} />
          <Field label="Iluminación, paleta y lenguaje visual" value={project.world.visualLanguage}
            onChange={visualLanguage => update(current => { current.world.visualLanguage = visualLanguage; return current })} rows={3} />
          <Field label="Prompt para la imagen base" value={project.world.visualPrompt}
            onChange={visualPrompt => update(current => { current.world.visualPrompt = visualPrompt; return current })} rows={4} />
          <details className="rounded-md border border-border bg-bg-tertiary/35 p-2 text-[10px] text-text-muted">
            <summary className="cursor-pointer text-text-secondary">Evitar en las imágenes y localizaciones adicionales</summary>
            <div className="mt-3 space-y-3">
              <Field label="Negative prompt" value={project.world.negativePrompt}
                onChange={negativePrompt => update(current => { current.world.negativePrompt = negativePrompt; return current })} rows={3} />
              <div className="flex items-center justify-between gap-2">
                <span>{project.world.locations.length} localizaciones adicionales</span>
                <button className={button} onClick={() => update(current => {
                  current.world.locations.push({ id: storyId('location'), name: 'Nueva localización', purpose: '', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [] })
                  return current
                })}><Plus size={12} /> Añadir</button>
              </div>
              {project.world.locations.map((location, index) => (
                <LocationEditor key={location.id} location={location} index={index} total={project.world.locations.length}
                  project={project} update={update} imageBusy={imageBusy} generateVisual={generateVisual}
                  upload={() => upload({ kind: 'location', id: location.id })}
                  removeReference={id => removeReference('location', location.id, id)} />
              ))}
            </div>
          </details>
          <div className="flex flex-wrap gap-2">
            <button className={`${button} ${!worldReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('world')}
              title="Genera o reescribe sólo los textos del entorno mediante el LLM; no renderiza imágenes.">
              {busy === 'world' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Preparar entorno · solo texto
            </button>
            <button className={button} disabled={Boolean(imageBusy) || referenceBatchBusy || !project.world.visualPrompt.trim()}
              onClick={() => void generateVisual({ kind: 'world' }, project.world.visualPrompt)}>
              {imageBusy === 'world:world' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} Generar imagen
            </button>
            <button className={button} onClick={() => upload({ kind: 'world' })}><Upload size={13} /> Añadir referencia</button>
            <button className={`${button} ${isSectionApproved('world') ? 'border-emerald-500 text-emerald-400' : ''}`}
              onClick={() => approveSection('world')}><Check size={13} /> {isSectionApproved('world') ? 'Aprobado' : 'Aprobar'}</button>
          </div>
          <ReferenceGallery ids={project.world.referenceAssetIds} assets={project.assets}
            onRemove={id => removeReference('world', undefined, id)} />
        </article>

        <article id="story-review-characters" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">2 · {isMusicVideo ? 'Artista y sujetos' : isTrailer ? 'Protagonistas y antagonistas' : 'Protagonistas'}</h4>
              <p className="text-[9px] text-text-muted">Sólo identidad, vestuario, aspecto y referencias que verá la cámara.</p>
            </div>
            {status(castReady, isSectionApproved('characters'))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={`${button} ${!castReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('characters')}
              title="Genera o reescribe sólo los textos de los sujetos mediante el LLM; conserva sus imágenes.">
              {busy === 'characters' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Preparar sujetos · solo texto
            </button>
            <button className={`${button} ${!castReady ? requiredPreparationButton : ''}`}
              disabled={Boolean(busy || imageBusy || referenceBatchBusy)}
              onClick={() => generateSection('characters', { generateImages: true })}
              title="Prepara las fichas de los sujetos y, después de aplicarlas, genera las imágenes de identidad que falten. Puede consumir créditos de imagen.">
              {busy === 'characters' || referenceBatchBusy
                ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
              Preparar sujetos + imágenes
            </button>
            <button className={button} onClick={() => update(current => { current.characters.push(emptyCharacter()); return current })}>
              <Plus size={13} /> Añadir
            </button>
            <button className={`${button} ${isSectionApproved('characters') ? 'border-emerald-500 text-emerald-400' : ''}`}
              onClick={() => approveSection('characters')}><Check size={13} /> {isSectionApproved('characters') ? 'Aprobados' : 'Aprobar conjunto'}</button>
          </div>
          <p className="rounded-md border border-violet-500/25 bg-violet-500/5 px-2.5 py-1.5 text-[9px] leading-relaxed text-text-muted">
            {isTrailer
              ? 'Para completar esta fase basta uno de los dos botones. Las imágenes son opcionales al escribir el tráiler; se necesitan después si eliges “Imágenes iniciales”, o puedes aportar referencias aprobadas para H3 Ref2VA.'
              : 'Para completar esta fase basta uno de los dos botones; no pulses ambos. Las imágenes no son necesarias para escribir la canción: usa “+ imágenes” sólo si prepararás el videoclip con imágenes y “solo texto” para “Vídeo directo · sin imágenes”.'}
          </p>
          <div className="space-y-3">
            {project.characters.map((character, index) => (
              <CompactSubjectEditor key={character.id} character={character} index={index} total={project.characters.length}
                project={project} update={update} imageBusy={imageBusy} generateVisual={generateVisual}
                upload={() => upload({ kind: 'character', id: character.id })}
                removeReference={id => removeReference('character', character.id, id)}
                requiresVisualIdentity={requiresVisualIdentities} />
            ))}
            {!project.characters.length && <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-text-muted">Genera o añade la primera persona que aparecerá en cámara.</p>}
          </div>
        </article>

        <article id="story-review-structure" className="scroll-mt-4 rounded-xl border border-border bg-bg-primary/35 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-semibold text-text-primary">3 · {isMusicVideo ? 'Momentos visuales' : isTrailer ? 'Arco y momentos de tráiler' : 'Acciones y cortes'}</h4>
              <p className="text-[9px] text-text-muted">{isMusicVideo ? 'La progresión visual que Director adaptará a las secciones de la canción.' : isTrailer ? 'Impacto, promesa, ruptura, escalada, respiración y gancho final sin revelar el desenlace.' : 'Una secuencia corta con principio, cambio y remate.'}</p>
            </div>
            {status(sequenceReady, isSectionApproved('structure'))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={`${button} ${!sequenceReady ? requiredPreparationButton : ''}`} disabled={Boolean(busy || referenceBatchBusy)} onClick={() => generateSection('structure')}
              title="Genera o reescribe sólo la secuencia escrita mediante el LLM; no renderiza imágenes ni vídeo.">
              {busy === 'structure' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Preparar secuencia · solo texto
            </button>
            <button className={button} onClick={() => update(current => {
              current.beats.push({ id: storyId('beat'), stage: '', title: 'Nuevo momento', summary: '', goal: '', conflict: '', turn: '' })
              return current
            })}><Plus size={13} /> Añadir momento</button>
            <button className={`${button} ${isSectionApproved('structure') ? 'border-emerald-500 text-emerald-400' : ''}`}
              onClick={() => approveSection('structure')}><Check size={13} /> {isSectionApproved('structure') ? 'Aprobada' : 'Aprobar secuencia'}</button>
          </div>
          <div className="space-y-2">
            {project.beats.map((beat, index) => (
              <CompactBeatEditor key={beat.id} beat={beat} index={index} total={project.beats.length} update={update} />
            ))}
            {!project.beats.length && <p className="rounded-lg border border-dashed border-border p-6 text-center text-xs text-text-muted">Genera la secuencia o añade el primer momento.</p>}
          </div>
        </article>
      </div>
    </section>
  )
}

function CompactSubjectEditor({
  character, index, total, project, update, imageBusy, generateVisual, upload, removeReference, requiresVisualIdentity,
}: {
  character: StoryCharacter
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  imageBusy: string
  generateVisual: (target: { kind: 'character'; id: string }, prompt: string) => Promise<unknown>
  upload: () => void
  removeReference: (id: string) => void
  requiresVisualIdentity: boolean
}) {
  const set = (change: Partial<StoryCharacter>) => update(current => {
    current.characters = current.characters.map(item => item.id === character.id
      ? { ...item, approval: 'draft', ...change } : item)
    return current
  })
  const primaryAsset = character.primaryReferenceAssetId
    ? project.assets[character.primaryReferenceAssetId]
    : undefined
  const hasPrimary = primaryAsset?.approval === 'approved'
  const canApprove = !requiresVisualIdentity || hasPrimary
  return (
    <div id={`story-review-character-${character.id}`} className="scroll-mt-4 rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-text-primary">{character.name || 'Sin nombre'}</p>
          <p className={`text-[9px] ${hasPrimary || !requiresVisualIdentity ? 'text-emerald-300' : 'text-amber-300'}`}>
            {requiresVisualIdentity
              ? hasPrimary ? 'Identidad principal aprobada' : 'Falta aprobar una imagen de identidad principal'
              : 'Vídeo directo · la descripción es suficiente'}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title="Subir" onClick={() => update(current => { moveItem(current.characters, index, index - 1); return current })}><ChevronUp size={12} /></button>
          <button className={button} disabled={index === total - 1} title="Bajar" onClick={() => update(current => { moveItem(current.characters, index, index + 1); return current })}><ChevronDown size={12} /></button>
          <button className="p-1 text-red-400" title="Eliminar" onClick={() => update(current => {
            current.characters = current.characters.filter(item => item.id !== character.id)
            current.relationships = current.relationships.filter(item => item.fromCharacterId !== character.id && item.toCharacterId !== character.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={13} /></button>
        </div>
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        <Field label="Nombre" value={character.name} onChange={name => set({ name })} />
        <Field label="Papel en cámara" value={character.role} onChange={role => set({ role })} />
        <Field label="Aspecto reconocible" value={character.appearance} onChange={appearance => set({ appearance })} rows={3} />
        <Field label="Vestuario y continuidad" value={character.wardrobe} onChange={wardrobe => set({ wardrobe })} rows={3} />
        <div className="sm:col-span-2"><Field label="Prompt de identidad visual" value={character.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} /></div>
      </div>
      <details className="rounded border border-border px-2 py-1.5 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">Voz, motivación y restricciones opcionales</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <Field label="Voz / diálogo" value={character.voice} onChange={voice => set({ voice })} rows={2} />
          <Field label="Motivación visible" value={character.desire} onChange={desire => set({ desire })} rows={2} />
          <div className="sm:col-span-2"><Field label="Negative prompt" value={character.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={2} /></div>
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !character.visualPrompt.trim()}
          onClick={() => void generateVisual({ kind: 'character', id: character.id }, character.visualPrompt)}>
          {imageBusy === `character:${character.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {hasPrimary ? 'Crear variación' : 'Crear identidad'}
        </button>
        <button className={button} onClick={upload}><Upload size={13} /> Subir imágenes</button>
        <button className={`${button} ${character.approval === 'approved' ? 'border-emerald-500 text-emerald-400' : ''}`}
          disabled={!canApprove}
          title={requiresVisualIdentity
            ? hasPrimary ? 'Confirmar esta identidad para Director' : 'Selecciona y aprueba primero una imagen principal en Imágenes'
            : 'Confirmar la descripción para el modo de vídeo directo'}
          onClick={() => set({ approval: character.approval === 'approved' ? 'draft' : 'approved' })}>
          <Check size={13} /> {requiresVisualIdentity
            ? character.approval === 'approved' ? 'Identidad aprobada' : 'Aprobar identidad'
            : character.approval === 'approved' ? 'Descripción aprobada' : 'Aprobar descripción'}
        </button>
      </div>
      <ReferenceGallery ids={character.referenceAssetIds} assets={project.assets} primaryId={character.primaryReferenceAssetId}
        onPrimary={primaryReferenceAssetId => set({ primaryReferenceAssetId })} onRemove={removeReference} />
    </div>
  )
}

function CompactBeatEditor({ beat, index, total, update }: {
  beat: StoryBeat
  index: number
  total: number
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const set = (change: Partial<StoryBeat>) => update(current => {
    current.beats = current.beats.map(item => item.id === beat.id ? { ...item, ...change } : item)
    return current
  })
  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2">
      <div className="flex items-center gap-2">
        <span className="w-5 shrink-0 text-sm font-bold text-text-muted/60">{index + 1}</span>
        <input className={input} value={beat.title} onChange={event => set({ title: event.target.value })} placeholder="Nombre del momento" aria-label={`Momento ${index + 1}`} />
        <button className={button} disabled={index === 0} title="Subir" onClick={() => update(current => { moveItem(current.beats, index, index - 1); return current })}><ChevronUp size={12} /></button>
        <button className={button} disabled={index === total - 1} title="Bajar" onClick={() => update(current => { moveItem(current.beats, index, index + 1); return current })}><ChevronDown size={12} /></button>
        <button className="p-1 text-red-400" title="Eliminar" onClick={() => update(current => { current.beats = current.beats.filter(item => item.id !== beat.id); return current })}><Trash2 size={12} /></button>
      </div>
      <Field label="Qué vemos" value={beat.summary} onChange={summary => set({ summary })} rows={3} />
      <div className="grid sm:grid-cols-2 gap-2">
        <Field label="Tensión, obstáculo o impulso" value={beat.conflict} onChange={conflict => set({ conflict })} rows={2} />
        <Field label="Cambio que deja para el siguiente corte" value={beat.turn} onChange={turn => set({ turn })} rows={2} />
      </div>
      <details className="rounded border border-border px-2 py-1.5 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">Sección musical / función opcional</summary>
        <div className="mt-2 grid sm:grid-cols-2 gap-2">
          <Field label="Sección o fase" value={beat.stage} onChange={stage => set({ stage })} />
          <Field label="Objetivo del momento" value={beat.goal} onChange={goal => set({ goal })} rows={2} />
        </div>
      </details>
    </div>
  )
}

function CharacterEditor({
  character, index, total, project, update, imageBusy, generateVisual, upload, removeReference,
}: {
  character: StoryCharacter
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  imageBusy: string
  generateVisual: (target: { kind: 'character'; id: string }, prompt: string) => void
  upload: () => void
  removeReference: (id: string) => void
}) {
  const set = (patch: Partial<StoryCharacter>) => update(current => {
    current.characters = current.characters.map(item => item.id === character.id ? { ...item, approval: 'draft', ...patch } : item)
    return current
  })
  return (
    <div id={`story-review-character-${character.id}`} className={`${panel} scroll-mt-4 space-y-3`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary">{character.name}</h3>
          <button className={`${button} ${character.approval === 'approved' ? 'border-emerald-500 text-emerald-400' : ''}`} onClick={() => set({ approval: character.approval === 'approved' ? 'draft' : 'approved' })}>
            <Check size={12} /> {character.approval}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title="Move character up" onClick={() => update(current => {
            moveItem(current.characters, index, index - 1)
            return current
          })}><ChevronUp size={13} /></button>
          <button className={button} disabled={index === total - 1} title="Move character down" onClick={() => update(current => {
            moveItem(current.characters, index, index + 1)
            return current
          })}><ChevronDown size={13} /></button>
          <button className="text-red-400 p-1" onClick={() => update(current => {
            current.characters = current.characters.filter(item => item.id !== character.id)
            current.relationships = current.relationships.filter(item => item.fromCharacterId !== character.id && item.toCharacterId !== character.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="grid md:grid-cols-3 gap-3">
        <Field label="Name" value={character.name} onChange={name => set({ name })} />
        <Field label="Role" value={character.role} onChange={role => set({ role })} />
        <div className="grid grid-cols-2 gap-2">
          <Field label="Age" value={character.age} onChange={age => set({ age })} />
          <Field label="Pronouns" value={character.pronouns} onChange={pronouns => set({ pronouns })} />
        </div>
        <Field label="Personality" value={character.personality} onChange={personality => set({ personality })} rows={3} />
        <Field label="Desire" value={character.desire} onChange={desire => set({ desire })} rows={3} />
        <Field label="Need" value={character.need} onChange={need => set({ need })} rows={3} />
        <Field label="Flaw" value={character.flaw} onChange={flaw => set({ flaw })} rows={3} />
        <Field label="Conflict" value={character.conflict} onChange={conflict => set({ conflict })} rows={3} />
        <Field label="Arc" value={character.arc} onChange={arc => set({ arc })} rows={3} />
        <Field label="Voice / dialogue" value={character.voice} onChange={voice => set({ voice })} rows={3} />
        <Field label="Appearance" value={character.appearance} onChange={appearance => set({ appearance })} rows={3} />
        <Field label="Wardrobe / continuity" value={character.wardrobe} onChange={wardrobe => set({ wardrobe })} rows={3} />
        <Field label="Concept-art prompt" value={character.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} />
        <Field label="Negative visual prompt" value={character.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={4} />
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !character.visualPrompt.trim()} onClick={() => generateVisual({ kind: 'character', id: character.id }, character.visualPrompt)}>
          {imageBusy === `character:${character.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {character.primaryReferenceAssetId ? 'Generate identity variation' : 'Generate first identity'}
        </button>
        <button className={button} onClick={upload}><Upload size={13} /> Upload references</button>
      </div>
      <ReferenceGallery ids={character.referenceAssetIds} assets={project.assets} primaryId={character.primaryReferenceAssetId} onPrimary={id => set({ primaryReferenceAssetId: id })} onRemove={removeReference} />
    </div>
  )
}

function LocationEditor({
  location, index, total, project, update, imageBusy, generateVisual, upload, removeReference,
}: {
  location: StoryLocation
  index: number
  total: number
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
  imageBusy: string
  generateVisual: (target: { kind: 'location'; id: string }, prompt: string) => void
  upload: () => void
  removeReference: (id: string) => void
}) {
  const set = (patch: Partial<StoryLocation>) => update(current => {
    current.world.locations = current.world.locations.map(item => item.id === location.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} space-y-3`}>
      <div className="flex justify-between gap-2">
        <h4 className="text-sm font-semibold text-text-primary">{location.name}</h4>
        <div className="flex items-center gap-1">
          <button className={button} disabled={index === 0} title="Move location up" onClick={() => update(current => {
            moveItem(current.world.locations, index, index - 1)
            return current
          })}><ChevronUp size={13} /></button>
          <button className={button} disabled={index === total - 1} title="Move location down" onClick={() => update(current => {
            moveItem(current.world.locations, index, index + 1)
            return current
          })}><ChevronDown size={13} /></button>
          <button className="text-red-400 p-1" onClick={() => update(current => {
            current.world.locations = current.world.locations.filter(item => item.id !== location.id)
            pruneUnusedAssets(current)
            return current
          })}><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        <Field label="Name" value={location.name} onChange={name => set({ name })} />
        <Field label="Dramatic purpose" value={location.purpose} onChange={purpose => set({ purpose })} />
        <Field label="Description" value={location.description} onChange={description => set({ description })} rows={4} />
        <Field label="Concept prompt" value={location.visualPrompt} onChange={visualPrompt => set({ visualPrompt })} rows={4} />
        <Field label="Negative prompt" value={location.negativePrompt} onChange={negativePrompt => set({ negativePrompt })} rows={3} />
      </div>
      <div className="flex gap-2">
        <button className={button} disabled={Boolean(imageBusy) || !location.visualPrompt.trim()} onClick={() => generateVisual({ kind: 'location', id: location.id }, location.visualPrompt)}>
          {imageBusy === `location:${location.id}` ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {location.referenceAssetIds.length ? 'Generate another location' : 'Generate location'}
        </button>
        <button className={button} onClick={upload}><Upload size={13} /> Add reference</button>
      </div>
      <ReferenceGallery ids={location.referenceAssetIds} assets={project.assets} onRemove={removeReference} />
    </div>
  )
}

function RelationshipEditor({
  relationship, project, update,
}: {
  relationship: StoryRelationship
  project: StoryProject
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const set = (patch: Partial<StoryRelationship>) => update(current => {
    current.relationships = current.relationships.map(item => item.id === relationship.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} grid md:grid-cols-2 gap-3`}>
      <label className="text-[10px] text-text-muted">From
        <select className={`${input} mt-1`} value={relationship.fromCharacterId} onChange={event => set({ fromCharacterId: event.target.value })}>
          {project.characters.map(character => <option key={character.id} value={character.id}>{character.name}</option>)}
        </select>
      </label>
      <label className="text-[10px] text-text-muted">To
        <select className={`${input} mt-1`} value={relationship.toCharacterId} onChange={event => set({ toCharacterId: event.target.value })}>
          {project.characters.map(character => <option key={character.id} value={character.id}>{character.name}</option>)}
        </select>
      </label>
      <Field label="Relationship" value={relationship.label} onChange={label => set({ label })} />
      <button className="text-red-400 justify-self-end" onClick={() => update(current => {
        current.relationships = current.relationships.filter(item => item.id !== relationship.id)
        return current
      })}><Trash2 size={14} /></button>
      <Field label="Current dynamic" value={relationship.dynamic} onChange={dynamic => set({ dynamic })} rows={3} />
      <Field label="How it changes" value={relationship.evolution} onChange={evolution => set({ evolution })} rows={3} />
    </div>
  )
}

function BeatEditor({
  beat, index, total, update,
}: {
  beat: StoryBeat
  index: number
  total: number
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const set = (patch: Partial<StoryBeat>) => update(current => {
    current.beats = current.beats.map(item => item.id === beat.id ? { ...item, ...patch } : item)
    return current
  })
  return (
    <div className={`${panel} grid md:grid-cols-[60px_1fr_1fr] gap-3`}>
      <div className="space-y-2">
        <div className="text-2xl font-bold text-text-muted/40">{String(index + 1).padStart(2, '0')}</div>
        <div className="flex gap-1">
          <button className={button} disabled={index === 0} title="Move beat up" onClick={() => update(current => {
            moveItem(current.beats, index, index - 1)
            return current
          })}><ChevronUp size={12} /></button>
          <button className={button} disabled={index === total - 1} title="Move beat down" onClick={() => update(current => {
            moveItem(current.beats, index, index + 1)
            return current
          })}><ChevronDown size={12} /></button>
        </div>
      </div>
      <div className="space-y-3">
        <Field label="Stage" value={beat.stage} onChange={stage => set({ stage })} />
        <Field label="Title" value={beat.title} onChange={title => set({ title })} />
        <Field label="What happens" value={beat.summary} onChange={summary => set({ summary })} rows={4} />
      </div>
      <div className="space-y-3">
        <Field label="Dramatic goal" value={beat.goal} onChange={goal => set({ goal })} rows={2} />
        <Field label="Conflict" value={beat.conflict} onChange={conflict => set({ conflict })} rows={2} />
        <Field label="Turn / consequence" value={beat.turn} onChange={turn => set({ turn })} rows={3} />
        <button className="text-red-400 text-xs flex items-center gap-1" onClick={() => update(current => {
          current.beats = current.beats.filter(item => item.id !== beat.id)
          return current
        })}><Trash2 size={12} /> Remove beat</button>
      </div>
    </div>
  )
}
