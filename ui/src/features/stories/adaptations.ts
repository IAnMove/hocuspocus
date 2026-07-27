import { createComicProject } from '../comics/model'
import type {
  ComicAsset,
  ComicCharacter,
  ComicDirectorRequest,
  ComicProject,
} from '../comics/types'
import type { ShortFilmCharacter } from '../../types'
import type { StoryCharacter, StoryProject } from './types'

export const DEFAULT_COMIC_CHAPTER_DIRECTION =
  'Create a self-contained comic chapter inside this story world. Tell a new compact incident with a beginning, escalation, decisive action and resolution. Preserve the master plot and ending for later chapters; do not summarize or resolve the whole source story.'

export const DEFAULT_SHORT_FILM_DIRECTION =
  'Create a self-contained short-film episode inside this story world. Focus on one concrete incident and emotional turn that can be understood on its own. Preserve the master plot and ending; do not compress the whole source story into this film.'

const line = (label: string, value: string | undefined): string =>
  value?.trim() ? `${label}: ${value.trim()}` : ''

function characterName(project: StoryProject, id: string): string {
  return project.characters.find(character => character.id === id)?.name || id
}

function canonicalCharacterDescription(character: StoryCharacter): string {
  return [
    character.age ? `Age: ${character.age}.` : '',
    character.pronouns ? `Pronouns: ${character.pronouns}.` : '',
    character.appearance,
    character.wardrobe ? `Canonical wardrobe: ${character.wardrobe}.` : '',
    character.visualPrompt ? `Visual identity: ${character.visualPrompt}.` : '',
  ].filter(Boolean).join(' ')
}

function canonicalCharacterPsychology(character: StoryCharacter): string {
  return [
    character.personality,
    character.desire ? `Wants: ${character.desire}.` : '',
    character.need ? `Needs: ${character.need}.` : '',
    character.flaw ? `Flaw: ${character.flaw}.` : '',
    character.conflict ? `Central conflict: ${character.conflict}.` : '',
    character.arc ? `Master arc: ${character.arc}.` : '',
    character.voice ? `Voice: ${character.voice}.` : '',
  ].filter(Boolean).join(' ')
}

function comicCharacter(character: StoryCharacter): ComicCharacter {
  return {
    id: character.id,
    name: character.name,
    description: canonicalCharacterDescription(character),
    role: character.role,
    personality: [
      character.personality,
      character.flaw ? `Flaw: ${character.flaw}.` : '',
      character.conflict ? `Central conflict: ${character.conflict}.` : '',
    ].filter(Boolean).join(' '),
    motivation: [
      character.desire ? `Wants: ${character.desire}.` : '',
      character.need ? `Needs: ${character.need}.` : '',
      character.arc ? `Arc: ${character.arc}.` : '',
    ].filter(Boolean).join(' '),
    voice: character.voice,
    wardrobe: character.wardrobe,
    visualNotes: character.visualPrompt,
    negativePrompt: character.negativePrompt,
    referenceAssetIds: Array.from(new Set(character.referenceAssetIds)),
    referenceAssetId: character.primaryReferenceAssetId,
    locked: true,
  }
}

/** A readable source-of-truth block that remains manually editable in Comic Director. */
export function storyAdaptationContext(project: StoryProject): string {
  const sections = [
    line('Source title', project.title),
    line('Premise', project.premise),
    line('Logline', project.logline),
    line('Synopsis', project.synopsis),
    line('Theme', project.theme),
    line('Required ending', project.ending),
    '',
    'DRAMATIC BEATS',
    ...project.beats.map((beat, index) => [
      `${index + 1}. ${beat.stage}${beat.title ? ` — ${beat.title}` : ''}`,
      line('Goal', beat.goal),
      line('Action', beat.summary),
      line('Conflict', beat.conflict),
      line('Turn', beat.turn),
    ].filter(Boolean).join(' · ')),
    '',
    'CHARACTER RELATIONSHIPS',
    ...(project.relationships.length
      ? project.relationships.map(relationship => [
        `${characterName(project, relationship.fromCharacterId)} → ${characterName(project, relationship.toCharacterId)}`,
        relationship.label,
        relationship.dynamic,
        relationship.evolution ? `Evolution: ${relationship.evolution}` : '',
      ].filter(Boolean).join(' · '))
      : ['No explicit relationships supplied.']),
    '',
    'WORLD AND LOCATIONS',
    line('World', project.world.summary),
    line('Period', project.world.period),
    line('Geography', project.world.geography),
    line('Society', project.world.society),
    line('Technology', project.world.technology),
    line('Rules', project.world.rules.join('; ')),
    ...project.world.locations.map(location => [
      location.name,
      location.purpose,
      location.description,
      location.visualPrompt ? `Visual continuity: ${location.visualPrompt}` : '',
    ].filter(Boolean).join(' · ')),
    '',
    'CHARACTER ARCS AND VOICES',
    ...project.characters.map(character => [
      `${character.name} (${character.role || 'character'})`,
      line('Personality', character.personality),
      line('Desire', character.desire),
      line('Need', character.need),
      line('Flaw', character.flaw),
      line('Conflict', character.conflict),
      line('Arc', character.arc),
      line('Voice', character.voice),
    ].filter(Boolean).join(' · ')),
  ]
  return sections.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

export function buildComicAdaptation(
  project: StoryProject,
  direction = DEFAULT_COMIC_CHAPTER_DIRECTION,
  options: {
    pageCount?: number
    panelsPerPage?: number
  } = {},
): {
  comic: ComicProject
  request: ComicDirectorRequest
} {
  const pageCount = Math.max(1, Math.min(100, Math.round(options.pageCount || 4)))
  const panelsPerPage = Math.max(1, Math.min(12, Math.round(options.panelsPerPage || 4)))
  const comic = createComicProject()
  comic.title = project.title
  comic.synopsis = project.synopsis
  comic.language = project.language
  comic.assets = Object.fromEntries(Object.values(project.assets).map(asset => [asset.id, {
    id: asset.id,
    name: asset.name,
    kind: asset.provider === 'minimax'
      ? 'minimax'
      : asset.provider === 'upload' ? 'upload' : 'local',
    source: asset.source,
    prompt: asset.prompt,
    provider: asset.provider,
    model: asset.model,
    createdAt: asset.createdAt,
  } satisfies ComicAsset]))
  comic.characters = project.characters.map(comicCharacter)

  const worldContext = [
    project.world.summary,
    line('Period', project.world.period),
    line('Geography', project.world.geography),
    line('Society', project.world.society),
    line('Technology', project.world.technology),
    line('World rules', project.world.rules.join('; ')),
    ...project.world.locations.map(location =>
      `${location.name}: ${[location.purpose, location.description, location.visualPrompt]
        .filter(Boolean).join(' · ')}`),
  ].filter(Boolean).join('\n')

  const request: ComicDirectorRequest = {
    premise: [
      direction.trim() || DEFAULT_COMIC_CHAPTER_DIRECTION,
      `Source-story hook: ${project.logline || project.premise || project.synopsis}`,
    ].join('\n\n'),
    storyContext: [
      'ADAPTATION CONTRACT',
      'The production premise above defines the chapter to create. The material below is the master-story canon: preserve its established facts, relationships and long-term arcs, but do not treat every master beat as a scene that must be retold.',
      '',
      storyAdaptationContext(project),
    ].join('\n'),
    sourceStory: {
      id: project.id,
      revision: project.revision,
      title: project.title,
    },
    pageCount,
    language: project.language,
    format: 'a4',
    panelsPerPage,
    genre: project.genre,
    tone: project.tone,
    audience: project.audience,
    artStyle: [project.world.visualLanguage, project.world.visualPrompt]
      .filter(Boolean).join('. '),
    worldContext,
    forbiddenElements: [
      project.world.negativePrompt,
      ...project.world.locations.map(location => location.negativePrompt),
    ].filter(Boolean).join('; '),
    worldReferenceAssetIds: Array.from(new Set([
      ...project.world.referenceAssetIds,
      ...project.world.locations.flatMap(location => location.referenceAssetIds),
    ])),
    dialogueDensity: 'medium',
    writingProvider: project.provider.writingProvider,
    writingModel: project.provider.writingModel,
    writingBaseUrl: project.provider.writingBaseUrl,
    provider: project.provider.imageProvider,
    imageModel: project.provider.imageProvider === 'minimax'
      ? 'image-01'
      : project.provider.imageModel,
    characters: comic.characters,
    ending: 'Resolve the chapter incident and its immediate emotional turn while preserving the source story’s larger arc and canonical ending.',
  }
  return { comic, request }
}

export interface ShortFilmAdaptation {
  sceneDescription: string
  characters: ShortFilmCharacter[]
  targetDuration: number
  narrative: boolean
  visualStyle: string
  preserveVisualStyle: boolean
  characterReferences: Array<{ assetId: string; label: string }>
  locationReferences: Array<{ assetId: string; label: string }>
}

export interface ShortFilmAdaptationOptions {
  preserveVisualStyle?: boolean
}

/** Build an editable, self-contained Director episode without flattening the master story. */
export function buildShortFilmAdaptation(
  project: StoryProject,
  direction = DEFAULT_SHORT_FILM_DIRECTION,
  targetDuration = 45,
  options: ShortFilmAdaptationOptions = {},
): ShortFilmAdaptation {
  const preserveVisualStyle = options.preserveVisualStyle ?? true
  const visualStyle = [
    project.world.visualLanguage,
    project.world.visualPrompt,
  ].map(value => value.trim()).filter(Boolean).join('. ')
    || 'Match the approved Story reference artwork exactly, preserving its authored visual medium and character design; if it is anime, comic or illustration, keep it illustrated and never reinterpret it as live action.'
  const characterReferences = project.characters.flatMap(character => {
    const assetId = character.primaryReferenceAssetId || character.referenceAssetIds[0]
    return assetId ? [{ assetId, label: character.name }] : []
  })
  const locationReferences = [
    ...project.world.referenceAssetIds.map(assetId => ({
      assetId,
      label: project.world.summary ? `${project.title} · world` : 'World',
    })),
    ...project.world.locations.flatMap(location =>
      location.referenceAssetIds.map(assetId => ({ assetId, label: location.name }))),
  ]

  return {
    sceneDescription: [
      'PRODUCTION TASK',
      direction.trim() || DEFAULT_SHORT_FILM_DIRECTION,
      'The film must be a new compact episode that is faithful to the canon below, not a synopsis of the entire master story.',
      '',
      'MASTER STORY CANON',
      storyAdaptationContext(project),
      '',
      'VISUAL WORLD BIBLE',
      line('Visual language', project.world.visualLanguage),
      line('World visual prompt', project.world.visualPrompt),
      line('Forbidden imagery', [
        project.world.negativePrompt,
        ...project.world.locations.map(location => location.negativePrompt),
      ].filter(Boolean).join('; ')),
      preserveVisualStyle ? '' : 'Visual medium may be reinterpreted for this adaptation.',
    ].filter(Boolean).join('\n'),
    characters: project.characters.map(character => ({
      name: character.name,
      description: [
        canonicalCharacterDescription(character),
        canonicalCharacterPsychology(character),
        character.negativePrompt ? `Never depict: ${character.negativePrompt}.` : '',
      ].filter(Boolean).join(' '),
    })),
    targetDuration: Math.max(10, Math.min(1800, Math.round(targetDuration || 45))),
    narrative: true,
    visualStyle,
    preserveVisualStyle,
    characterReferences: Array.from(
      new Map(characterReferences.map(reference => [reference.assetId, reference])).values(),
    ),
    locationReferences: Array.from(
      new Map(locationReferences.map(reference => [reference.assetId, reference])).values(),
    ),
  }
}
