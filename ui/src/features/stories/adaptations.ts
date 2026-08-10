import { createComicProject } from '../comics/model'
import type {
  ComicAsset,
  ComicCharacter,
  ComicDirectorRequest,
  ComicProject,
} from '../comics/types'
import type { ShortFilmCharacter } from '../../types'
import { storyNegativePromptForStyle, storyRenderStyle, stripStoryVisualStyle } from './model'
import type { StoryCharacter, StoryMusicCue, StoryProject } from './types'

export const DEFAULT_COMIC_CHAPTER_DIRECTION =
  'Create a self-contained comic chapter inside this story world. Tell a new compact incident with a beginning, escalation, decisive action and resolution. Preserve the master plot and ending for later chapters; do not summarize or resolve the whole source story.'

export const DEFAULT_SHORT_FILM_DIRECTION =
  'Create a self-contained short-film episode inside this story world. Focus on one concrete incident and emotional turn that can be understood on its own. Preserve the master plot and ending; do not compress the whole source story into this film.'

const line = (label: string, value: string | undefined): string =>
  value?.trim() ? `${label}: ${value.trim()}` : ''

function characterName(project: StoryProject, id: string): string {
  return project.characters.find(character => character.id === id)?.name || id
}

function approvedReferenceIds(project: StoryProject, ids: string[]): string[] {
  return Array.from(new Set(ids)).filter(id => project.assets[id]?.approval === 'approved')
}

function approvedCharacterReferenceIds(
  project: StoryProject,
  character: StoryCharacter,
  maximum = 3,
): string[] {
  const approved = approvedReferenceIds(project, character.referenceAssetIds)
  const primary = character.primaryReferenceAssetId
  const ordered = primary && approved.includes(primary)
    ? [primary, ...approved.filter(id => id !== primary)]
    : approved
  return ordered.slice(0, maximum)
}

function canonicalCharacterDescription(character: StoryCharacter): string {
  return [
    character.age ? `Age: ${character.age}.` : '',
    character.pronouns ? `Pronouns: ${character.pronouns}.` : '',
    character.appearance,
    character.wardrobe ? `Canonical wardrobe: ${character.wardrobe}.` : '',
    character.visualPrompt ? `Visual identity: ${stripStoryVisualStyle(character.visualPrompt)}.` : '',
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

function comicCharacter(
  project: StoryProject,
  character: StoryCharacter,
  visualStyle: string,
  enforceVisualStyle: boolean,
): ComicCharacter {
  const referenceAssetIds = approvedCharacterReferenceIds(project, character)
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
    visualNotes: stripStoryVisualStyle(character.visualPrompt),
    negativePrompt: storyNegativePromptForStyle(
      character.negativePrompt,
      visualStyle,
      enforceVisualStyle,
    ),
    referenceAssetIds,
    referenceAssetId: referenceAssetIds[0],
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
    line('Global visual style', project.enforceVisualStyle ? project.visualStyle : ''),
    line('Character rendering style', project.enforceVisualStyle ? project.characterVisualStyle : ''),
    project.allowClipText
      ? 'Visible text in generated clips: allowed when explicitly authored.'
      : 'Visible text in generated clips: forbidden. Dialogue and lyrics are audio/performance only; never render them as captions, subtitles, signs, UI or other readable lettering.',
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
      location.visualPrompt ? `Visual continuity: ${stripStoryVisualStyle(location.visualPrompt)}` : '',
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
  const enforcedVisualStyle = project.enforceVisualStyle
    ? storyRenderStyle(project)
    : ''
  const hasStyleLock = Boolean(enforcedVisualStyle)
  const compatibleNegative = (value: string) => storyNegativePromptForStyle(
    value,
    enforcedVisualStyle,
    hasStyleLock,
  )
  const comic = createComicProject()
  comic.title = project.title
  comic.synopsis = project.synopsis
  comic.language = project.language
  comic.assets = Object.fromEntries(Object.values(project.assets)
    .filter(asset => asset.approval === 'approved')
    .map(asset => [asset.id, {
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
  comic.characters = project.characters.map(character => comicCharacter(
    project,
    character,
    enforcedVisualStyle,
    hasStyleLock,
  ))

  const worldContext = [
    project.world.summary,
    line('Period', project.world.period),
    line('Geography', project.world.geography),
    line('Society', project.world.society),
    line('Technology', project.world.technology),
    line('World rules', project.world.rules.join('; ')),
    ...project.world.locations.map(location =>
      `${location.name}: ${[location.purpose, location.description, stripStoryVisualStyle(location.visualPrompt)]
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
    // A locked global style replaces inherited art direction. Keeping the old
    // visual language in Story makes the toggle reversible without asking an
    // image model to reconcile two contradictory media at render time.
    artStyle: enforcedVisualStyle || project.world.visualLanguage,
    worldContext,
    forbiddenElements: [
      compatibleNegative(project.world.negativePrompt),
      ...project.world.locations.map(location => compatibleNegative(location.negativePrompt)),
    ].filter(Boolean).join('; '),
    worldReferenceAssetIds: Array.from(new Set([
      ...approvedReferenceIds(project, project.world.referenceAssetIds),
      ...project.world.locations.flatMap(location => approvedReferenceIds(project, location.referenceAssetIds)),
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

export interface MusicVideoAdaptation {
  sceneDescription: string
  focusKind: 'world' | 'character' | 'story'
  focusTargetId: string
  focusLabel: string
  characterReferences: Array<{ assetId: string; label: string }>
  locationReferences: Array<{ assetId: string; label: string }>
}

export interface MusicVideoAdaptationOptions {
  generationMode?: StoryProject['musicVideoGenerationMode']
}

/** Build a song-led visual brief whose subject follows the authored music cue. */
export function buildMusicVideoAdaptation(
  project: StoryProject,
  cue?: StoryMusicCue,
  options: MusicVideoAdaptationOptions = {},
): MusicVideoAdaptation {
  const directVideo = options.generationMode === 'direct_video'
  const focusKind = cue?.kind || 'story'
  const targetCharacter = focusKind === 'character'
    ? project.characters.find(character => character.id === cue?.targetId)
    : undefined
  const mentionedCharacters = project.characters.filter(character =>
    (cue?.lyrics || '').toLocaleLowerCase().includes(character.name.toLocaleLowerCase()))
  const focusedCharacters = focusKind === 'story'
    ? project.characters
    : focusKind === 'character'
      ? Array.from(new Map([targetCharacter, ...mentionedCharacters]
          .filter(Boolean)
          .map(character => [character!.id, character!])).values())
      : mentionedCharacters
  const characterReferences = focusedCharacters.flatMap(character =>
    approvedCharacterReferenceIds(project, character).map((assetId, index) => ({
      assetId,
      label: index === 0 ? `${character.name} · primary` : `${character.name} · view ${index + 1}`,
    })))
  const locationReferences = [
    ...approvedReferenceIds(project, project.world.referenceAssetIds).map(assetId => ({
      assetId,
      label: project.world.summary ? `${project.title} · world` : 'World',
    })),
    ...project.world.locations.flatMap(location =>
      approvedReferenceIds(project, location.referenceAssetIds)
        .map(assetId => ({ assetId, label: location.name }))),
  ]
  const focusLabel = targetCharacter?.name
    || (focusKind === 'world' ? `${project.title} · world` : project.title)
  const directCharacterCanon = (character: StoryCharacter) => [
    `${character.name} (${character.role || 'character'})`,
    character.age ? `Age: ${character.age}.` : '',
    character.pronouns ? `Pronouns: ${character.pronouns}.` : '',
    character.appearance,
    character.wardrobe ? `Canonical wardrobe: ${character.wardrobe}.` : '',
    canonicalCharacterPsychology(character),
  ].filter(Boolean).join('\n')
  const directWorldCanon = [
    line('World', project.world.summary),
    line('Period', project.world.period),
    line('Geography', project.world.geography),
    line('Society', project.world.society),
    line('Technology', project.world.technology),
    line('World rules', project.world.rules.join('; ')),
    ...project.world.locations.map(location => [
      location.name,
      location.purpose,
      location.description,
    ].filter(Boolean).join(' · ')),
  ].filter(Boolean).join('\n')
  const directStoryCanon = [
    line('Source title', project.title),
    line('Premise', project.premise),
    line('Synopsis', project.synopsis),
    line('Theme', project.theme),
    line('Required ending', project.ending),
    '',
    'NARRATIVE CHARACTERS',
    ...project.characters.map(directCharacterCanon),
    '',
    'DRAMATIC BEATS',
    ...project.beats.map((beat, index) => [
      `${index + 1}. ${beat.stage}${beat.title ? ` — ${beat.title}` : ''}`,
      line('Action', beat.summary),
      line('Conflict', beat.conflict),
      line('Turn', beat.turn),
    ].filter(Boolean).join(' · ')),
    '',
    'NARRATIVE WORLD FACTS',
    directWorldCanon,
  ].filter(Boolean).join('\n')
  const focusCanon = targetCharacter
    ? directVideo ? directCharacterCanon(targetCharacter) : [
        `${targetCharacter.name} (${targetCharacter.role || 'character'})`,
        canonicalCharacterDescription(targetCharacter),
        canonicalCharacterPsychology(targetCharacter),
      ].join('\n')
    : focusKind === 'world'
      ? directVideo
        ? directWorldCanon
        : [project.world.summary, project.world.visualPrompt, ...project.world.rules].filter(Boolean).join('\n')
      : directVideo ? directStoryCanon : storyAdaptationContext(project)

  return {
    focusKind,
    focusTargetId: targetCharacter?.id || (focusKind === 'world' ? 'world' : project.id),
    focusLabel,
    sceneDescription: [
      'PRODUCTION TASK',
      `Create a song-led music video focused on ${focusLabel}.`,
      focusKind === 'character'
        ? 'Keep this character visually recognizable in every relevant shot. Other characters may appear only when named in the lyrics.'
        : focusKind === 'world'
          ? 'Prioritize atmosphere, places and the rules of this world over unrelated character coverage.'
          : 'Translate the song into a coherent visual arc across the main story and cast.',
      '',
      line('Song title / cue', cue?.title),
      line('Song purpose', cue?.purpose),
      line('Music-video brief', cue?.brief),
      line('Musical style', cue?.style),
      project.allowClipText
        ? 'VISIBLE TEXT POLICY: Intentional readable text is allowed only when a shot explicitly needs it.'
        : 'VISIBLE TEXT POLICY — STRICT: Do not show lyrics, dialogue, captions, subtitles, title cards, labels, signs, UI lettering or any other readable words in any generated image or video. Treat the lyrics below only as audio timing and semantic inspiration. Never quote, copy or materialize lyric lines visually; express their meaning through characters, action, setting, light and symbolism instead. Any screens, code or signage must remain abstract and unreadable.',
      cue?.lyrics ? `AUTHORITATIVE LYRICS\n${cue.lyrics}` : '',
      '',
      'FOCUS CANON',
      focusCanon,
      '',
      directVideo ? 'DIRECT VIDEO NARRATIVE CONTRACT' : 'VISUAL WORLD BIBLE',
      directVideo
        ? 'The immutable visual world/style prompt is supplied separately and is the only aesthetic authority. Use this Story material only for concrete subjects, places and actions; do not infer or repeat an alternate rendering style.'
        : line('Global visual style', project.enforceVisualStyle ? project.visualStyle : ''),
      directVideo ? line('Narrative world', project.world.summary) : line('Character rendering style', project.enforceVisualStyle ? project.characterVisualStyle : ''),
      directVideo ? '' : line('Visual language', project.world.visualLanguage),
      directVideo ? '' : line('Forbidden imagery', project.world.negativePrompt),
      project.allowClipText
        ? ''
        : 'FINAL VISIBLE-TEXT OVERRIDE: If any lyric, beat, location note or visual-language sentence above mentions words, code text, dialogue on screen or floating lettering, reinterpret that idea as nonverbal imagery. Do not include the quoted words or any text-rendering instruction in image_prompt, video_prompt, keyframes or window prompts.',
    ].filter(Boolean).join('\n'),
    characterReferences: directVideo ? [] : Array.from(
      new Map(characterReferences.map(reference => [reference.assetId, reference])).values(),
    ),
    locationReferences: directVideo ? [] : Array.from(
      new Map(locationReferences.map(reference => [reference.assetId, reference])).values(),
    ),
  }
}

/** Build an editable, self-contained Director episode without flattening the master story. */
export function buildShortFilmAdaptation(
  project: StoryProject,
  direction = DEFAULT_SHORT_FILM_DIRECTION,
  targetDuration = 45,
  options: ShortFilmAdaptationOptions = {},
): ShortFilmAdaptation {
  const preserveVisualStyle = options.preserveVisualStyle ?? true
  const enforcedVisualStyle = project.enforceVisualStyle
    ? project.visualStyle.trim()
    : ''
  const renderStyleLock = project.enforceVisualStyle ? storyRenderStyle(project) : ''
  const hasStyleLock = Boolean(renderStyleLock)
  const compatibleNegative = (value: string) => storyNegativePromptForStyle(
    value,
    renderStyleLock,
    hasStyleLock,
  )
  const visualStyle = enforcedVisualStyle || project.world.visualLanguage.trim()
    || 'Match the approved Story reference artwork exactly, preserving its authored visual medium and character design; if it is anime, comic or illustration, keep it illustrated and never reinterpret it as live action.'
  const characterReferences = project.characters.flatMap(character =>
    approvedCharacterReferenceIds(project, character).map((assetId, index) => ({
      assetId,
      label: index === 0 ? `${character.name} · primary` : `${character.name} · view ${index + 1}`,
    })))
  const locationReferences = [
    ...approvedReferenceIds(project, project.world.referenceAssetIds).map(assetId => ({
      assetId,
      label: project.world.summary ? `${project.title} · world` : 'World',
    })),
    ...project.world.locations.flatMap(location =>
      approvedReferenceIds(project, location.referenceAssetIds)
        .map(assetId => ({ assetId, label: location.name }))),
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
      line('Global visual style', enforcedVisualStyle),
      line('Visual language', hasStyleLock ? '' : project.world.visualLanguage),
      line('World visual prompt', stripStoryVisualStyle(project.world.visualPrompt)),
      line('Forbidden imagery', [
        compatibleNegative(project.world.negativePrompt),
        ...project.world.locations.map(location => compatibleNegative(location.negativePrompt)),
      ].filter(Boolean).join('; ')),
      preserveVisualStyle ? '' : 'Visual medium may be reinterpreted for this adaptation.',
    ].filter(Boolean).join('\n'),
    characters: project.characters.map(character => {
      const negativePrompt = compatibleNegative(character.negativePrompt)
      return {
        name: character.name,
        description: [
          canonicalCharacterDescription(character),
          canonicalCharacterPsychology(character),
          negativePrompt ? `Never depict: ${negativePrompt}.` : '',
        ].filter(Boolean).join(' '),
      }
    }),
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
