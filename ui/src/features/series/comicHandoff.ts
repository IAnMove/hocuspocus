import { compileProviderPrompt } from '../../lib/languageIntent'
import {
  comicId,
  createComicProject,
  projectFromPlan,
  withComicContentLanguage,
} from '../comics/model'
import type {
  ComicAsset,
  ComicCharacter,
  ComicDirectorRequest,
  ComicPlan,
  ComicPlanPanel,
  ComicProject,
  ComicProvenance,
  ComicSourceEpisode,
  ComicSourceSeries,
} from '../comics/types'
import type {
  SeriesCharacter,
  SeriesEpisode,
  SeriesLibrary,
  SeriesProject,
  SeriesScene,
  SeriesShot,
} from './types'
import { resolveSeriesEpisodeById, type SeriesComicSourceIdentity } from '../comics/provenance'

export interface SeriesComicHandoffInput extends SeriesComicSourceIdentity {
  title?: string
  pageCount?: number
  panelsPerPage?: number
  actor?: ComicProvenance['actor']
}

export interface SeriesComicHandoff {
  comic: ComicProject
  request: ComicDirectorRequest
  provenance: ComicProvenance
  series: SeriesProject
  episode: SeriesEpisode
}

function clean(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function boundedInteger(value: number | undefined, fallback: number, maximum: number): number {
  if (!Number.isFinite(value)) return fallback
  return Math.max(1, Math.min(maximum, Math.round(value as number)))
}

function comicCharacter(character: SeriesCharacter): ComicCharacter {
  return {
    id: character.id,
    name: character.name,
    description: [character.appearance, character.identityLock].filter(Boolean).join('. ') || character.name,
    role: character.role,
    personality: character.personality,
    motivation: character.desire,
    voice: character.voiceAndDialogue,
    wardrobe: character.defaultWardrobeVariantId
      ? character.wardrobeVariants.find(variant => variant.id === character.defaultWardrobeVariantId)?.description || ''
      : '',
    visualNotes: character.identityLock,
    negativePrompt: 'inconsistent face, changed wardrobe, duplicate character, extra limbs',
    referenceAssetId: character.primaryReferenceAssetId,
    referenceAssetIds: [...character.referenceAssetIds],
    locked: true,
  }
}

function sourceOutputAssetIds(series: SeriesProject, episode: SeriesEpisode): string[] {
  const ids = new Set<string>()
  episode.shots.forEach(shot => shot.attempts.forEach(attempt => {
    attempt.outputAssetIds.forEach(id => ids.add(id))
  }))
  Object.values(series.assets).forEach(asset => {
    if (asset.ownerId === episode.id || episode.shots.some(shot => shot.id === asset.ownerId)) ids.add(asset.id)
  })
  return [...ids]
}

function comicAssets(series: SeriesProject, episode: SeriesEpisode): Record<string, ComicAsset> {
  const ids = sourceOutputAssetIds(series, episode)
  return Object.fromEntries(ids.map(id => {
    const source = series.assets[id]
    if (!source) return [id, {
      id,
      name: id,
      kind: 'local' as const,
      source: '',
      missing: true,
      createdAt: new Date().toISOString(),
      metadata: { sourceSeriesId: series.id, sourceEpisodeId: episode.id },
    } satisfies ComicAsset]
    return [id, {
      id: source.id,
      name: source.metadata.name && typeof source.metadata.name === 'string' ? source.metadata.name : source.id,
      kind: 'local' as const,
      source: source.uri,
      createdAt: typeof source.metadata.createdAt === 'string' ? source.metadata.createdAt : new Date().toISOString(),
      metadata: {
        ...source.metadata,
        sourceSeriesId: series.id,
        sourceEpisodeId: episode.id,
        sourceOwnerType: source.ownerType,
        sourceOwnerId: source.ownerId,
      },
    } satisfies ComicAsset]
  }))
}

function sceneForShot(series: SeriesProject, shot: SeriesShot): string {
  const location = shot.locationId ? series.locations.find(item => item.id === shot.locationId) : undefined
  return [
    location ? `Location: ${location.name}. ${location.description}` : '',
    shot.framing ? `Framing: ${shot.framing}.` : '',
    shot.camera ? `Camera: ${shot.camera}.` : '',
    shot.action,
    shot.audioDirection ? `Audio direction: ${shot.audioDirection}.` : '',
    shot.prompt ? `Source shot direction: ${shot.prompt}` : '',
  ].filter(Boolean).join(' ')
}

function panelFromShot(series: SeriesProject, shot: SeriesShot, index: number): ComicPlanPanel {
  const knownCharacters = new Set(series.characters.map(character => character.id))
  const characters = shot.visibleCharacterIds.filter(id => knownCharacters.has(id))
  const dialogue = shot.dialogueBeats
    .filter(line => clean(line.text))
    .map(line => ({
      speakerId: knownCharacters.has(line.characterId) ? line.characterId : undefined,
      text: line.text,
      bubbleType: 'speech' as const,
    }))
  const description = sceneForShot(series, shot)
  return {
    id: comicId('panel-plan'),
    order: index + 1,
    narrativeRole: `Series shot ${shot.order || index + 1}`,
    sceneDescription: description || 'Adapt the selected Series shot as one clear comic panel.',
    imagePrompt: [
      'Single comic panel adapted from an exact Series episode shot.',
      series.visualStyle,
      description,
      'Clean composition, expressive acting, coherent character silhouettes, no lettering, no balloons, no captions.',
    ].filter(Boolean).join(' '),
    characters,
    framing: shot.framing || 'medium',
    dialogue,
    captions: [],
    soundEffects: [],
    continuityNotes: `Preserve Series “${series.title}” and Episode “${shot.sceneId}” identity, wardrobe and location continuity.`,
    videoPrompt: shot.prompt || undefined,
    videoAction: shot.action || undefined,
    durationSeconds: shot.durationSeconds,
  }
}

function panelFromScene(series: SeriesProject, scene: SeriesScene, index: number): ComicPlanPanel {
  const knownCharacters = new Set(series.characters.map(character => character.id))
  const dialogue = scene.dialogue.filter(line => clean(line.text)).map(line => ({
    speakerId: knownCharacters.has(line.characterId) ? line.characterId : undefined,
    text: line.text,
    bubbleType: 'speech' as const,
  }))
  const location = series.locations.find(item => item.id === scene.locationId)
  const description = [
    location ? `Location: ${location.name}. ${location.description}` : '',
    scene.time ? `Time: ${scene.time}.` : '',
    scene.purpose,
    scene.beats.map(beat => beat.summary).filter(Boolean).join(' '),
    scene.entryState ? `Entry state: ${scene.entryState}.` : '',
    scene.exitState ? `Exit state: ${scene.exitState}.` : '',
  ].filter(Boolean).join(' ')
  return {
    id: comicId('panel-plan'),
    order: index + 1,
    narrativeRole: `Series scene ${scene.order || index + 1}`,
    sceneDescription: description || 'Adapt the selected Series scene as one clear comic panel.',
    imagePrompt: [
      'Single comic panel adapted from an exact Series episode scene.',
      series.visualStyle,
      description,
      'Clean composition, expressive acting, coherent character silhouettes, no lettering, no balloons, no captions.',
    ].filter(Boolean).join(' '),
    characters: scene.participatingCharacterIds.filter(id => knownCharacters.has(id)),
    framing: 'medium',
    dialogue,
    captions: [],
    soundEffects: [],
    continuityNotes: `Preserve Series “${series.title}” and Episode scene ${scene.id} continuity.`,
  }
}

function sourcePanels(series: SeriesProject, episode: SeriesEpisode): ComicPlanPanel[] {
  const shots = [...episode.shots].sort((left, right) => left.order - right.order)
  if (shots.length) return shots.map((shot, index) => panelFromShot(series, shot, index))
  const scenes = [...episode.script].sort((left, right) => left.order - right.order)
  if (scenes.length) return scenes.map((scene, index) => panelFromScene(series, scene, index))
  const beats = episode.outline.beats.filter(beat => clean(beat))
  return (beats.length ? beats : [episode.premise || episode.logline || episode.title]).map((beat, index) => ({
    id: comicId('panel-plan'),
    order: index + 1,
    narrativeRole: `Episode beat ${index + 1}`,
    sceneDescription: beat,
    imagePrompt: [
      'Single comic panel adapted from an exact Series episode beat.',
      series.visualStyle,
      beat,
      'Clean composition, expressive acting, coherent character silhouettes, no lettering, no balloons, no captions.',
    ].filter(Boolean).join(' '),
    characters: series.protagonistCharacterId ? [series.protagonistCharacterId] : [],
    framing: 'medium',
    dialogue: [],
    captions: [],
    soundEffects: [],
    continuityNotes: `Preserve Series “${series.title}” and Episode “${episode.title}” continuity.`,
  }))
}

function makeSourceContext(
  series: SeriesProject,
  episode: SeriesEpisode,
  source: SeriesComicSourceIdentity,
): string {
  return [
    'SERIES → COMICS ADAPTATION CONTRACT',
    `Exact source workspace ID: ${source.workspaceId}`,
    `Exact source series ID: ${source.seriesId}`,
    `Exact source episode ID: ${source.episodeId}`,
    `Series: ${series.title}`,
    `Episode: ${episode.title}`,
    `Series canon: ${series.canon.worldSummary}`,
    `Series visual style: ${series.visualStyle}`,
    `Episode premise: ${episode.premise}`,
    `Episode logline: ${episode.logline}`,
    `Episode outline: ${episode.outline.beats.join(' · ')}`,
  ].filter(Boolean).join('\n')
}

/**
 * Build a complete, editable Comic draft from the exact Series episode in a
 * loaded library. This function never searches by title and never generates
 * provider output; the caller may let the user edit and save it first.
 */
export function buildSeriesComicHandoff(
  library: SeriesLibrary,
  input: SeriesComicHandoffInput,
): SeriesComicHandoff {
  const source = {
    workspaceId: input.workspaceId.trim(),
    seriesId: input.seriesId.trim(),
    episodeId: input.episodeId.trim(),
  }
  if (!source.workspaceId || !source.seriesId || !source.episodeId) {
    throw new Error('Series → Comics requires workspaceId, seriesId and episodeId.')
  }
  const { series, episode } = resolveSeriesEpisodeById(library, source)
  const panelsPerPage = boundedInteger(input.panelsPerPage, 4, 12)
  const panels = sourcePanels(series, episode)
  const pageCount = Math.max(1, Math.min(100, Math.ceil(panels.length / panelsPerPage)))
  const languageIntent = series.languageIntent
  const characters = series.characters.map(comicCharacter)
  const title = clean(input.title) || `${series.title} · ${episode.title}`
  const comic = createComicProject()
  const sourceSeries: ComicSourceSeries = {
    id: series.id,
    revision: series.revision,
    title: series.title,
  }
  const sourceEpisode: ComicSourceEpisode = {
    id: episode.id,
    seasonId: episode.seasonId,
    title: episode.title,
    updatedAt: episode.updatedAt,
  }
  const provenance: ComicProvenance = {
    schema: 'comic-provenance-v1',
    workspaceId: source.workspaceId,
    source: {
      kind: 'series_episode',
      seriesId: series.id,
      seriesRevision: series.revision,
      episodeId: episode.id,
      episodeUpdatedAt: episode.updatedAt,
      productionIds: [...episode.productionIds],
      outputAssetIds: sourceOutputAssetIds(series, episode),
    },
    destination: { comicId: comic.id },
    actor: input.actor || 'wizard',
    tool: 'series_lab',
    capability: 'stage_series_comic',
    createdAt: new Date().toISOString(),
  }
  const plan: ComicPlan = {
    version: 1,
    id: comicId('plan'),
    title,
    logline: episode.logline || episode.premise,
    synopsis: episode.premise || episode.logline,
    language: languageIntent.contentLanguage || series.language,
    styleBible: series.visualStyle,
    characters,
    pages: Array.from({ length: pageCount }, (_, pageIndex) => ({
      pageNumber: pageIndex + 1,
      layoutHint: 'grid' as const,
      panels: panels.slice(pageIndex * panelsPerPage, (pageIndex + 1) * panelsPerPage),
    })).filter(page => page.panels.length),
  }
  const prepared = projectFromPlan(plan, {
    ...comic,
    title,
    synopsis: episode.premise || episode.logline,
    language: languageIntent.contentLanguage || series.language,
    languageIntent,
    characters,
    assets: comicAssets(series, episode),
    provenance,
    style: {
      ...comic.style,
      name: series.visualStyle || 'Series adaptation',
      promptSuffix: [series.visualStyle, 'Preserve the exact Series character and location continuity.'].filter(Boolean).join('. '),
    },
  })
  const provider = series.provider.imageProvider === 'minimax' ? 'minimax' : 'maestro'
  const request: ComicDirectorRequest = {
    useGlobalProfile: series.provider.useGlobalProfile,
    premise: compileProviderPrompt(
      episode.premise || episode.logline || title,
      languageIntent,
      { medium: 'comic' },
    ),
    productionMode: 'comic',
    storyContext: compileProviderPrompt(makeSourceContext(series, episode, source), languageIntent, { medium: 'comic' }),
    sourceSeries,
    sourceEpisode,
    pageCount: plan.pages.length,
    language: languageIntent.contentLanguage || series.language,
    format: 'a4',
    panelsPerPage,
    genre: series.genre,
    tone: series.tone,
    audience: series.audience,
    artStyle: series.visualStyle,
    worldContext: series.canon.worldSummary,
    forbiddenElements: series.canon.forbiddenChanges.join('; '),
    worldReferenceAssetIds: [],
    dialogueDensity: 'medium',
    writingProvider: series.provider.writingProvider,
    writingModel: series.provider.writingModel,
    writingBaseUrl: series.provider.writingBaseUrl,
    provider,
    imageModel: series.provider.imageModel,
    characters,
    ending: 'Preserve the exact episode ending and its canon consequences.',
  }
  const withDirector = withComicContentLanguage({
    ...prepared,
    director: {
      planId: plan.id,
      provider,
      imageModel: request.imageModel,
      input: request,
      plan,
      completedPanelIds: [],
      failedPanelIds: [],
      panelJobs: {},
      scriptVersion: 1,
    },
  }, request.language)
  return { comic: withDirector, request, provenance, series, episode }
}
