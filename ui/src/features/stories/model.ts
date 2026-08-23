import type {
  StoryBeat, StoryCharacter, StoryLocation, StoryProject, StoryRelationship,
  StoryMusicCandidate, StoryMusicCue, StoryVisualAsset,
} from './types'
import {
  DEFAULT_DIRECT_VIDEO_MASTER_PROMPT,
  LEGACY_HEAVY_METAL_DIRECT_VIDEO_MASTER_PROMPT,
} from '../../types/index.ts'
import { normalizeStoryMusicModel } from './musicModel'

export type StorySection = 'overview' | 'world' | 'characters' | 'relationships' | 'structure'

const STYLE_LOCK_PREFIX = 'VISUAL STYLE LOCK (mandatory, highest priority):'
const STYLE_LOCK_SUFFIX = 'END VISUAL STYLE LOCK.'
const STYLE_LOCK_PATTERN = new RegExp(
  `^${STYLE_LOCK_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?${STYLE_LOCK_SUFFIX.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*`,
  'i',
)

const STYLE_FAMILIES = [
  ['anime', 'manga'],
  ['comic book', 'comic-book', 'comics', 'comic', 'tebeo', 'graphic novel', 'novela grafica'],
  ['photoreal', 'photographic', 'live action', 'fotoreal', 'fotografico', 'accion real'],
  ['watercolor', 'watercolour', 'acuarela'],
  ['oil painting', 'oil-painted', 'oleo'],
  ['pixel art', 'pixel-art'],
  ['vector art', 'vectorial'],
  ['cel shading', 'cel-shaded', 'cel shaded'],
  ['3d render', '3d-rendered', 'cgi'],
  ['stop motion', 'stop-motion', 'claymation'],
] as const

export function directVideoMasterPromptFromVisualStyles(
  visualStyle: string,
  characterVisualStyle: string,
): string {
  const globalStyle = visualStyle.trim()
  const characterStyle = characterVisualStyle.trim()
  if (!globalStyle && !characterStyle) return ''
  return [
    globalStyle ? `GLOBAL VISUAL STYLE (mandatory in every clip): ${globalStyle}` : '',
    characterStyle
      ? `CHARACTER VISUAL STYLE (mandatory for every visible character): ${characterStyle}`
      : '',
    DEFAULT_DIRECT_VIDEO_MASTER_PROMPT,
  ].filter(Boolean).join('\n\n')
}

const normalizeStyleText = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLocaleLowerCase()

function containsAffirmedStyleTerm(style: string, term: string): boolean {
  let index = style.indexOf(term)
  while (index >= 0) {
    const prefix = style.slice(Math.max(0, index - 36), index)
    const negated = /(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|\bzero\b|\bavoid\b|\bexclude\b|\bevitar\b|\bsin\b|\bnunca\b)[^,.;:]{0,28}$/u.test(prefix)
    if (!negated) return true
    index = style.indexOf(term, index + term.length)
  }
  return false
}

/**
 * Keep continuity exclusions while dropping legacy medium/style bans that
 * directly contradict the currently enforced global style. The stored Story
 * data is left untouched, so disabling the lock restores its original rules.
 */
export function storyNegativePromptForStyle(
  negativePrompt: string,
  visualStyle: string,
  enforce = true,
): string {
  const negative = negativePrompt.trim()
  const style = normalizeStyleText(visualStyle.trim())
  if (!enforce || !negative || !style) return negative
  const desiredFamilies = STYLE_FAMILIES.filter(family =>
    family.some(term => containsAffirmedStyleTerm(style, term)))
  if (!desiredFamilies.length) return negative
  return negative
    .split(/(?:[;\n]+|(?<=[.!?])\s+)/u)
    .map(clause => clause.trim())
    .filter(Boolean)
    .filter(clause => {
      const normalizedClause = normalizeStyleText(clause)
      return !desiredFamilies.some(family =>
        family.some(term => normalizedClause.includes(term)))
    })
    .join('; ')
}

/** Remove a previously materialized Story style lock without changing prompt content. */
export function stripStoryVisualStyle(prompt: string): string {
  return prompt.trim().replace(STYLE_LOCK_PATTERN, '').trim()
}

/** Compose a replaceable, provider-neutral style lock ahead of semantic prompt content. */
export function applyStoryVisualStyle(
  prompt: string,
  visualStyle: string,
  enforce = true,
): string {
  const content = stripStoryVisualStyle(prompt)
  const style = visualStyle.trim()
  if (!enforce || !style) return content
  return `${STYLE_LOCK_PREFIX} ${style} ${STYLE_LOCK_SUFFIX}${content ? ` ${content}` : ''}`
}

/** Keep character rendering separate in the editor while enforcing it with the global lock. */
export function storyRenderStyle(project: Pick<StoryProject, 'visualStyle' | 'characterVisualStyle'>): string {
  const globalStyle = project.visualStyle.trim()
  const characterStyle = project.characterVisualStyle.trim()
  return [
    globalStyle,
    characterStyle
      ? `CHARACTER RENDERING STYLE: ${characterStyle}. Every visible person or character must use this exact rendering, material and design language consistently.`
      : '',
  ].filter(Boolean).join(' ')
}

/** Fast local preflight for prompts that are likely to collapse every clip into one scene. */
export function analyzeStoryPromptHealth(project: StoryProject): string[] {
  const warnings: string[] = []
  const style = `${project.visualStyle} ${project.characterVisualStyle} ${project.directVideoMasterPrompt}`.toLocaleLowerCase()
  const sceneTerms = [
    'cafetería', 'cafe', 'café', 'ordenador', 'computer', 'laptop', 'office', 'oficina',
    'bedroom', 'dormitorio', 'kitchen', 'cocina', 'sitting', 'sentado', 'typing', 'tecleando',
  ].filter(term => style.includes(term))
  if (sceneTerms.length >= 2) {
    warnings.push(`El estilo/prompt maestro contiene escena o acción (${sceneTerms.slice(0, 4).join(', ')}). Muévela al argumento o a un plano concreto para que no se repita en todos los clips.`)
  }
  if (project.directVideoMasterPromptMode === 'custom' && project.directVideoMasterPrompt.length > 1200) {
    warnings.push('El prompt maestro personalizado es muy largo; deja aquí sólo medio visual, paleta, iluminación y reglas de diseño.')
  }
  const beatTexts = project.beats.map(beat => `${beat.summary} ${beat.conflict} ${beat.turn}`.toLocaleLowerCase())
  const repeated = ['cafetería', 'cafe', 'café', 'ordenador', 'computer', 'laptop', 'pantalla', 'screen']
    .filter(term => beatTexts.length >= 3 && beatTexts.filter(textValue => textValue.includes(term)).length / beatTexts.length >= 0.6)
  if (repeated.length) {
    warnings.push(`La mayoría de momentos repite ${repeated.join(', ')}. Reserva ese motivo para uno o dos bloques y añade localizaciones/acciones de contraste.`)
  }
  if (project.locationVariety === 'balanced' && project.projectType === 'music_video' && project.creativeBrief.setting.trim() && !project.world.locations.length) {
    warnings.push('Sólo hay una localización concreta. Con “variedad equilibrada”, añade al menos dos entornos de contraste o deja el lugar como referencia no obligatoria.')
  }
  return warnings
}

export function storyId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function normalizeMusicCandidate(value: unknown, now: string): StoryMusicCandidate | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<StoryMusicCandidate>
  if (!text(candidate.source)) return null
  return {
    id: text(candidate.id) || storyId('song'),
    displayName: text(candidate.displayName) || undefined,
    title: text(candidate.title) || undefined,
    language: text(candidate.language) || undefined,
    version: Number(candidate.version) > 0 ? Math.max(1, Number(candidate.version)) : undefined,
    name: text(candidate.name, 'Story song'),
    source: text(candidate.source),
    prompt: text(candidate.prompt),
    lyrics: text(candidate.lyrics),
    provider: candidate.provider === 'local' ? 'local'
      : candidate.provider === 'lyria' ? 'lyria' : 'minimax',
    model: text(candidate.model),
    durationSeconds: Math.max(0, Number(candidate.durationSeconds) || 0),
    createdAt: text(candidate.createdAt, now),
    taskId: text(candidate.taskId) || undefined,
    rootTaskId: text(candidate.rootTaskId) || undefined,
  }
}

function normalizeMusicCue(value: unknown, index: number, now: string): StoryMusicCue | null {
  if (!value || typeof value !== 'object') return null
  const cue = value as Partial<StoryMusicCue>
  const kind = cue.kind === 'world' || cue.kind === 'character' ? cue.kind : 'story'
  const id = text(cue.id) || storyId(`music-${kind}`)
  return {
    id,
    kind,
    targetId: text(cue.targetId, kind === 'world' ? 'world' : `story-${index + 1}`),
    title: text(cue.title, `Music cue ${index + 1}`),
    purpose: text(cue.purpose),
    referenceSong: text(cue.referenceSong),
    brief: text(cue.brief),
    style: text(cue.style),
    lyrics: text(cue.lyrics),
    lyricsLanguage: text(cue.lyricsLanguage) || undefined,
    lyriaPrompt: text(cue.lyriaPrompt),
    instrumental: cue.instrumental === true,
    durationSeconds: Math.max(20, Math.min(360, Number(cue.durationSeconds) || 90)),
    candidates: Array.isArray(cue.candidates)
      ? cue.candidates.flatMap(candidate => normalizeMusicCandidate(candidate, now) || []) : [],
    selectedCandidateId: text(cue.selectedCandidateId) || undefined,
  }
}

const text = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback
const textArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
const idArray = (value: unknown): string[] => Array.from(new Set(textArray(value)))
const uniqueIds = <T extends { id: string }>(items: T[], prefix: string): T[] => {
  const seen = new Set<string>()
  return items.map((item, index) => {
    let id = item.id.trim() || `${prefix}-${index + 1}`
    if (seen.has(id)) id = `${id}-${index + 1}`
    while (seen.has(id)) id = `${id}-copy`
    seen.add(id)
    return id === item.id ? item : { ...item, id }
  })
}

function normalizeLocation(value: unknown, index: number): StoryLocation {
  const item = value && typeof value === 'object' ? value as Partial<StoryLocation> : {}
  return {
    id: text(item.id) || `location-${index + 1}`,
    name: text(item.name, `Location ${index + 1}`),
    purpose: text(item.purpose),
    description: text(item.description),
    visualPrompt: text(item.visualPrompt),
    negativePrompt: text(item.negativePrompt),
    referenceAssetIds: idArray(item.referenceAssetIds),
  }
}

export function normalizeStoryCharacter(value: unknown, index: number): StoryCharacter {
  const item = value && typeof value === 'object' ? value as Partial<StoryCharacter> : {}
  return {
    id: text(item.id).trim() || `character-${index + 1}`,
    name: text(item.name, `Character ${index + 1}`),
    role: text(item.role),
    age: text(item.age),
    pronouns: text(item.pronouns),
    personality: text(item.personality),
    desire: text(item.desire),
    need: text(item.need),
    flaw: text(item.flaw),
    conflict: text(item.conflict),
    arc: text(item.arc),
    voice: text(item.voice),
    appearance: text(item.appearance),
    wardrobe: text(item.wardrobe),
    visualPrompt: text(item.visualPrompt),
    negativePrompt: text(item.negativePrompt),
    referenceAssetIds: idArray(item.referenceAssetIds),
    primaryReferenceAssetId: text(item.primaryReferenceAssetId) || undefined,
    approval: item.approval === 'approved' ? 'approved' : 'draft',
  }
}

function normalizeRelationship(value: unknown, index: number): StoryRelationship {
  const item = value && typeof value === 'object' ? value as Partial<StoryRelationship> : {}
  return {
    id: text(item.id).trim() || `relationship-${index + 1}`,
    fromCharacterId: text(item.fromCharacterId).trim(),
    toCharacterId: text(item.toCharacterId).trim(),
    label: text(item.label),
    dynamic: text(item.dynamic),
    evolution: text(item.evolution),
  }
}

function normalizeBeat(value: unknown, index: number): StoryBeat {
  const item = value && typeof value === 'object' ? value as Partial<StoryBeat> : {}
  return {
    id: text(item.id) || `beat-${index + 1}`,
    stage: text(item.stage, `Beat ${index + 1}`),
    title: text(item.title),
    summary: text(item.summary),
    goal: text(item.goal),
    conflict: text(item.conflict),
    turn: text(item.turn),
  }
}

function normalizeAsset(value: unknown, id: string): StoryVisualAsset | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Partial<StoryVisualAsset>
  const source = text(item.source)
  if (!source) return null
  const provider = item.provider === 'minimax' || item.provider === 'upload'
    ? item.provider : 'maestro'
  return {
    id: text(item.id, id),
    name: text(item.name, id),
    source,
    prompt: text(item.prompt),
    negativePrompt: text(item.negativePrompt),
    provider,
    model: text(item.model) || undefined,
    createdAt: text(item.createdAt, new Date().toISOString()),
    assetKind: ['world', 'location', 'character', 'prop', 'style', 'ignore'].includes(text(item.assetKind))
      ? item.assetKind : undefined,
    description: text(item.description) || undefined,
    confidence: Number.isFinite(Number(item.confidence))
      ? Math.max(0, Math.min(1, Number(item.confidence))) : undefined,
    originalName: text(item.originalName) || undefined,
    importBatchId: text(item.importBatchId) || undefined,
    // Existing Story projects predate per-image approval and were already
    // used in productions. Preserve that behavior; newly imported/generated
    // assets are created explicitly as drafts in StoryLabPanel.
    approval: item.approval === 'draft' ? 'draft' : 'approved',
    variantKind: item.variantKind === 'styled' ? 'styled' : 'original',
    derivedFromAssetId: text(item.derivedFromAssetId) || undefined,
    stylePrompt: text(item.stylePrompt) || undefined,
  }
}

export function createStoryProject(projectType: StoryProject['projectType'] = 'full_story'): StoryProject {
  const now = new Date().toISOString()
  return {
    version: 1,
    id: storyId('story'),
    revision: 1,
    sectionVersions: {
      overview: 1, world: 1, characters: 1, relationships: 1, structure: 1,
    },
    title: 'Untitled story',
    projectType,
    creativeBrief: {
      generalIdea: '',
      context: '',
      performer: '',
      musicStyle: '',
      songStory: '',
      subjects: '',
      setting: '',
      action: '',
      quickFormat: 'dialogue',
      durationSeconds: projectType === 'quick_video' ? 15 : projectType === 'trailer' ? 60 : 90,
    },
    language: 'Español',
    spokenLanguage: 'Español de España',
    locationVariety: 'balanced',
    protagonistConsistency: false,
    protagonistCharacterId: '',
    genre: 'Adventure',
    tone: 'Cinematic',
    audience: 'General',
    visualStyle: '',
    characterVisualStyle: '',
    enforceVisualStyle: true,
    allowClipText: false,
    musicVideoGenerationMode: 'image_guided',
    directVideoMasterPromptMode: 'inherit',
    directVideoMasterPrompt: '',
    premise: '',
    logline: '',
    synopsis: '',
    theme: '',
    ending: '',
    workflowMode: 'guided',
    provider: {
      useGlobalProfile: true,
      writingProvider: 'maestro',
      writingModel: 'deepseek-v4-pro',
      writingBaseUrl: 'https://api.deepseek.com',
      imageProvider: 'maestro',
      imageModel: 'flux2_klein_9b',
    },
    videoOverride: {
      model: 'minimax_h3_legacy',
      resolution: '540p',
      aspectRatio: '16:9',
    },
    world: {
      summary: '', period: '', geography: '', society: '', technology: '',
      rules: [], visualLanguage: '', visualPrompt: '', negativePrompt: '',
      locations: [], referenceAssetIds: [],
    },
    characters: [],
    relationships: [],
    beats: [],
    assets: {},
    visualJobs: {},
    music: {
      mode: 'original',
      model: 'ace_step_v1_5_xl_sft_lm_4b',
      brief: '',
      style: '',
      sourceLyrics: '',
      lyrics: '',
      targetDurationSeconds: 90,
      candidateCount: 2,
      cues: [],
      candidates: [],
    },
    productions: [],
    approvals: {},
    createdAt: now,
    updatedAt: now,
  }
}

export function normalizeStoryProject(value: unknown): StoryProject {
  const fallback = createStoryProject()
  if (!value || typeof value !== 'object') return fallback
  const project = value as Partial<StoryProject>
  const creativeBrief = project.creativeBrief && typeof project.creativeBrief === 'object'
    ? project.creativeBrief : fallback.creativeBrief
  const world: Partial<StoryProject['world']> =
    project.world && typeof project.world === 'object' ? project.world : {}
  const assets: Record<string, StoryVisualAsset> = {}
  if (project.assets && typeof project.assets === 'object') {
    Object.entries(project.assets).forEach(([id, asset]) => {
      const normalized = normalizeAsset(asset, id)
      if (normalized) assets[normalized.id] = normalized
    })
  }
  const characters = uniqueIds(
    Array.isArray(project.characters) ? project.characters.map(normalizeStoryCharacter) : [],
    'character',
  )
  const validCharacterIds = new Set(characters.map(character => character.id))
  const relationships = uniqueIds(
    Array.isArray(project.relationships) ? project.relationships.map(normalizeRelationship) : [],
    'relationship',
  ).filter(item =>
      validCharacterIds.has(item.fromCharacterId)
      && validCharacterIds.has(item.toCharacterId)
      && item.fromCharacterId !== item.toCharacterId)
  const rawVersions: Partial<StoryProject['sectionVersions']> = project.sectionVersions || {}
  const sectionVersions = {
    overview: Math.max(1, Number(rawVersions.overview) || 1),
    world: Math.max(1, Number(rawVersions.world) || 1),
    characters: Math.max(1, Number(rawVersions.characters) || 1),
    relationships: Math.max(1, Number(rawVersions.relationships) || 1),
    structure: Math.max(1, Number(rawVersions.structure) || 1),
  }
  const approvals = project.approvals && typeof project.approvals === 'object'
    ? Object.fromEntries(Object.entries(project.approvals).flatMap(([key, approval]) => {
      if (!['overview', 'world', 'characters', 'relationships', 'structure'].includes(key)) return []
      if (!approval || typeof approval !== 'object') return []
      const value = approval as { approvedAt?: unknown; version?: unknown }
      const approvedAt = text(value.approvedAt)
      const version = Number(value.version)
      return approvedAt && Number.isFinite(version)
        ? [[key, { approvedAt, version }]]
        : []
    }))
    : {}
  const now = new Date().toISOString()
  const visualStyle = text(project.visualStyle)
  const characterVisualStyle = text(project.characterVisualStyle)
  const rawDirectVideoMasterPrompt = text(project.directVideoMasterPrompt)
  const directVideoMasterPromptMode = project.directVideoMasterPromptMode === 'custom'
    ? 'custom'
    : project.directVideoMasterPromptMode === 'inherit'
      ? 'inherit'
      : rawDirectVideoMasterPrompt
        && rawDirectVideoMasterPrompt !== DEFAULT_DIRECT_VIDEO_MASTER_PROMPT
        && rawDirectVideoMasterPrompt !== LEGACY_HEAVY_METAL_DIRECT_VIDEO_MASTER_PROMPT
        ? 'custom'
        : 'inherit'
  const rawVideoOverride = project.videoOverride && typeof project.videoOverride === 'object'
    ? project.videoOverride
    : null
  const videoOverrideModel = text(rawVideoOverride?.model)
  const videoOverride = rawVideoOverride
    ? {
        model: videoOverrideModel,
        resolution: ['auto', '480p', '540p', '720p', '768p', '1080p']
          .includes(text(rawVideoOverride.resolution))
          ? rawVideoOverride.resolution
          : videoOverrideModel ? fallback.videoOverride.resolution : 'auto',
        aspectRatio: ['auto', '16:9', '9:16']
          .includes(text(rawVideoOverride.aspectRatio))
          ? rawVideoOverride.aspectRatio
          : videoOverrideModel ? fallback.videoOverride.aspectRatio : 'auto',
      } as StoryProject['videoOverride']
    : {
        // Projects saved before videoOverride used the shared Director/Studio
        // selection. Keep a sentinel so StoryLabPanel can capture that exact
        // old value once after model hydration instead of silently changing it.
        model: '',
        resolution: 'auto',
        aspectRatio: 'auto',
      } as StoryProject['videoOverride']
  return {
    ...fallback,
    version: 1,
    id: text(project.id) || fallback.id,
    revision: Math.max(1, Number(project.revision) || 1),
    sectionVersions,
    title: text(project.title, fallback.title),
    projectType: project.projectType === 'music_video'
      ? 'music_video'
      : project.projectType === 'trailer'
        ? 'trailer'
        : project.projectType === 'quick_video' ? 'quick_video' : 'full_story',
    creativeBrief: {
      generalIdea: text(creativeBrief.generalIdea),
      context: text(creativeBrief.context),
      performer: text(creativeBrief.performer),
      musicStyle: text(creativeBrief.musicStyle),
      songStory: text(creativeBrief.songStory),
      subjects: text(creativeBrief.subjects),
      setting: text(creativeBrief.setting),
      action: text(creativeBrief.action),
      quickFormat: ['dialogue', 'meme', 'parody', 'sketch', 'viral', 'announcement']
        .includes(text(creativeBrief.quickFormat))
        ? creativeBrief.quickFormat : 'dialogue',
      durationSeconds: Math.max(5, Math.min(360,
        Number(creativeBrief.durationSeconds)
        || (project.projectType === 'quick_video' ? 15 : project.projectType === 'trailer' ? 60 : 90))),
    },
    language: text(project.language, fallback.language),
    spokenLanguage: text(project.spokenLanguage, text(project.language, fallback.spokenLanguage)),
    locationVariety: project.locationVariety === 'single_location' ? 'single_location' : 'balanced',
    protagonistConsistency: project.protagonistConsistency === true,
    protagonistCharacterId: (Array.isArray(project.characters) ? project.characters : [])
      .some((character: StoryCharacter) => character.id === text(project.protagonistCharacterId))
      ? text(project.protagonistCharacterId) : '',
    genre: text(project.genre, fallback.genre),
    tone: text(project.tone, fallback.tone),
    audience: text(project.audience, fallback.audience),
    visualStyle,
    characterVisualStyle,
    enforceVisualStyle: project.enforceVisualStyle !== false,
    allowClipText: project.allowClipText === true,
    musicVideoGenerationMode: project.musicVideoGenerationMode === 'direct_video'
      ? 'direct_video'
      : project.musicVideoGenerationMode === 'direct_references'
        ? 'direct_references'
        : 'image_guided',
    directVideoMasterPromptMode,
    directVideoMasterPrompt: directVideoMasterPromptMode === 'inherit'
      ? directVideoMasterPromptFromVisualStyles(visualStyle, characterVisualStyle)
      : rawDirectVideoMasterPrompt,
    premise: text(project.premise),
    logline: text(project.logline),
    synopsis: text(project.synopsis),
    theme: text(project.theme),
    ending: text(project.ending),
    workflowMode: project.workflowMode === 'automatic' ? 'automatic' : 'guided',
    provider: {
      ...fallback.provider,
      ...(project.provider && typeof project.provider === 'object' ? project.provider : {}),
      useGlobalProfile: project.provider && typeof project.provider === 'object'
        ? project.provider.useGlobalProfile === true
        : false,
      writingProvider: ['maestro', 'deepseek', 'minimax', 'openai', 'openai-compatible']
        .includes(text(project.provider?.writingProvider))
        ? project.provider!.writingProvider
        : 'maestro',
      writingModel: text(project.provider?.writingModel, fallback.provider.writingModel),
      writingBaseUrl: text(project.provider?.writingBaseUrl, fallback.provider.writingBaseUrl),
      imageProvider: project.provider?.imageProvider === 'minimax' ? 'minimax' : 'maestro',
      imageModel: text(project.provider?.imageModel, fallback.provider.imageModel),
    },
    videoOverride,
    world: {
      summary: text(world.summary),
      period: text(world.period),
      geography: text(world.geography),
      society: text(world.society),
      technology: text(world.technology),
      rules: textArray(world.rules),
      visualLanguage: text(world.visualLanguage),
      visualPrompt: text(world.visualPrompt),
      negativePrompt: text(world.negativePrompt),
      locations: uniqueIds(
        Array.isArray(world.locations) ? world.locations.map(normalizeLocation) : [],
        'location',
      ),
      referenceAssetIds: idArray(world.referenceAssetIds).filter(id => Boolean(assets[id])),
    },
    characters: characters.map(character => {
      const referenceAssetIds = character.referenceAssetIds.filter(id => Boolean(assets[id]))
      return {
        ...character,
        referenceAssetIds,
        primaryReferenceAssetId: referenceAssetIds.includes(character.primaryReferenceAssetId || '')
          ? character.primaryReferenceAssetId : referenceAssetIds[0],
      }
    }),
    relationships,
    beats: uniqueIds(
      Array.isArray(project.beats) ? project.beats.map(normalizeBeat) : [],
      'beat',
    ),
    assets,
    visualJobs: project.visualJobs && typeof project.visualJobs === 'object'
      ? Object.fromEntries(Object.entries(project.visualJobs).flatMap(([key, value]) =>
        typeof value === 'string' && value.trim() ? [[key, value]] : []))
      : {},
    music: {
      mode: project.music?.mode === 'cover' ? 'cover' : 'original',
      model: normalizeStoryMusicModel(project.music?.model),
      brief: text(project.music?.brief),
      style: text(project.music?.style),
      sourceLyrics: text(project.music?.sourceLyrics),
      lyrics: text(project.music?.lyrics),
      lyricsLanguage: text(project.music?.lyricsLanguage) || undefined,
      coverReferenceFilename: text(project.music?.coverReferenceFilename) || undefined,
      coverReferenceName: text(project.music?.coverReferenceName) || undefined,
      targetDurationSeconds: Math.max(20, Math.min(360, Number(project.music?.targetDurationSeconds) || 90)),
      candidateCount: project.music?.candidateCount === 3 ? 3 : 2,
      cues: Array.isArray(project.music?.cues)
        ? project.music.cues.flatMap((cue, index) => normalizeMusicCue(cue, index, now) || []) : [],
      candidates: Array.isArray(project.music?.candidates)
        ? project.music.candidates.flatMap(candidate => normalizeMusicCandidate(candidate, now) || [])
        : [],
      selectedCandidateId: text(project.music?.selectedCandidateId) || undefined,
    },
    productions: Array.isArray(project.productions)
      ? project.productions.filter(item => item && typeof item === 'object').map(item => ({
        id: text(item.id) || storyId('production'),
        kind: item.kind === 'music_video'
          ? 'music_video' : item.kind === 'trailer' ? 'trailer' : item.kind === 'film' ? 'film' : 'comic',
        title: text(item.title, project.title || fallback.title),
        createdAt: text(item.createdAt, now),
        sourceVersion: Math.max(1, Number(item.sourceVersion) || 1),
        sourceSnapshot: item.sourceSnapshot && typeof item.sourceSnapshot === 'object'
          ? item.sourceSnapshot : undefined,
        targetId: text(item.targetId) || undefined,
        targetName: text(item.targetName) || undefined,
        targetSnapshot: item.targetSnapshot && typeof item.targetSnapshot === 'object'
          ? item.targetSnapshot : undefined,
        status: item.status === 'draft' ? 'draft' : 'staged',
      }))
      : [],
    approvals,
    createdAt: text(project.createdAt, now),
    updatedAt: text(project.updatedAt, now),
  }
}

export function changedSections(before: StoryProject, after: StoryProject): StorySection[] {
  const overviewBefore = [
    before.title, before.projectType, before.creativeBrief, before.language, before.spokenLanguage, before.locationVariety, before.protagonistConsistency, before.protagonistCharacterId, before.genre, before.tone, before.audience,
    before.visualStyle, before.characterVisualStyle, before.enforceVisualStyle, before.allowClipText,
    before.musicVideoGenerationMode, before.directVideoMasterPromptMode, before.directVideoMasterPrompt,
    before.premise, before.logline, before.synopsis, before.theme, before.ending,
  ]
  const overviewAfter = [
    after.title, after.projectType, after.creativeBrief, after.language, after.spokenLanguage, after.locationVariety, after.protagonistConsistency, after.protagonistCharacterId, after.genre, after.tone, after.audience,
    after.visualStyle, after.characterVisualStyle, after.enforceVisualStyle, after.allowClipText,
    after.musicVideoGenerationMode, after.directVideoMasterPromptMode, after.directVideoMasterPrompt,
    after.premise, after.logline, after.synopsis, after.theme, after.ending,
  ]
  const changed: StorySection[] = []
  if (JSON.stringify(overviewBefore) !== JSON.stringify(overviewAfter)) changed.push('overview')
  if (JSON.stringify(before.world) !== JSON.stringify(after.world)) changed.push('world')
  if (JSON.stringify(before.characters) !== JSON.stringify(after.characters)) changed.push('characters')
  if (JSON.stringify(before.relationships) !== JSON.stringify(after.relationships)) changed.push('relationships')
  if (JSON.stringify(before.beats) !== JSON.stringify(after.beats)) changed.push('structure')
  return changed
}
