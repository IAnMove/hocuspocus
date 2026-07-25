import { createComicProject } from '../comics/model'
import type {
  ComicAsset,
  ComicCharacter,
  ComicDirectorRequest,
  ComicProject,
} from '../comics/types'
import type { StoryCharacter, StoryProject } from './types'

const line = (label: string, value: string | undefined): string =>
  value?.trim() ? `${label}: ${value.trim()}` : ''

function characterName(project: StoryProject, id: string): string {
  return project.characters.find(character => character.id === id)?.name || id
}

function comicCharacter(character: StoryCharacter): ComicCharacter {
  return {
    id: character.id,
    name: character.name,
    description: [
      character.age ? `Age: ${character.age}.` : '',
      character.pronouns ? `Pronouns: ${character.pronouns}.` : '',
      character.appearance,
      character.wardrobe ? `Canonical wardrobe: ${character.wardrobe}.` : '',
    ].filter(Boolean).join(' '),
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

export function buildComicAdaptation(project: StoryProject): {
  comic: ComicProject
  request: ComicDirectorRequest
} {
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
    premise: project.logline || project.premise || project.synopsis,
    storyContext: storyAdaptationContext(project),
    sourceStory: {
      id: project.id,
      revision: project.revision,
      title: project.title,
    },
    pageCount: Math.max(1, project.beats.length || 6),
    language: project.language,
    format: 'a4',
    panelsPerPage: 4,
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
    ending: project.ending,
  }
  return { comic, request }
}
