import type {
  SeriesCharacter, SeriesLibrary, SeriesLocation, SeriesProject, SeriesProp, SeriesVisualVariant,
} from './types'

export const seriesId = (prefix: string): string =>
  `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`

const text = (value: unknown, fallback = ''): string => typeof value === 'string' ? value : fallback
const objects = <T>(value: unknown): T[] => Array.isArray(value)
  ? value.filter(item => item && typeof item === 'object') as T[] : []

export function emptySeriesLibrary(workspaceId = 'default'): SeriesLibrary {
  return { schema: 'series-library', version: 1, workspaceId, seriesOrder: [], seriesById: {} }
}

export function normalizeSeriesProject(value: unknown): SeriesProject | null {
  if (!value || typeof value !== 'object') return null
  const project = value as Partial<SeriesProject>
  if (!text(project.id).trim()) return null
  const now = new Date().toISOString()
  const canon = project.canon && typeof project.canon === 'object' ? project.canon : {} as SeriesProject['canon']
  const provider = project.provider && typeof project.provider === 'object' ? project.provider : {} as SeriesProject['provider']
  const seasons = objects<SeriesProject['seasons'][number]>(project.seasons)
  const episodesById = project.episodesById && typeof project.episodesById === 'object'
    ? project.episodesById : {}
  return {
    ...project,
    version: 1,
    id: text(project.id),
    revision: Math.max(1, Number(project.revision) || 1),
    title: text(project.title, 'Untitled series'),
    logline: text(project.logline), premise: text(project.premise),
    format: project.format === 'serial' || project.format === 'hybrid' ? project.format : 'episodic',
    defaultEpisodeDurationSeconds: Math.max(15, Number(project.defaultEpisodeDurationSeconds) || 75),
    language: text(project.language, 'Español'), genre: text(project.genre),
    tone: text(project.tone, 'Cinematic'), audience: text(project.audience, 'General'),
    visualStyle: text(project.visualStyle), characterVisualStyle: text(project.characterVisualStyle),
    cameraLanguage: text(project.cameraLanguage), allowClipText: project.allowClipText === true,
    sourceMode: project.sourceMode === 'known_universe_experimental' || project.sourceMode === 'hybrid'
      ? project.sourceMode : 'original',
    masterUniversePrompt: text(project.masterUniversePrompt), rightsNote: text(project.rightsNote),
    bestEffortLipSyncAcknowledged: project.bestEffortLipSyncAcknowledged === true,
    importSource: project.importSource && typeof project.importSource === 'object'
      ? project.importSource : {
        kind: 'original', sourceWorkspaceId: null, sourceStoryId: null, importedAt: now,
        historicalProductionIds: [], migrationNotes: '',
      },
    canon: {
      ...canon,
      worldSummary: text(canon.worldSummary), immutableRules: objects(canon.immutableRules),
      currentFacts: objects(canon.currentFacts), forbiddenChanges: Array.isArray(canon.forbiddenChanges)
        ? canon.forbiddenChanges.filter(item => typeof item === 'string') : [],
      themes: Array.isArray(canon.themes) ? canon.themes.filter(item => typeof item === 'string') : [],
      longArcs: objects(canon.longArcs), timeline: objects(canon.timeline),
      revision: Math.max(0, Number(canon.revision) || 0),
      approval: canon.approval === 'approved' ? 'approved' : 'draft',
      approvedAt: text(canon.approvedAt),
    },
    characters: objects(project.characters), relationships: objects(project.relationships),
    locations: objects(project.locations), props: objects(project.props), seasons,
    episodesById, assets: project.assets && typeof project.assets === 'object' ? project.assets : {},
    provider: {
      ...provider,
      // Provider blocks already persisted before global profiles are explicit
      // project overrides; brand-new projects receive true from the backend.
      useGlobalProfile: provider.useGlobalProfile === true,
      writingProvider: provider.writingProvider || 'maestro', writingModel: text(provider.writingModel),
      writingBaseUrl: text(provider.writingBaseUrl), imageProvider: text(provider.imageProvider, 'maestro'),
      imageModel: text(provider.imageModel), videoModel: text(provider.videoModel, 'minimax_h3_legacy').replace('minimax-h3', 'minimax_h3'),
      videoSettings: provider.videoSettings && typeof provider.videoSettings === 'object'
        ? provider.videoSettings : { renderStrategy: 'auto', resolution: '480p', orientation: 'landscape' },
    },
    createdAt: text(project.createdAt, now), updatedAt: text(project.updatedAt, now),
  } as SeriesProject
}

export function normalizeSeriesLibrary(value: unknown, workspace: string): SeriesLibrary {
  if (!value || typeof value !== 'object') return emptySeriesLibrary(workspace)
  const raw = value as Partial<SeriesLibrary>
  const projects: Record<string, SeriesProject> = {}
  if (raw.seriesById && typeof raw.seriesById === 'object') {
    Object.values(raw.seriesById).forEach(item => {
      const normalized = normalizeSeriesProject(item)
      if (normalized) projects[normalized.id] = normalized
    })
  }
  const order = Array.isArray(raw.seriesOrder)
    ? raw.seriesOrder.filter(id => typeof id === 'string' && projects[id]) : []
  Object.keys(projects).forEach(id => { if (!order.includes(id)) order.push(id) })
  return {
    ...(raw as SeriesLibrary), schema: 'series-library', version: 1,
    workspaceId: workspace, seriesOrder: order, seriesById: projects,
  }
}

export function createVisualVariant(label = 'Default'): SeriesVisualVariant {
  return { id: seriesId('variant'), label, description: '', referenceAssetIds: [] }
}

export function createSeriesCharacter(): SeriesCharacter {
  return {
    id: seriesId('character'), name: 'New character', aliases: [], role: '', personality: '',
    desire: '', need: '', flaw: '', longArc: '', voiceAndDialogue: '', appearance: '',
    identityLock: '', wardrobeVariants: [], referenceAssetIds: [], currentState: {}, approval: 'draft',
  }
}

export function createSeriesLocation(): SeriesLocation {
  return {
    id: seriesId('location'), name: 'New location', purpose: '', description: '',
    referenceAssetIds: [], variants: [], currentState: {}, approval: 'draft',
  }
}

export function createSeriesProp(): SeriesProp {
  return {
    id: seriesId('prop'), name: 'New prop', kind: '', description: '', ownerCharacterId: '',
    referenceAssetIds: [], variants: [], currentState: {}, approval: 'draft',
  }
}
