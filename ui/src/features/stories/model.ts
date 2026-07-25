import type {
  StoryBeat, StoryCharacter, StoryLocation, StoryProject, StoryRelationship,
  StoryVisualAsset,
} from './types'

export type StorySection = 'overview' | 'world' | 'characters' | 'relationships' | 'structure'

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
    before.premise, before.logline, before.synopsis, before.theme, before.ending,
  ]
  const overviewAfter = [
    after.title, after.language, after.genre, after.tone, after.audience,
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
