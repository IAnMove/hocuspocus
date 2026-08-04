import type {
  StoryBeat, StoryCharacter, StoryLocation, StoryProject, StoryRelationship,
  StoryVisualAsset,
} from './types'

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

export function storyId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
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
  }
}

export function createStoryProject(): StoryProject {
  const now = new Date().toISOString()
  return {
    version: 1,
    id: storyId('story'),
    revision: 1,
    sectionVersions: {
      overview: 1, world: 1, characters: 1, relationships: 1, structure: 1,
    },
    title: 'Untitled story',
    language: 'Español',
    genre: 'Adventure',
    tone: 'Cinematic',
    audience: 'General',
    visualStyle: '',
    enforceVisualStyle: true,
    premise: '',
    logline: '',
    synopsis: '',
    theme: '',
    ending: '',
    workflowMode: 'guided',
    provider: {
      writingProvider: 'maestro',
      writingModel: 'deepseek-v4-pro',
      writingBaseUrl: 'https://api.deepseek.com',
      imageProvider: 'maestro',
      imageModel: 'flux2_klein_9b',
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
      model: 'music-3.0',
      brief: '',
      style: '',
      sourceLyrics: '',
      lyrics: '',
      targetDurationSeconds: 90,
      candidateCount: 2,
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
  return {
    ...fallback,
    version: 1,
    id: text(project.id) || fallback.id,
    revision: Math.max(1, Number(project.revision) || 1),
    sectionVersions,
    title: text(project.title, fallback.title),
    language: text(project.language, fallback.language),
    genre: text(project.genre, fallback.genre),
    tone: text(project.tone, fallback.tone),
    audience: text(project.audience, fallback.audience),
    visualStyle: text(project.visualStyle),
    enforceVisualStyle: project.enforceVisualStyle !== false,
    premise: text(project.premise),
    logline: text(project.logline),
    synopsis: text(project.synopsis),
    theme: text(project.theme),
    ending: text(project.ending),
    workflowMode: project.workflowMode === 'automatic' ? 'automatic' : 'guided',
    provider: {
      ...fallback.provider,
      ...(project.provider && typeof project.provider === 'object' ? project.provider : {}),
      writingProvider: ['maestro', 'deepseek', 'minimax', 'openai', 'openai-compatible']
        .includes(text(project.provider?.writingProvider))
        ? project.provider!.writingProvider
        : 'maestro',
      writingModel: text(project.provider?.writingModel, fallback.provider.writingModel),
      writingBaseUrl: text(project.provider?.writingBaseUrl, fallback.provider.writingBaseUrl),
      imageProvider: project.provider?.imageProvider === 'minimax' ? 'minimax' : 'maestro',
      imageModel: text(project.provider?.imageModel, fallback.provider.imageModel),
    },
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
      model: project.music?.model === 'music-2.6' ? 'music-2.6' : 'music-3.0',
      brief: text(project.music?.brief),
      style: text(project.music?.style),
      sourceLyrics: text(project.music?.sourceLyrics),
      lyrics: text(project.music?.lyrics),
      coverReferenceFilename: text(project.music?.coverReferenceFilename) || undefined,
      coverReferenceName: text(project.music?.coverReferenceName) || undefined,
      targetDurationSeconds: Math.max(20, Math.min(360, Number(project.music?.targetDurationSeconds) || 90)),
      candidateCount: project.music?.candidateCount === 3 ? 3 : 2,
      candidates: Array.isArray(project.music?.candidates)
        ? project.music.candidates.flatMap(candidate => {
          if (!candidate || typeof candidate !== 'object' || !text(candidate.source)) return []
          return [{
            id: text(candidate.id) || storyId('song'),
            name: text(candidate.name, 'Story song'),
            source: text(candidate.source),
            prompt: text(candidate.prompt),
            lyrics: text(candidate.lyrics),
            provider: candidate.provider === 'local' ? 'local' as const : 'minimax' as const,
            model: text(candidate.model),
            durationSeconds: Math.max(0, Number(candidate.durationSeconds) || 0),
            createdAt: text(candidate.createdAt, now),
          }]
        })
        : [],
      selectedCandidateId: text(project.music?.selectedCandidateId) || undefined,
    },
    productions: Array.isArray(project.productions)
      ? project.productions.filter(item => item && typeof item === 'object').map(item => ({
        id: text(item.id) || storyId('production'),
        kind: item.kind === 'film' ? 'film' : 'comic',
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
    before.title, before.language, before.genre, before.tone, before.audience,
    before.visualStyle, before.enforceVisualStyle,
    before.premise, before.logline, before.synopsis, before.theme, before.ending,
  ]
  const overviewAfter = [
    after.title, after.language, after.genre, after.tone, after.audience,
    after.visualStyle, after.enforceVisualStyle,
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
