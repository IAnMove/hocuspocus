import { useEffect, useMemo, useRef, useState } from 'react'
import JSZip from 'jszip'
import {
  BookOpen, Boxes, Check, ChevronDown, ChevronRight, ChevronUp, Copy, Download, ExternalLink, Film, ImagePlus, Loader2,
  Music, Network, Palette, Plus, RefreshCcw, Sparkles, Trash2, Upload, Users,
} from 'lucide-react'
import * as api from '../../api/client'
import { getModelMode, useStore } from '../../stores/useStore'
import { EditableLanguageInput } from '../../components/common/EditableLanguageInput'
import { generateImageAsset } from '../../lib/imageGeneration'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { getOutputReference } from '../../lib/outputReference'
import { AudioRangeSelector } from './AudioRangeSelector'
import { useComicStore } from '../comics/store'
import type { ComicProject } from '../comics/types'
import {
  buildComicAdaptation,
  buildMusicVideoAdaptation,
  buildShortFilmAdaptation,
  DEFAULT_COMIC_CHAPTER_DIRECTION,
  DEFAULT_SHORT_FILM_DIRECTION,
} from './adaptations'
import { normalizeStoryProject, storyId, useStoryStore } from './store'
import {
  applyStoryVisualStyle,
  normalizeStoryCharacter,
  storyNegativePromptForStyle,
} from './model'
import type {
  StoryBeat, StoryCharacter, StoryGenerationScope, StoryLocation, StoryProject,
  StoryMusicCandidate, StoryMusicCue, StoryRelationship, StoryVisualAsset, StoryWritingProvider,
} from './types'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'
const panel = 'rounded-xl border border-border bg-bg-secondary p-3 md:p-4'

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

function storySongBrief(project: StoryProject, durationSeconds: number): string {
  const cast = project.characters.slice(0, 5).map(character =>
    `${character.name}: ${character.desire}; arc: ${character.arc}`).join(' | ')
  const beats = project.beats.map(beat => `${beat.title}: ${beat.summary}`).join(' → ')
  return [
    `Create an original theme song that tells the story “${project.title}”.`,
    `Write all lyrics in ${project.language}. Target approximately ${durationSeconds} seconds.`,
    `Genre and emotional direction: ${project.genre}; ${project.tone}. Theme: ${project.theme}.`,
    `Premise: ${project.premise}. Synopsis: ${project.synopsis}. Ending: ${project.ending}.`,
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

type StoryTab = 'overview' | 'world' | 'characters' | 'relationships' | 'structure' | 'music' | 'productions'
type PendingDraft = {
  scope: StoryGenerationScope
  result: Record<string, unknown>
  selected: string[]
  replaceCollections: boolean
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

function draftPaths(result: Record<string, unknown>): string[] {
  const paths: string[] = []
  if (result.overview && typeof result.overview === 'object') {
    Object.keys(result.overview).forEach(key => paths.push(`overview.${key}`))
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
  label, value, onChange, rows = 1, placeholder = '',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
}) {
  return (
    <label className="block text-[10px] text-text-muted">
      {label}
      {rows > 1
        ? <textarea className={`${input} mt-1`} rows={rows} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />
        : <input className={`${input} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} />}
    </label>
  )
}

function Choice({
  label, value, options, onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  const custom = !options.includes(value)
  return (
    <label className="block text-[10px] text-text-muted">
      {label}
      <select
        className={`${input} mt-1`}
        value={custom ? '__other__' : value}
        onChange={event => onChange(event.target.value === '__other__' ? '' : event.target.value)}
      >
        {options.map(option => <option key={option}>{option}</option>)}
        <option value="__other__">Other…</option>
      </select>
      {custom && <input className={`${input} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={`Custom ${label.toLowerCase()}`} />}
    </label>
  )
}

function ProviderPanel({
  project, patch,
}: {
  project: StoryProject
  patch: (patch: Partial<StoryProject>) => void
}) {
  const services = useStore(state => state.servicesConfig)
  const models = useStore(state => state.models)
  const provider = project.provider.writingProvider
  const installedImageModels = models.filter(model =>
    model.is_downloaded !== false
    && getModelMode(model.model_type, model.family) === 'image')
  const writingReady = provider === 'maestro'
    || (provider === 'deepseek' && Boolean(services?.deepseek_api_key_set))
    || (provider === 'minimax' && Boolean(services?.minimax_api_key_set))
    || (provider === 'openai' && Boolean(services?.openai_api_key_set))
    || (provider === 'openai-compatible'
      && Boolean(services?.compatible_api_key_set && services?.compatible_base_url))
  const imageReady = project.provider.imageProvider === 'maestro'
    ? installedImageModels.some(model => model.model_type === project.provider.imageModel)
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
        <p className="text-[10px] text-text-muted mt-1">These choices belong only to this story. Writing and concept art remain independent.</p>
      </div>
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
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
      {ids.map(id => {
        const asset = assets[id]
        if (!asset) return null
        return (
          <div key={id} className={`relative rounded-lg overflow-hidden border ${id === primaryId ? 'border-emerald-400' : 'border-border'} bg-bg-tertiary`}>
            <img src={asset.source} alt={asset.name} className="w-full aspect-square object-cover" />
            <div className="absolute inset-x-0 bottom-0 flex justify-between bg-black/65 p-1">
              {onPrimary && <button className="text-[9px] text-white" onClick={() => onPrimary(id)}>{id === primaryId ? 'Primary' : 'Use'}</button>}
              <button className="text-red-300 ml-auto" onClick={() => onRemove(id)}><Trash2 size={11} /></button>
            </div>
          </div>
        )
      })}
    </div>
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
      <div className="flex flex-col sm:flex-row gap-2 lg:max-w-[620px]">
        <input className={`${input} sm:w-72`} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="Optional regeneration instruction…" />
        <button className={button} disabled={Boolean(busy)} onClick={() => onGenerate(scope)}>
          {busy === scope ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate section
        </button>
        <button className={`${button} ${approved ? 'border-emerald-500 text-emerald-400' : ''}`} onClick={onApprove}>
          <Check size={13} /> {approved ? 'Approved' : 'Approve'}
        </button>
      </div>
    </div>
  )
}

export function StoryLabPanel() {
  const project = useStoryStore(state => state.project)
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
  const enabledModels = useStore(state => state.enabledModels)
  const servicesConfig = useStore(state => state.servicesConfig)
  const filmImageModel = useStore(state => state.selectedModelPerMode.image) || 'flux2_klein_9b'
  const filmVideoModel = useStore(state => state.selectedModelPerMode.video) || 'ltx2_22B_distilled_1_1'
  const selectDirectorImageModel = useStore(state => state.selectDirectorImageModel)
  const selectDirectorVideoModel = useStore(state => state.selectDirectorVideoModel)
  const [tab, setTab] = useState<StoryTab>('overview')
  const [busy, setBusy] = useState<StoryGenerationScope | null>(null)
  const [imageBusy, setImageBusy] = useState('')
  const [referenceBatchBusy, setReferenceBatchBusy] = useState(false)
  const [productionBusy, setProductionBusy] = useState<'film' | 'music' | null>(null)
  const [musicCueBusy, setMusicCueBusy] = useState('')
  const [musicQueue, setMusicQueue] = useState<{ ids: string[]; index: number } | null>(null)
  const [instruction, setInstruction] = useState('')
  const [comicDirection, setComicDirection] = useState(DEFAULT_COMIC_CHAPTER_DIRECTION)
  const [comicPageCount, setComicPageCount] = useState(4)
  const [comicPanelsPerPage, setComicPanelsPerPage] = useState(4)
  const [filmDirection, setFilmDirection] = useState(DEFAULT_SHORT_FILM_DIRECTION)
  const [filmDuration, setFilmDuration] = useState(45)
  const [filmPreserveVisualStyle, setFilmPreserveVisualStyle] = useState(true)
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
      }
    } catch {
      return null
    }
  })
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const importRef = useRef<HTMLInputElement>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const musicCoverRef = useRef<HTMLInputElement>(null)
  const lyriaUploadRef = useRef<HTMLInputElement>(null)
  const lyriaUploadCueId = useRef('')
  const generationAbortRef = useRef<AbortController | null>(null)
  const [uploadTarget, setUploadTarget] = useState<{ kind: 'world' | 'character' | 'location'; id?: string } | null>(null)
  const musicCandidateOptions = useMemo(() => {
    const seen = new Set<string>()
    const options: Array<{ candidate: StoryMusicCandidate; cue?: StoryMusicCue; label: string }> = []
    project.music.cues.forEach(cue => cue.candidates.forEach(candidate => {
      if (seen.has(candidate.id)) return
      seen.add(candidate.id)
      options.push({ candidate, cue, label: `${cue.title} · ${candidate.model}` })
    }))
    project.music.candidates.forEach(candidate => {
      if (seen.has(candidate.id)) return
      seen.add(candidate.id)
      options.push({ candidate, label: `Story song · ${candidate.model}` })
    })
    return options
  }, [project.music.candidates, project.music.cues])
  const selectedMusicOption = musicCandidateOptions.find(option => option.candidate.id === musicProductionCandidateId)

  useEffect(() => {
    if (selectedMusicOption || !musicCandidateOptions.length) return
    const preferred = musicCandidateOptions.find(option => option.cue?.selectedCandidateId === option.candidate.id)
      || musicCandidateOptions[0]
    setMusicProductionCandidateId(preferred.candidate.id)
  }, [musicCandidateOptions, selectedMusicOption])

  useEffect(() => {
    const duration = selectedMusicOption?.candidate.durationSeconds || 0
    setMusicTrailerRange({ start: 0, end: duration, duration })
  }, [selectedMusicOption?.candidate.id, selectedMusicOption?.candidate.durationSeconds])
  const beginStoryActivity = (phase: string, message: string, total = 0) => {
    const id = `story-lab:${project.id}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    let failed = false
    useStore.getState().upsertActivity({
      id,
      kind: 'story_lab',
      title: 'Story Lab',
      status: 'running',
      phase,
      message,
      current: 0,
      total,
    })
    const updateActivity = (
      nextMessage: string,
      nextPhase = phase,
      current = 0,
      nextTotal = total,
    ) => {
      useStore.getState().upsertActivity({
        id,
        kind: 'story_lab',
        title: 'Story Lab',
        status: 'running',
        phase: nextPhase,
        message: nextMessage,
        current,
        total: nextTotal,
      })
    }
    return {
      update: updateActivity,
      fail: (error: unknown, nextPhase = phase) => {
        failed = true
        const errorMessage = error instanceof Error ? error.message : String(error)
        useStore.getState().upsertActivity({
          id,
          kind: 'story_lab',
          title: 'Story Lab',
          status: 'failed',
          phase: nextPhase,
          message: errorMessage,
          error: errorMessage,
        })
      },
      finish: () => {
        if (failed) return
        useStore.getState().removeActivity(id)
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

  useEffect(() => {
    loadWorkspace(activeWorkspace)
  }, [activeWorkspace, loadWorkspace])

  useEffect(() => {
    setRecoveryJobId(window.localStorage.getItem(storyJobKey(activeWorkspace, project.id)) || '')
    setComicDirection(DEFAULT_COMIC_CHAPTER_DIRECTION)
    setComicPageCount(4)
    setComicPanelsPerPage(4)
    setFilmDirection(DEFAULT_SHORT_FILM_DIRECTION)
    setFilmDuration(45)
    try {
      const saved = JSON.parse(window.localStorage.getItem(storyResultKey(activeWorkspace, project.id)) || 'null')
      setPendingDraft(saved?.result ? {
        scope: saved.scope || 'all',
        result: saved.result,
        selected: draftPaths(saved.result),
        replaceCollections: true,
      } : null)
    } catch {
      setPendingDraft(null)
    }
  }, [activeWorkspace, project.id])

  const approve = (key: keyof StoryProject['approvals']) => {
    if (key === 'overview' && (!project.premise.trim() || !project.logline.trim() || !project.synopsis.trim())) {
      setNotice({ kind: 'error', text: 'Premise, logline and synopsis are required before approving the story.' })
      setTab('overview')
      return
    }
    if (key === 'world' && (!project.world.summary.trim() || !project.world.visualLanguage.trim())) {
      setNotice({ kind: 'error', text: 'Add a world summary and visual language before approving the world.' })
      setTab('world')
      return
    }
    if (key === 'characters') {
      const incomplete = project.characters.filter(character =>
        character.approval !== 'approved'
        || !character.primaryReferenceAssetId
        || !project.assets[character.primaryReferenceAssetId])
      if (!project.characters.length || incomplete.length) {
        setNotice({
          kind: 'error',
          text: 'Approve each character and select a valid primary visual identity before approving the cast.',
        })
        setTab('characters')
        return
      }
    }
    if (key === 'relationships' && project.relationships.some(relationship =>
      !relationship.fromCharacterId
      || !relationship.toCharacterId
      || relationship.fromCharacterId === relationship.toCharacterId
      || !relationship.dynamic.trim())) {
      setNotice({ kind: 'error', text: 'Every relationship needs two different characters and a current dynamic.' })
      setTab('relationships')
      return
    }
    if (key === 'structure' && (
      project.beats.length < 3
      || project.beats.some(beat => !beat.summary.trim() || !beat.conflict.trim() || !beat.turn.trim())
    )) {
      setNotice({ kind: 'error', text: 'Use at least three causal beats, each with action, conflict and a consequence.' })
      setTab('structure')
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
          if (chosen.has(`overview.${key}`) && typeof value === 'string') {
            ;(next as unknown as Record<string, unknown>)[key] = value
          }
        })
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
  }

  const completeGeneratedDraft = async (
    scope: StoryGenerationScope,
    result: Record<string, unknown>,
  ) => {
    if (project.workflowMode === 'guided') {
      setPendingDraft({
        scope,
        result,
        selected: draftPaths(result),
        replaceCollections: true,
      })
      setNotice({ kind: 'ok', text: 'A generated draft is ready. Review the changes before applying them.' })
      return
    }
    applyGeneratedResult(result)
    if (scope === 'all') {
      const generated = useStoryStore.getState().project
      const imageCount = (generated.world.visualPrompt && !generated.world.referenceAssetIds.length ? 1 : 0)
        + generated.characters.filter(character =>
          character.visualPrompt && !character.referenceAssetIds.length).length
        + generated.world.locations.filter(location =>
          location.visualPrompt && !location.referenceAssetIds.length).length
      if (imageCount > 0 && project.provider.imageProvider === 'minimax' && !window.confirm(
        `Automatic mode will now generate ${imageCount} MiniMax concept image${imageCount === 1 ? '' : 's'}, which may use provider credits. Continue?`,
      )) {
        setTab('characters')
        return
      }
      if (generated.world.visualPrompt && generated.world.referenceAssetIds.length === 0) {
        const worldReady = await generateVisual({ kind: 'world' }, generated.world.visualPrompt)
        if (!worldReady) {
          setTab('characters')
          return
        }
      }
      for (const character of generated.characters) {
        if (character.visualPrompt && character.referenceAssetIds.length === 0) {
          const ready = await generateVisual({ kind: 'character', id: character.id }, character.visualPrompt)
          if (!ready) {
            setTab('characters')
            return
          }
        }
      }
      for (const location of generated.world.locations) {
        if (location.visualPrompt && location.referenceAssetIds.length === 0) {
          const ready = await generateVisual(
            { kind: 'location', id: location.id },
            location.visualPrompt,
          )
          if (!ready) {
            setTab('world')
            return
          }
        }
      }
      setNotice({ kind: 'ok', text: 'Automatic Story Lab pass completed: staged bible and first-look concepts are ready.' })
      setTab('productions')
    }
  }

  const generate = async (scope: StoryGenerationScope) => {
    if (!project.premise.trim()) {
      setNotice({ kind: 'error', text: 'Write a premise first.' })
      return
    }
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
    try {
      const { result } = await api.generateStorySection({
        scope,
        premise: project.premise,
        language: project.language,
        genre: project.genre,
        tone: project.tone,
        audience: project.audience,
        instruction,
        project,
        writingProvider: project.provider.writingProvider,
        writingModel: project.provider.writingModel,
        writingBaseUrl: project.provider.writingBaseUrl,
        workspace: activeWorkspace,
      }, progress => {
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
      }))
      if (useStoryStore.getState().project.id !== sourceProjectId) {
        setNotice({ kind: 'ok', text: 'Generation completed and was saved with its source story. Reopen that story to review the draft.' })
        return
      }
      await completeGeneratedDraft(scope, result)
    } catch (error) {
      if ((error as Error).name !== 'AbortError') activity.fail(error)
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
    setBusy('all')
    setNotice(null)
    try {
      const { result } = await api.resumeStoryGeneration(recoveryJobId.trim(), progress => {
        setJobProgress(`${progress.message} ${progress.total ? `${progress.current}/${progress.total}` : ''}`)
        activity.update(
          progress.message,
          progress.stage === 'music' ? 'music_planning' : `story_${progress.stage || 'planning'}`,
          progress.current,
          progress.total,
        )
      })
      if (useStoryStore.getState().project.id !== sourceProjectId) return
      setPendingDraft({
        scope: 'all',
        result,
        selected: draftPaths(result),
        replaceCollections: true,
      })
      window.localStorage.setItem(storyResultKey(activeWorkspace, project.id), JSON.stringify({
        jobId: recoveryJobId,
        scope: 'all',
        result,
      }))
      setNotice({ kind: 'ok', text: 'Recovered Story Lab draft is ready for review.' })
    } catch (error) {
      activity.fail(error)
      setNotice({ kind: 'error', text: (error as Error).message })
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
    } = {},
  ) => {
    if (!prompt.trim()) return
    const key = `${target.kind}:${target.id || 'world'}`
    const current = useStoryStore.getState().project
    const sourceProjectId = current.id
    const character = target.kind === 'character'
      ? current.characters.find(item => item.id === target.id) : undefined
    const location = target.kind === 'location'
      ? current.world.locations.find(item => item.id === target.id) : undefined
    const negativePrompt = target.kind === 'world'
      ? current.world.negativePrompt
      : character?.negativePrompt || location?.negativePrompt || ''
    const compatibleNegativePrompt = storyNegativePromptForStyle(
      negativePrompt,
      current.visualStyle,
      current.enforceVisualStyle,
    )
    const primaryReference = options.usePrimaryReference !== false && character?.primaryReferenceAssetId
      ? current.assets[character.primaryReferenceAssetId]?.source
      : undefined
    const effectivePrompt = [
      applyStoryVisualStyle(prompt, current.visualStyle, current.enforceVisualStyle),
      'Single concept-art image, one coherent view, no contact sheet, no grid, no text, no labels.',
      compatibleNegativePrompt ? `Strictly avoid: ${compatibleNegativePrompt}.` : '',
    ].filter(Boolean).join(' ')
    const jobKey = `${key}:${stableTextKey(effectivePrompt)}`
    setImageBusy(key)
    if (!options.quiet) setNotice(null)
    try {
      const generated = await generateImageAsset(
        current.provider.imageProvider,
        effectivePrompt,
        current.provider.imageModel,
        primaryReference,
        negativePrompt.trim(),
        {
          panelId: `story-${jobKey}`,
          existingJobId: current.visualJobs[jobKey],
          onJobSubmitted: jobId => update(latest => {
            if (latest.id !== sourceProjectId) return latest
            Object.keys(latest.visualJobs)
              .filter(item => item.startsWith(`${key}:`))
              .forEach(item => { delete latest.visualJobs[item] })
            latest.visualJobs[jobKey] = jobId
            return latest
          }),
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
        provider: current.provider.imageProvider,
        model: generated.model,
        createdAt: new Date().toISOString(),
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
    const style = project.visualStyle.trim()
    if (!style) {
      setNotice({ kind: 'error', text: 'Write a visual style before applying it to prompts.' })
      return
    }
    let changed = 0
    update(current => {
      current.enforceVisualStyle = true
      const apply = (value: string) => {
        if (!value.trim()) return value
        changed += 1
        return applyStoryVisualStyle(value, current.visualStyle, true)
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

  const regenerateStyledReferences = async () => {
    const current = useStoryStore.getState().project
    if (!current.visualStyle.trim()) {
      setNotice({ kind: 'error', text: 'Write a visual style before regenerating references.' })
      return
    }
    const targets: Array<{
      target: { kind: 'world' | 'character' | 'location'; id?: string }
      label: string
      prompt: string
    }> = []
    if (current.world.visualPrompt.trim()) {
      targets.push({ target: { kind: 'world' }, label: 'world', prompt: current.world.visualPrompt })
    }
    current.characters.forEach(character => {
      if (character.visualPrompt.trim()) {
        targets.push({
          target: { kind: 'character', id: character.id },
          label: character.name,
          prompt: character.visualPrompt,
        })
      }
    })
    current.world.locations.forEach(location => {
      if (location.visualPrompt.trim()) {
        targets.push({
          target: { kind: 'location', id: location.id },
          label: location.name,
          prompt: location.visualPrompt,
        })
      }
    })
    if (!targets.length) {
      setNotice({ kind: 'error', text: 'Add at least one world, character or location visual prompt first.' })
      return
    }
    const creditWarning = current.provider.imageProvider === 'minimax'
      ? ' This may use MiniMax provider credits.' : ''
    if (!window.confirm(
      `Generate ${targets.length} styled reference image${targets.length === 1 ? '' : 's'}? Each successful result will replace that target's old references; failed targets keep their current references.${creditWarning}`,
    )) return

    update(latest => {
      latest.enforceVisualStyle = true
      return latest
    })
    setReferenceBatchBusy(true)
    setNotice(null)
    let completed = 0
    let lastError = ''
    try {
      for (const item of targets) {
        setNotice({
          kind: 'ok',
          text: `Regenerating styled references ${completed + 1}/${targets.length}: ${item.label}`,
        })
        const ready = await generateVisual(item.target, item.prompt, {
          replaceReferences: true,
          usePrimaryReference: false,
          quiet: true,
          onError: message => { lastError = message },
        })
        if (!ready) break
        completed += 1
      }
      setNotice(completed === targets.length
        ? {
            kind: 'ok',
            text: `Regenerated ${completed} visual reference${completed === 1 ? '' : 's'} with the current style. Old detached assets were removed from the Story Lab library.`,
          }
        : {
            kind: 'error',
            text: `Stopped after ${completed}/${targets.length} references. Completed replacements were kept; the failed target kept its old reference. ${lastError}`.trim(),
          })
    } finally {
      setReferenceBatchBusy(false)
    }
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
        }, uploadTarget)
      }
    } catch (error) {
      setNotice({ kind: 'error', text: (error as Error).message })
    } finally {
      setImageBusy('')
      if (uploadRef.current) uploadRef.current.value = ''
    }
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
  ) => {
    const adaptation = buildShortFilmAdaptation(source, direction, targetDuration, {
      preserveVisualStyle,
    })
    const director = useStore.getState()
    director.directorReset()
    const store = useStore.getState()
    store.setGenerationMode('video')
    if (imageModel) {
      useStore.getState().selectDirectorImageModel(imageModel)
    }
    if (videoModel) {
      await useStore.getState().selectDirectorVideoModel(videoModel)
    }
    // setSidebarMode normally sends a fresh Director session to its route
    // chooser. Open it before restoring the Story Lab payload, otherwise it
    // overwrites the preloaded `style` step with `upload`.
    store.setSidebarMode('director')
    store.directorSetSceneDescription(adaptation.sceneDescription)
    store.setDirectorSkill('short_film')
    store.shortFilmSetPath('story')
    store.shortFilmSetCharacters(adaptation.characters)
    store.shortFilmSetTargetDuration(adaptation.targetDuration)
    store.shortFilmSetNarrative(adaptation.narrative)
    store.shortFilmSetVisualStyle(adaptation.visualStyle)
    store.shortFilmSetPreserveVisualStyle(adaptation.preserveVisualStyle)
    store.setDirectorAutoMode(autoStart)
    useStore.setState({
      directorWritingProvider: source.provider.writingProvider,
      directorWritingModel: source.provider.writingModel,
      directorWritingBaseUrl: source.provider.writingBaseUrl,
    })
    for (const reference of adaptation.characterReferences) {
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
    for (const reference of adaptation.locationReferences) {
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
    const director = useStore.getState()
    const hasDirectorWork = Boolean(
      director.directorSceneDescription.trim()
      || director.directorPlannedClips.length
      || director.directorCharacterRefs.length
      || director.directorLocationRefs.length,
    )
    const confirmed = autoStart
      ? window.confirm(
        'Generate a complete short-film episode from this story? The current Director draft will be replaced and image/video generation may use provider credits.',
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

  const writeStorySong = async () => {
    const activity = beginStoryActivity('writing_song', 'Story Lab is writing the song prompt and lyrics…', 1)
    setProductionBusy('music')
    try {
      const brief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds)
      const written = await api.writeSong({
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
      const brief = project.music.brief.trim()
        || storySongBrief(project, project.music.targetDurationSeconds)
      let style = project.music.style.trim()
      let lyrics = project.music.lyrics.trim()
      if (!style || (project.music.mode === 'original' && !lyrics)) {
        activity.update('Story Lab is writing the missing song prompt and lyrics…', 'writing_song', 0, 1)
        const written = await api.writeSong({
          target: 'minimax',
          model: project.music.mode === 'cover' ? 'music-cover' : project.music.model,
          description: brief,
          style_direction: style || `${project.genre}, ${project.tone}`,
          lyrics_direction: lyrics || project.music.sourceLyrics,
          story_context: storySongBrief(project, project.music.targetDurationSeconds),
          language: project.language,
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
      })
      const createdAt = new Date().toISOString()
      const candidates = result.candidates.map(candidate => ({
        id: storyId('song'),
        name: candidate.filename,
        source: candidate.source,
        prompt: style,
        lyrics,
        provider: 'minimax' as const,
        model: candidate.model,
        durationSeconds: candidate.duration_seconds,
        createdAt,
      }))
      patch({
        music: {
          ...project.music,
          brief,
          style,
          lyrics,
          candidates: [...project.music.candidates, ...candidates],
          selectedCandidateId: candidates[0]?.id || project.music.selectedCandidateId,
        },
      })
      setNotice({ kind: 'ok', text: `${candidates.length} MiniMax Music candidates generated. Listen and choose one for the musical trailer.` })
    } catch (error) {
      activity.fail(error, 'generating_music')
      setNotice({ kind: 'error', text: `MiniMax Music could not generate the candidates: ${(error as Error).message}` })
    } finally {
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

  const adaptMusicCueWithLlm = async (cueId: string) => {
    const cue = useStoryStore.getState().project.music.cues.find(item => item.id === cueId)
    if (!cue) return
    if (!cue.referenceSong.trim()) {
      setNotice({ kind: 'error', text: 'Add an example reference song before adapting this proposal.' })
      return
    }
    const activity = beginStoryActivity('music_planning', `Story Lab is adapting “${cue.title}”…`, 1)
    setMusicCueBusy(`llm:${cueId}`)
    try {
      const target = cue.kind === 'character'
        ? project.characters.find(character => character.id === cue.targetId)?.name || cue.targetId
        : cue.kind === 'world' ? 'the Story world' : 'the complete Story'
      const written = await api.writeSong({
        target: 'minimax',
        model: project.music.model,
        instrumental: cue.instrumental,
        description: `Create an entirely original ${cue.instrumental ? 'instrumental music cue' : 'song'} for ${target}. Purpose in this Story: ${cue.purpose}.`,
        reference_song: cue.referenceSong,
        style_direction: cue.brief,
        lyrics_direction: cue.lyrics,
        story_context: storySongBrief(project, cue.durationSeconds),
        language: project.language,
        duration_seconds: cue.durationSeconds,
        include_lyria: true,
        max_new_tokens: 3000,
      })
      patchMusicCue(cueId, {
        style: written.style,
        lyrics: written.lyrics,
        lyriaPrompt: written.lyria_prompt,
      })
      setNotice({ kind: 'ok', text: `“${cue.title}” now has editable MiniMax and Google Lyria prompts${cue.instrumental ? '' : ' with structured lyrics'}.` })
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
      const candidate = {
        id: storyId('song'),
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

  const generateMusicCueAudio = async (cueId: string, queued = false): Promise<boolean> => {
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
      })
      const createdAt = new Date().toISOString()
      const candidates = result.candidates.map(candidate => ({
        id: storyId('song'),
        name: candidate.filename,
        source: candidate.source,
        prompt,
        lyrics: cue.lyrics,
        provider: 'minimax' as const,
        model: candidate.model,
        durationSeconds: candidate.duration_seconds,
        createdAt,
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
        setNotice({ kind: 'ok', text: `MiniMax generated “${cue.title}”. The result is saved under this proposal.` })
      }
      return true
    } catch (error) {
      activity?.fail(error, 'generating_music')
      setNotice({ kind: 'error', text: `“${cue.title}” could not be generated: ${(error as Error).message}` })
      return false
    } finally {
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
    setMusicQueue({ ids, index: 0 })
    let completed = 0
    try {
      for (let index = 0; index < ids.length; index += 1) {
        setMusicQueue({ ids, index })
        const cue = useStoryStore.getState().project.music.cues.find(item => item.id === ids[index])
        activity.update(
          `Generating “${cue?.title || `track ${index + 1}`}” · ${index + 1}/${ids.length}`,
          'music_queue',
          index,
          ids.length,
        )
        const ready = await generateMusicCueAudio(ids[index], true)
        if (!ready) break
        completed += 1
        activity.update(
          `Completed “${cue?.title || `track ${index + 1}`}” · ${completed}/${ids.length}`,
          'music_queue',
          completed,
          ids.length,
        )
      }
      if (completed === ids.length) {
        setNotice({ kind: 'ok', text: `Music queue completed: ${completed} tracks generated one after another.` })
      } else {
        activity.fail(new Error(`Music queue stopped after ${completed}/${ids.length}`), 'music_queue')
        setNotice(current => current?.kind === 'error' ? current : {
          kind: 'error', text: `Music queue stopped after ${completed}/${ids.length}; completed tracks were preserved.`,
        })
      }
    } finally {
      activity.finish()
      setMusicCueBusy('')
      setMusicQueue(null)
    }
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
    title: candidate.name,
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
  ) => {
    const resolvedCue = effectiveMusicCue(source, cue, candidate)
    const adaptation = buildMusicVideoAdaptation(source, resolvedCue)
    const director = useStore.getState()
    director.directorReset()
    const store = useStore.getState()
    store.setGenerationMode('video')
    store.setSidebarMode('director')
    store.setDirectorSkill('music_video')
    store.setDirectorAutoMode(autoStart)
    store.directorSetSceneDescription(adaptation.sceneDescription)
    useStore.setState({
      directorMusicSource: 'upload',
      directorSongDescription: resolvedCue.brief,
      directorSongStyle: resolvedCue.style,
      directorSongLyrics: resolvedCue.lyrics,
      directorSongDuration: excerpt ? excerpt.end - excerpt.start : resolvedCue.durationSeconds,
      directorPacingProfile: pacing,
      directorStep: 'upload',
    })

    for (const reference of adaptation.characterReferences) {
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
    for (const reference of adaptation.locationReferences) {
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
    }
    return { adaptation, resolvedCue, pipelineId: useStore.getState().pipelineId }
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
    const cue = musicCueForCandidate(project, candidateId)
    const candidate = musicCandidateById(project, candidateId)
    if (!candidate) {
      const director = useStore.getState()
      director.directorReset()
      director.setGenerationMode('video')
      director.setSidebarMode('director')
      director.setDirectorSkill('music_video')
      director.setDirectorAutoMode(false)
      useStore.setState({ directorMusicSource: 'generate', directorStep: 'upload' })
      window.dispatchEvent(new Event('maestro:director-open'))
      return
    }
    setProductionBusy('music')
    const activity = beginStoryActivity(
      'preparing_music_video',
      `Loading “${candidate.name}” and its Story references…`,
      3,
    )
    try {
      activity.update('Loading character and world references…', 'preparing_music_video', 1, 3)
      const loaded = await loadMusicVideoProduction(
        project,
        cue,
        candidate,
        options.autoStart === true,
        options.pacing || musicProductionPacing,
        options.mode === 'trailer' ? options.excerpt : undefined,
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
              imageModel: filmImageModel,
              videoModel: filmVideoModel,
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
    if (!selectedMusicOption) {
      setNotice({ kind: 'error', text: 'Generate or import a song in Music before creating a music video.' })
      return
    }
    if (musicProductionMode === 'trailer' && musicTrailerRange.end <= musicTrailerRange.start + 0.99) {
      setNotice({ kind: 'error', text: 'Choose and preview a trailer excerpt of at least one second.' })
      return
    }
    if (autoStart && !window.confirm(
      `Generate the ${musicProductionMode === 'trailer' ? 'musical trailer' : 'complete music video'} for “${selectedMusicOption.label}”? `
      + 'This creates one start image and one video render per planned clip and may consume provider credits.',
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
      const current = useStore.getState()
      const hasWork = Boolean(current.directorSceneDescription.trim() || current.directorPlannedClips.length)
      if (hasWork && !window.confirm(
        'Reopen this music-video production? The current Director draft will be replaced.',
      )) return
      setProductionBusy('music')
      try {
        await loadMusicVideoProduction(source, cue, candidate, false, pacing, excerpt)
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
      'Reopen this film staging? The current Director draft will be replaced.',
    )) return
    const direction = typeof production.targetSnapshot?.direction === 'string'
      ? production.targetSnapshot.direction
      : DEFAULT_SHORT_FILM_DIRECTION
    const targetDuration = Number(production.targetSnapshot?.targetDuration) || 45
    const preserveVisualStyle = production.targetSnapshot?.preserveVisualStyle !== false
    const videoModel = typeof production.targetSnapshot?.videoModel === 'string'
      ? production.targetSnapshot.videoModel
      : filmVideoModel
    const imageModel = typeof production.targetSnapshot?.imageModel === 'string'
      ? production.targetSnapshot.imageModel
      : filmImageModel
    await loadFilmProduction(source, direction, false, targetDuration, preserveVisualStyle, videoModel, imageModel)
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

  const tabs: Array<{ id: StoryTab; label: string; icon: typeof BookOpen }> = [
    { id: 'overview', label: 'Story', icon: BookOpen },
    { id: 'world', label: 'World', icon: Boxes },
    { id: 'characters', label: 'Characters', icon: Users },
    { id: 'music', label: 'Music', icon: Music },
    { id: 'relationships', label: 'Relationships', icon: Network },
    { id: 'structure', label: 'Structure', icon: ChevronRight },
    { id: 'productions', label: 'Productions', icon: Film },
  ]
  const progress = useMemo(() => [
    Boolean(project.logline && project.synopsis),
    Boolean(project.world.summary),
    project.characters.length > 0,
    project.beats.length >= 6,
  ].filter(Boolean).length, [project])
  const productionIssues = (() => {
    if (project.workflowMode === 'automatic') return []
    const required: Array<keyof StoryProject['approvals']> = [
      'overview', 'world', 'characters', 'structure',
    ]
    if (project.relationships.length) required.push('relationships')
    const issues = required
      .filter(section => !isApproved(section))
      .map(section => `Approve ${section}`)
    if (project.characters.some(character =>
      character.approval !== 'approved'
      || !character.primaryReferenceAssetId
      || !project.assets[character.primaryReferenceAssetId])) {
      issues.push('Approve every character identity')
    }
    return issues
  })()

  return (
    <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-bg-primary overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg-secondary px-3 py-2">
        <div className="mr-auto">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-accent-blue" />
            <span className="text-sm font-semibold text-text-primary">Story Lab</span>
            <span className="text-[10px] text-text-muted">v{project.revision} · {progress}/4 foundations</span>
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
          <p className="text-[9px] text-text-muted mt-0.5">One editable story bible for comics, films and future adaptations.</p>
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
        <select className={`${input} w-auto`} value={project.workflowMode} onChange={event => patch({ workflowMode: event.target.value as StoryProject['workflowMode'] })}>
          <option value="guided">Guided · approve stages</option>
          <option value="automatic">Automatic · one click</option>
        </select>
        <button className={button} onClick={() => generate('all')} disabled={Boolean(busy)}>
          {busy === 'all' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {jobProgress || 'Generate story bible'}
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
        <button className={button} disabled={Boolean(busy || imageBusy)} onClick={newProject}><Plus size={13} /> New</button>
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
            <p>Manual edits are always authoritative.</p>
            <p>Regeneration preserves existing reference images.</p>
            <p>Adaptations remember the source revision.</p>
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
                    <button className={`${button} border-emerald-500/50 text-emerald-300`} disabled={!pendingDraft.selected.length} onClick={() => applyGeneratedResult(
                      pendingDraft.result,
                      pendingDraft.selected,
                      pendingDraft.replaceCollections,
                    )}><Check size={13} /> Apply selected</button>
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
                <SectionHeader title="Story and intent" description="Define what the story is about before choosing shots or panels." scope="overview" busy={busy} approved={isApproved('overview')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('overview')} />
                <div className="grid xl:grid-cols-[1fr_360px] gap-4">
                  <div className={`${panel} grid md:grid-cols-2 gap-3`}>
                    <Field label="Title" value={project.title} onChange={title => patch({ title })} />
                    <label className="block text-[10px] text-text-muted">
                      Language
                      <EditableLanguageInput
                        className={`${input} mt-1`}
                        value={project.language}
                        onChange={language => patch({ language })}
                      />
                    </label>
                    <Choice label="Genre" value={project.genre} options={GENRES} onChange={genre => patch({ genre })} />
                    <Choice label="Tone" value={project.tone} options={TONES} onChange={tone => patch({ tone })} />
                    <Field label="Audience" value={project.audience} onChange={audience => patch({ audience })} />
                    <Field label="Theme" value={project.theme} onChange={theme => patch({ theme })} />
                    <Field label="What the story is about / premise" value={project.premise} onChange={premise => patch({ premise })} rows={5} placeholder="Who wants what, what stops them, and what happens if they fail?" />
                    <Field label="Visual style / independent art direction" value={project.visualStyle} onChange={visualStyle => patch({ visualStyle })} rows={5} placeholder="For example: hand-painted 2D animation, watercolor backgrounds, clean ink contours, warm muted palette…" />
                    <div className="md:col-span-2 rounded-lg border border-border bg-bg-tertiary/50 p-3 space-y-2">
                      <label className="flex items-start gap-2 text-xs text-text-secondary cursor-pointer">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={project.enforceVisualStyle}
                          onChange={event => patch({ enforceVisualStyle: event.target.checked })}
                        />
                        <span>
                          <span className="font-medium text-text-primary">Enforce this style on every Story image</span>
                          <span className="block mt-0.5 text-[10px] text-text-muted">Adds a highest-priority render-time lock while keeping story and subject prompts independent, so changing style does not require regenerating the bible.</span>
                        </span>
                      </label>
                      <div className="flex flex-wrap gap-2">
                        <button className={button} disabled={!project.visualStyle.trim()} onClick={writeStyleIntoPrompts}>
                          <Palette size={13} /> Write/replace style lock in existing prompts
                        </button>
                        <button className={button} disabled={!project.visualStyle.trim() || Boolean(imageBusy) || referenceBatchBusy} onClick={regenerateStyledReferences}>
                          {referenceBatchBusy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />} Regenerate all visual references in this style
                        </button>
                      </div>
                    </div>
                    <div className="md:col-span-2"><Field label="Logline" value={project.logline} onChange={logline => patch({ logline })} rows={2} /></div>
                    <div className="md:col-span-2"><Field label="Synopsis" value={project.synopsis} onChange={synopsis => patch({ synopsis })} rows={8} /></div>
                    <div className="md:col-span-2"><Field label="Ending / final image" value={project.ending} onChange={ending => patch({ ending })} rows={3} /></div>
                  </div>
                  <ProviderPanel project={project} patch={patch} />
                </div>
              </>
            )}

            {tab === 'world' && (
              <>
                <SectionHeader title="World bible" description="Rules, places and a visual language that every production can reuse." scope="world" busy={busy} approved={isApproved('world')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('world')} />
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
                <SectionHeader title="Characters" description="Personality, dramatic function, voice and approved visual identity live together." scope="characters" busy={busy} approved={isApproved('characters')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('characters')} />
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
                <SectionHeader title="Relationships" description="Conflict and change often live between characters, not inside isolated biographies." scope="relationships" busy={busy} approved={isApproved('relationships')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('relationships')} />
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
                <SectionHeader title="Dramatic structure" description="A causal sequence: every beat changes the situation and motivates the next." scope="structure" busy={busy} approved={isApproved('structure')} instruction={instruction} setInstruction={setInstruction} onGenerate={generate} onApprove={() => approve('structure')} />
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
                    <p className="text-xs text-text-muted mt-1">LLM-authored ambience, character presentation themes and three story songs. Suggestions cost no MiniMax music credits until you generate audio.</p>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2 xl:max-w-[760px]">
                    <input className={`${input} sm:w-72`} value={instruction}
                      onChange={event => setInstruction(event.target.value)}
                      placeholder="Optional music direction…" />
                    <button className={button} disabled={Boolean(busy || musicQueue)} onClick={() => generate('music')}>
                      {busy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate LLM suggestions
                    </button>
                    <button className={`${button} border-pink-500/60 text-pink-300`}
                      disabled={Boolean(busy || musicQueue || musicCueBusy) || !project.music.cues.length || !servicesConfig?.minimax_api_key_set}
                      onClick={() => void generateAllMusicCues()}>
                      {musicQueue ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />}
                      {musicQueue ? `Queue ${musicQueue.index + 1}/${musicQueue.ids.length}` : 'Generate all sequentially'}
                    </button>
                  </div>
                </div>

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
                                    <label className="block text-[10px] text-text-muted">Duration · seconds
                                      <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                                        value={cue.durationSeconds}
                                        onChange={event => patchMusicCue(cue.id, { durationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) })} />
                                    </label>
                                  </div>
                                  <button className={`${button} w-full`} disabled={Boolean(musicCueBusy || musicQueue) || !cue.referenceSong.trim()}
                                    onClick={() => void adaptMusicCueWithLlm(cue.id)}>
                                    {adapting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Adapt provider prompt{cue.instrumental ? '' : ' + lyrics'} with LLM
                                  </button>
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
                                  <Field label={`prompt · ${cue.style.trim().length}/300 characters`} value={cue.style}
                                    onChange={style => patchMusicCue(cue.id, { style })} rows={3} />
                                  <p className="text-[9px] text-text-muted">Genre, mood, instruments, voice, tempo and production. Anything after character 300 is not sent.</p>
                                  {!cue.instrumental && <Field label="lyrics · structured separately" value={cue.lyrics}
                                    onChange={lyrics => patchMusicCue(cue.id, { lyrics })} rows={10} />}
                                  {!cue.instrumental && cue.lyrics.trim() && !MINIMAX_LYRIC_SECTION.test(cue.lyrics) && (
                                    <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[9px] text-amber-200">
                                      These lyrics have no supported section tags. Use the LLM adaptation or add [Verse], [Pre Chorus], [Chorus], [Bridge] and [Outro] before generating.
                                    </p>
                                  )}
                                  <details className="rounded border border-border bg-bg-tertiary/70 p-2">
                                    <summary className="cursor-pointer text-[9px] text-text-secondary">Inspect the complete Maestro → MiniMax payload</summary>
                                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[9px] text-text-muted">{miniMaxCuePayload(cue, project.music.model)}</pre>
                                  </details>
                                  <div className="grid sm:grid-cols-2 gap-2">
                                    <button className={button} onClick={() => {
                                      void navigator.clipboard.writeText(miniMaxCuePayload(cue, project.music.model))
                                      setNotice({ kind: 'ok', text: `MiniMax payload for “${cue.title}” copied.` })
                                    }}><Copy size={12} /> Copy exact payload</button>
                                    <button className={`${button} border-pink-500/60 text-pink-300`}
                                      disabled={Boolean(musicCueBusy || musicQueue) || !servicesConfig?.minimax_api_key_set || !cue.style.trim() || (!cue.instrumental && (!cue.lyrics.trim() || !MINIMAX_LYRIC_SECTION.test(cue.lyrics)))}
                                      onClick={() => void generateMusicCueAudio(cue.id)}>
                                      {generatingAudio ? <Loader2 size={13} className="animate-spin" /> : <Music size={13} />} Generate this track
                                    </button>
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
                                    <button className={button} disabled={Boolean(musicCueBusy || musicQueue) || !cue.referenceSong.trim()}
                                      onClick={() => void adaptMusicCueWithLlm(cue.id)}>
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
                                    return (
                                      <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                                        <button type="button" className="w-full flex items-center justify-between gap-2 text-left text-[10px]"
                                          onClick={() => patchMusicCue(cue.id, { selectedCandidateId: candidate.id })}>
                                          <span className="text-text-primary">{getOutputReference({ name: candidate.name, type: 'audio' })} · {candidate.model}</span>
                                          <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : 'duration on playback'}</span>
                                        </button>
                                        <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                                        <button className={`${button} w-full`} disabled={Boolean(musicCueBusy || musicQueue)}
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
                      <Field label="Final MiniMax prompt · English · max 300 characters" value={project.music.style}
                        onChange={style => patch({ music: { ...project.music, style } })} rows={3} />
                      <Field label="Editable lyrics" value={project.music.lyrics}
                        onChange={lyrics => patch({ music: { ...project.music, lyrics } })} rows={8} />
                      <label className="block text-[10px] text-text-muted">Approx. duration · seconds
                        <input className={`${input} mt-1`} type="number" min={20} max={360} step={5}
                          value={project.music.targetDurationSeconds}
                          onChange={event => patch({ music: { ...project.music, targetDurationSeconds: Math.max(20, Math.min(360, Number(event.target.value) || 90)) } })} />
                      </label>
                      <button className={`${button} w-full border-pink-500/60 text-pink-300`}
                        disabled={productionBusy === 'music' || !servicesConfig?.minimax_api_key_set}
                        onClick={() => void generateMinimaxSongs()}><Music size={13} /> Generate manual candidates</button>
                      {project.music.candidates.map(candidate => (
                        <div key={candidate.id} className="rounded border border-border p-2 space-y-1.5">
                          <span className="text-[10px] text-text-primary">{getOutputReference({ name: candidate.name, type: 'audio' })} · {candidate.model}</span>
                          <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                          <button className={`${button} w-full`} onClick={() => void openMusicalTrailer(candidate.id)}><Film size={12} /> Use in musical trailer</button>
                        </div>
                      ))}
                      <button className={`${button} w-full`} onClick={() => void openMusicalTrailer()}>
                        <ChevronRight size={13} /> Open Musical Video Director
                      </button>
                    </div>
                  </div>
                </details>
              </>
            )}

            {tab === 'productions' && (
              <>
                <div className="mb-4">
                  <h2 className="text-lg font-semibold text-text-primary">Productions</h2>
                  <p className="text-xs text-text-muted mt-1">Adapt the same approved material without destroying the source story.</p>
                </div>
                <div className="grid md:grid-cols-2 gap-4">
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
                    <button className={`${button} w-full border-accent-blue text-accent-blue`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(true)}><Sparkles size={13} /> Generate complete comic chapter</button>
                    <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length)} onClick={() => stageComic(false)}><ChevronRight size={13} /> Open in Comic Director</button>
                    <p className="text-[9px] text-text-muted">Complete generation creates the plan and artwork and may consume provider credits. Director mode lets you review every field first.</p>
                  </div>
                  <div className={`${panel} space-y-3`}>
                    <Film size={26} className="text-purple-400" />
                    <h3 className="font-semibold text-text-primary">Film adaptation</h3>
                    <p className="text-xs text-text-muted">Creates a short narrative episode instead of compressing the whole story. The cast, world and visual references remain attached.</p>
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
                    <label className="block text-[10px] text-text-muted">Image model
                      <select
                        className={`${input} mt-1`}
                        value={filmImageModel}
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
                        {filmImageModel === MINIMAX_IMAGE_API_MODEL
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
                        onChange={event => void selectDirectorVideoModel(event.target.value)}
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
                        {filmVideoModel === 'minimax_h3'
                          ? 'MiniMax H3 renders every planned shot locally at up to 768p with native stereo audio. Longer shots are continued and assembled automatically.'
                          : 'LTX uses Maestro’s established multi-shot Director pipeline.'}
                      </span>
                    </label>
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
                    <button className={`${button} w-full border-purple-500/60 text-purple-300`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy) || !filmImageReady} onClick={() => stageFilm(true)}>{productionBusy === 'film' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate complete short film</button>
                    <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy)} onClick={() => stageFilm(false)}><ChevronRight size={13} /> Open in Short Film Director</button>
                    <p className="text-[9px] text-text-muted">Complete generation launches a recoverable Director pipeline and may consume image/video credits.</p>
                  </div>
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
                        <div className="grid gap-2 sm:grid-cols-2">
                          <button
                            className={`${button} w-full border-pink-500/60 text-pink-300`}
                            disabled={Boolean(productionBusy) || Boolean(productionIssues.length)}
                            onClick={() => void stageMusicVideo(true)}
                          >
                            {productionBusy === 'music' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                            Generate {musicProductionMode === 'trailer' ? 'musical trailer' : 'complete music video'}
                          </button>
                          <button
                            className={`${button} w-full`}
                            disabled={Boolean(productionBusy) || Boolean(productionIssues.length)}
                            onClick={() => void stageMusicVideo(false)}
                          >
                            <ChevronRight size={13} /> Open {musicProductionMode === 'trailer' ? 'trailer' : 'music video'} in Director
                          </button>
                        </div>
                        <p className="text-[9px] text-text-muted">
                          The selected song, structured lyrics, focus character/world, approved images and pacing are saved in Adaptation history and can be reopened independently.
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
                    <button className={`${button} w-full border-pink-500/60 text-pink-300`}
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
                          const reference = getOutputReference({ name: candidate.name, type: 'audio' })
                          const selected = project.music.selectedCandidateId === candidate.id
                          return (
                            <div key={candidate.id} className={`rounded border p-2 space-y-1.5 ${selected ? 'border-pink-400 bg-pink-500/5' : 'border-border'}`}>
                              <button type="button" onClick={() => patch({ music: { ...project.music, selectedCandidateId: candidate.id } })}
                                className="w-full flex items-center justify-between text-[10px] text-left">
                                <span className="text-text-primary">{reference} · {candidate.model}</span>
                                <span className="text-text-muted">{candidate.durationSeconds ? `${candidate.durationSeconds.toFixed(1)}s` : 'duration on playback'}</span>
                              </button>
                              <audio src={candidate.source} controls preload="metadata" className="w-full h-8" />
                              <button className={`${button} w-full ${selected ? 'border-pink-500/50 text-pink-300' : ''}`}
                                onClick={() => void openMusicalTrailer(candidate.id)} disabled={productionBusy === 'music'}>
                                <Film size={12} /> Use this song in musical trailer
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    )}
                    <button className={`${button} w-full`} onClick={() => void openMusicalTrailer()} disabled={productionBusy === 'music'}>
                      <ChevronRight size={13} /> Open Musical Video Director
                    </button>
                    <p className="text-[9px] text-text-muted">Uploaded songs work too. Beat-aware cuts synchronize editing rhythm; generated motion itself is not guaranteed to hit every beat semantically.</p>
                  </div>
                </div>
                {productionIssues.length > 0 && (
                  <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
                    Guided production is locked until review is complete: {productionIssues.join(' · ')}.
                  </div>
                )}
                <div className={`${panel} mt-4`}>
                  <h3 className="text-sm font-semibold text-text-primary mb-3">Adaptation history</h3>
                  {project.productions.length ? project.productions.map(item => (
                    <div key={item.id} className="flex flex-col lg:flex-row lg:items-center justify-between gap-2 border-b border-border last:border-0 py-2 text-xs">
                      <div>
                        <span className="text-text-primary capitalize">
                          {item.kind === 'music_video' ? 'Music video' : item.kind} · {item.targetName || item.title}
                        </span>
                        <span className="text-text-muted ml-2">
                          source v{item.sourceVersion} · {new Date(item.createdAt).toLocaleString()}
                        </span>
                        {item.sourceSnapshot?.sectionVersions
                          && JSON.stringify(item.sourceSnapshot.sectionVersions) !== JSON.stringify(project.sectionVersions) && (
                          <span className="ml-2 text-amber-300">source changed since staging</span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button className={button} onClick={() => reopenProduction(item.id)}>Reopen target</button>
                        {item.sourceSnapshot && (
                          <button className={button} onClick={() => restoreProductionSource(item.id)}>Restore source as copy</button>
                        )}
                      </div>
                    </div>
                  )) : <p className="text-xs text-text-muted">No adaptation has been staged yet.</p>}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      <input ref={uploadRef} type="file" accept="image/*" multiple className="hidden" onChange={event => uploadVisual(event.target.files)} />
      <input ref={lyriaUploadRef} type="file" accept="audio/*" className="hidden"
        onChange={event => void uploadLyriaResult(event.target.files?.[0])} />
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
    <div className={`${panel} space-y-3`}>
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
