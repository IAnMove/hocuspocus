import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { scaffoldLanguage } from '../../lib/contentLanguage'
import i18n from '../../i18n'
import {
  boundedDuration,
  creativeCharacters,
  creativeLocations,
  normalizeName,
  outlineBeats,
} from '../../lib/labHelpers'
import { useStore } from '../../stores/useStore'
import { compileProviderPrompt, mergeLanguageIntent } from '../../lib/languageIntent'
import { applyLegacyStoryLanguage, applyStoryLanguageIntent, seedStoryLanguageIntent } from './languageIntent'
import { storyJobKey, storyResultKey } from './storyLabSession'
import { applyMusicVideoDirectVideoDefaults, resolveMusicVideoVisualStyle } from './musicVideoLook'
import {
  assertStorySongFidelity,
  buildStorySongWritingRequest,
  protectedSongLyrics,
  resolveStorySongLanguage,
  storySongSemanticAnchors,
} from './songLanguage'
import {
  directorResultDetails,
  directorRunProvenance,
} from './provenance'
import {
  buildMusicVideoProduction,
  validateMusicVideoStaging,
} from './musicWorkflowState'
import { clampStoryMusicDuration, resolveStoryMusicModel } from './musicModel'
import type {
  ApplyStoryProposalCommand,
  ApproveStorySectionCommand,
  ApproveStoryVisualsCommand,
  ConfigureStorySongCommand,
  CreateStoryCommand,
  GenerateStorySectionCommand,
  GenerateStorySongCommand,
  GenerateStoryVisualsCommand,
  StageStoryComicCommand,
  StageStoryMusicVideoCommand,
  StageStoryVideoCommand,
  StartDirectorProductionCommand,
  UpdateStoryCommand,
} from './commands'

function storyResult(
  workspaceId: string,
  story: { id: string; title: string },
  section: string,
  message: string,
  extra: Record<string, unknown> = {},
): CommandResult {
  const entity = { kind: 'story', id: story.id, workspaceId }
  return commandResultFromSlice({
    entity,
    taskIds: typeof extra.taskId === 'string' && extra.taskId ? [extra.taskId] : undefined,
    pipelineIds: typeof extra.pipelineId === 'string' && extra.pipelineId ? [extra.pipelineId] : undefined,
    navigationTarget: {
      destination: extra.destination === 'director' || extra.destination === 'comics'
        ? extra.destination
        : 'story_lab',
      section,
      entity,
    },
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'story:reply',
      metadata: { summary: message, title: story.title, ...extra },
    }],
  })
}

function resolveStoryProject(
  projects: Record<string, import('./types').StoryProject>,
  current: import('./types').StoryProject,
  targetStoryId = '',
  targetStoryTitle = '',
): import('./types').StoryProject {
  const exactId = targetStoryId.trim()
  if (exactId) {
    const project = projects[exactId]
    if (!project) throw new Error(i18n.t('storyLab:errors.storyMissingById', { id: exactId }))
    if (targetStoryTitle && normalizeName(project.title) !== normalizeName(targetStoryTitle)) {
      throw new Error(i18n.t('storyLab:errors.storyRenamed', { id: exactId, title: project.title }))
    }
    return project
  }
  if (!targetStoryTitle) return current
  const matches = Object.values(projects).filter(item => normalizeName(item.title) === normalizeName(targetStoryTitle))
  if (matches.length > 1) throw new Error(i18n.t('storyLab:errors.duplicateStories', { title: targetStoryTitle }))
  if (!matches[0]) throw new Error(i18n.t('storyLab:errors.storyMissingInFolder', { title: targetStoryTitle }))
  return matches[0]
}

async function saveActiveStoryProjectMutation(
  workspace: string,
  current: { libraryRevision: number; projects: Record<string, import('./types').StoryProject> },
  projectId: string,
  mutate: (project: import('./types').StoryProject) => import('./types').StoryProject,
): Promise<import('./types').StoryProject> {
  const { saveStoryProjectMutation } = await import('./store')
  return saveStoryProjectMutation(workspace, current, projectId, mutate)
}

export async function configureStorySong(action: ConfigureStorySongCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { songWriteTarget }, { resolveStoryWritingProvider }, api] = await Promise.all([
    import('./store'), import('./musicModel'), import('./provider'), import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error(i18n.t('storyLab:errors.conflictBeforeEditSong'))
  const found = resolveStoryProject(current.projects, current.project, action.targetStoryId, action.targetStoryTitle)
  const targetBase = found.projectType === 'music_video'
    ? applyMusicVideoDirectVideoDefaults(found)
    : applyMusicVideoDirectVideoDefaults({
      ...found,
      projectType: 'music_video',
      musicVideoGenerationMode: 'direct_video',
    })
  const target = normalizeStoryProject(applyStoryLanguageIntent(targetBase, action.languageIntent, {
    technicalPromptLanguage: 'en',
  }))
  const languageIntent = target.languageIntent
  if (current.activeProjectOperations[target.id]) throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  const lyricsLanguage = resolveStorySongLanguage(action.lyricsLanguage, languageIntent, target.language)
  const protectedLyrics = protectedSongLyrics(languageIntent)
  const model = resolveStoryMusicModel(
    action.model,
    target.music.model,
    useStore.getState().models.map(item => ({
      model_type: item.model_type,
      family: item.family,
      is_downloaded: item.is_downloaded,
    })),
  )
  const durationSeconds = clampStoryMusicDuration(
    boundedDuration(action.durationSeconds, target.music.targetDurationSeconds),
    model,
  )
  const brief = action.brief.trim() || target.music.brief || target.creativeBrief.songStory || target.premise
  const semanticAnchors = storySongSemanticAnchors({
    premise: target.premise, theme: target.theme, songStory: target.creativeBrief.songStory, brief,
  })
  let style = action.style.trim()
  let lyrics = action.instrumental ? '' : action.lyrics.trim()
  let lyriaPrompt = ''
  if (!action.instrumental && !lyrics && action.writeLyrics) {
    const writing = resolveStoryWritingProvider(useStore.getState().productionProfile, target)
    const written = await api.writeSong(buildStorySongWritingRequest({
      target, brief, style, lyricsLanguage, protectedLyrics, model,
      targetProvider: songWriteTarget(model), durationSeconds,
      writingProvider: writing.provider, writingModel: writing.model, writingBaseUrl: writing.baseUrl,
    }))
    style = written.style.trim() || style
    lyrics = written.lyrics.trim()
    lyriaPrompt = written.lyria_prompt.trim()
    // Keep one high-signal subject anchor as a deterministic guard. The
    // writer may use valid synonyms for the remaining brief terms, so
    // requiring every extracted word would reject good creative lyrics.
    assertStorySongFidelity(lyrics, lyricsLanguage, semanticAnchors.slice(0, 1), protectedLyrics)
  }
  if (!action.instrumental && !lyrics) throw new Error(i18n.t('storyLab:errors.composerNoLyrics'))
  const existing = target.music.cues.find(item => item.kind === 'story')
  const cueTitle = action.songTitle.trim() || existing?.title || `${target.title} · ${i18n.t('storyLab:scaffold.songSuffix', { lng: scaffoldLanguage(target.language) })}`
  const cueId = existing?.id || storyId('music-cue')
  const project = await saveActiveStoryProjectMutation(workspace, current, target.id, source => {
    const latestTarget = source.projectType === 'music_video'
      ? applyMusicVideoDirectVideoDefaults(source)
      : applyMusicVideoDirectVideoDefaults({
        ...source,
        projectType: 'music_video',
        musicVideoGenerationMode: 'direct_video',
      })
    const latestExisting = latestTarget.music.cues.find(item => item.id === cueId)
      || latestTarget.music.cues.find(item => item.kind === 'story')
    const cue = {
      id: latestExisting?.id || cueId,
      kind: 'story' as const,
      targetId: latestTarget.id,
      title: cueTitle,
      purpose: brief,
      referenceSong: latestExisting?.referenceSong || '',
      brief,
      style,
      lyrics,
      lyricsLanguage,
      lyriaPrompt: lyriaPrompt || latestExisting?.lyriaPrompt || '',
      instrumental: action.instrumental,
      durationSeconds,
      candidates: latestExisting?.candidates || [],
      selectedCandidateId: undefined,
    }
    const cues = latestExisting
      ? latestTarget.music.cues.map(item => item.id === latestExisting.id ? cue : item)
      : [cue, ...latestTarget.music.cues]
    return normalizeStoryProject({
      ...latestTarget,
      language: languageIntent.contentLanguage || latestTarget.language,
      spokenLanguage: languageIntent.spokenLanguage || latestTarget.spokenLanguage,
      languageIntent: mergeLanguageIntent(latestTarget.languageIntent, languageIntent),
      revision: latestTarget.revision + 1,
      creativeBrief: {
        ...latestTarget.creativeBrief,
        musicStyle: cue.style,
        songStory: cue.purpose,
        durationSeconds: cue.durationSeconds,
      },
      music: {
        ...latestTarget.music,
        mode: 'original',
        model,
        brief: cue.brief,
        style: cue.style,
        lyrics: cue.lyrics,
        lyricsLanguage: cue.lyricsLanguage,
        targetDurationSeconds: cue.durationSeconds,
        cues,
        selectedCandidateId: undefined,
      },
      updatedAt: new Date().toISOString(),
    })
  })
  const savedCue = project.music.cues.find(item => item.id === cueId)
    || project.music.cues.find(item => item.kind === 'story')
  if (!savedCue) throw new Error(i18n.t('storyLab:errors.songSheetMissingCue'))
  const songMode = savedCue.instrumental
    ? i18n.t('storyLab:replies.modeInstrumental')
    : i18n.t('storyLab:replies.modeVocal')
  return storyResult(
    workspace,
    project,
    'music',
    i18n.t('storyLab:replies.songConfigured', {
      title: savedCue.title,
      model: project.music.model,
      mode: songMode,
      language: savedCue.lyricsLanguage,
    }),
    { projectId: project.id, cueId: savedCue.id, cueTitle: savedCue.title },
  )
}

export async function generateStorySong(action: GenerateStorySongCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmGenerateSong'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore }, { isLocalMusicModel }, { generateStoryCueSong }] = await Promise.all([
    import('./store'), import('./musicModel'), import('./storySongGeneration'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error(i18n.t('storyLab:errors.conflictBeforeGenerateSong'))
  const target = resolveStoryProject(current.projects, current.project, action.targetStoryId, action.targetStoryTitle)
  const exactCue = action.cueId
    ? target.music.cues.find(item => item.id === action.cueId)
    : action.cueTitle
      ? target.music.cues.find(item => normalizeName(item.title) === normalizeName(action.cueTitle))
      : undefined
  if (action.cueId && !exactCue) throw new Error(i18n.t('storyLab:errors.cueMissingById', { cueId: action.cueId, title: target.title }))
  // Once a cue title is supplied it is an explicit identity, not a hint. A
  // stale title must fail instead of silently selecting the only cue. The
  // compound Wizard runtime supplies cueId after configure_story_song, while
  // direct callers can still use the exact persisted title.
  const cue = exactCue
    || (!action.cueTitle
      ? (target.music.cues.length === 1 ? target.music.cues[0] : undefined)
        || target.music.cues.find(item => item.kind === 'story')
      : undefined)
  if (!cue) {
    const cueName = action.cueTitle || i18n.t('storyLab:errors.primaryCue')
    throw new Error(i18n.t('storyLab:errors.songMissingByName', { name: cueName, title: target.title }))
  }
  if (!isLocalMusicModel(target.music.model)) {
    throw new Error(i18n.t('storyLab:errors.needsLocalMusicModel'))
  }
  if (current.activeProjectOperations[target.id]) throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    const generated = await generateStoryCueSong({
      workspace,
      projectId: target.id,
      cueId: cue.id,
      actor: 'wizard',
      capability: 'generate_story_song',
    })
    const savedCue = generated.project.music.cues.find(item => item.id === cue.id)
    if (!savedCue) throw new Error(i18n.t('storyLab:errors.songSavedWithoutCue'))
    const engine = target.music.model === 'minimax_music3' ? 'MiniMax Music 3 local' : 'ACE-Step'
    return storyResult(
      workspace,
      generated.project,
      'music',
      i18n.t('storyLab:replies.songGenerated', {
        engine,
        title: savedCue.title,
        version: generated.version,
      }),
      {
        projectId: generated.project.id,
        cueId: savedCue.id,
        candidateId: generated.candidateId,
        songVersion: generated.version,
        taskId: generated.taskId,
        rootTaskId: generated.rootTaskId,
        jobId: generated.jobId,
        provenance: generated.candidate.provenance,
        cueTitle: savedCue.title,
        outputName: generated.filename,
      },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function createFilledStory(action: CreateStoryCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, createStoryProject, normalizeStoryProject, storyId }, api] = await Promise.all([
    import('./store'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeCreate'))
  }

  const sameTitle = Object.values(current.projects).find(project => (
    normalizeName(project.title) === normalizeName(action.title)
  ))
  const duplicate = Object.values(current.projects).find(project => (
    normalizeName(project.title) === normalizeName(action.title)
    && normalizeName(project.premise) === normalizeName(action.premise)
  ))
  if (action.projectType === 'music_video' && sameTitle?.projectType === 'music_video') {
    useStoryStore.setState({ project: sameTitle, dirty: false })
    return storyResult(
      workspace,
      sameTitle,
      'overview',
      i18n.t('storyLab:replies.musicVideoAlreadyOpen', { title: sameTitle.title }),
    )
  }
  if (duplicate && !(action.projectType === 'music_video' && duplicate.projectType !== 'music_video')) {
    useStoryStore.setState({ project: duplicate, dirty: false })
    return storyResult(
      workspace,
      duplicate,
      'overview',
      i18n.t('storyLab:replies.storyAlreadyOpen', { title: duplicate.title }),
    )
  }

  const base = createStoryProject(action.projectType || 'full_story')
  const languageIntent = seedStoryLanguageIntent(base, action.language, action.languageIntent).languageIntent
  const resolvedVisualStyle = resolveMusicVideoVisualStyle(
    action.projectType || 'full_story',
    action.visualStyle,
    action.creativeBrief,
  )
  const authoredLanguage = languageIntent.contentLanguage || action.language || base.language
  const authoredSpoken = languageIntent.spokenLanguage || action.language || base.spokenLanguage
  const lng = scaffoldLanguage(authoredLanguage)
  const roleLead = i18n.t('storyLab:scaffold.roleLead', { lng })
  const roleSupport = i18n.t('storyLab:scaffold.roleSupport', { lng })
  const characters = creativeCharacters(action.characters, authoredLanguage).map((character, index) => ({
    id: storyId('character'),
    name: character.name || i18n.t('storyLab:scaffold.characterName', { lng, index: index + 1 }),
    role: character.role || (index ? roleSupport : roleLead),
    age: '', pronouns: '',
    personality: character.personality,
    desire: character.desire,
    need: i18n.t('storyLab:scaffold.need', {
      lng,
      desire: character.desire || i18n.t('storyLab:scaffold.needDesire', { lng }),
    }),
    flaw: character.flaw,
    conflict: action.premise,
    arc: action.ending || i18n.t('storyLab:scaffold.arc', { lng }),
    voice: character.voice,
    appearance: character.appearance,
    wardrobe: i18n.t('storyLab:scaffold.wardrobe', { lng }),
    visualPrompt: `${character.appearance}. ${resolvedVisualStyle}`.trim(),
    negativePrompt: 'inconsistent identity, duplicate character, unreadable face',
    referenceAssetIds: [], approval: 'draft' as const,
  }))
  const locations = creativeLocations(action.locations, authoredLanguage).map((location, index) => ({
    id: storyId('location'),
    name: location.name || i18n.t('storyLab:scaffold.locationName', { lng, index: index + 1 }),
    purpose: location.purpose,
    description: location.description,
    visualPrompt: `${location.description}. ${resolvedVisualStyle}`.trim(),
    negativePrompt: 'inconsistent layout, unreadable signage, visual clutter',
    referenceAssetIds: [],
  }))
  const beats = outlineBeats(action.outlineBeats, action.premise, action.ending, authoredLanguage).map((beat, index, all) => ({
    id: storyId('beat'),
    stage: index === 0
      ? i18n.t('storyLab:scaffold.stageOpening', { lng })
      : index === all.length - 1
        ? i18n.t('storyLab:scaffold.stageResolution', { lng })
        : i18n.t('storyLab:scaffold.stageDevelopment', { lng, index }),
    title: `Beat ${index + 1}`,
    summary: beat,
    goal: index === all.length - 1
      ? i18n.t('storyLab:scaffold.beatGoalClose', { lng })
      : i18n.t('storyLab:scaffold.beatGoalAdvance', { lng }),
    conflict: index === 0 ? action.premise : i18n.t('storyLab:scaffold.beatConflict', { lng }),
    turn: index === all.length - 1 ? action.ending || beat : i18n.t('storyLab:scaffold.beatTurn', { lng }),
  }))
  const reuseId = action.projectType === 'music_video' && sameTitle && sameTitle.projectType !== 'music_video'
    ? sameTitle.id
    : undefined
  let project = normalizeStoryProject({
    ...base,
    id: reuseId || base.id,
    title: action.title,
    projectType: action.projectType || 'full_story',
    creativeBrief: {
      ...base.creativeBrief,
      generalIdea: action.creativeBrief || action.premise,
      context: action.synopsis,
      subjects: characters.map(character => character.name).join(', '),
      setting: locations.map(location => location.name).join(', '),
      action: action.ending || action.premise,
      durationSeconds: boundedDuration(action.durationSeconds, 90),
    },
    language: authoredLanguage,
    spokenLanguage: authoredSpoken,
    languageIntent,
    genre: action.genre || i18n.t('storyLab:scaffold.genre', { lng }),
    tone: action.tone || i18n.t('storyLab:scaffold.tone', { lng }),
    visualStyle: resolvedVisualStyle || i18n.t('storyLab:scaffold.visualStyle', { lng }),
    characterVisualStyle: resolvedVisualStyle || i18n.t('storyLab:scaffold.characterVisualStyle', { lng }),
    premise: action.premise,
    logline: action.logline,
    synopsis: action.synopsis || action.premise,
    theme: action.theme,
    ending: action.ending,
    world: {
      ...base.world,
      summary: action.worldSummary || action.synopsis || action.premise,
      period: i18n.t('storyLab:scaffold.period', { lng }),
      geography: locations.map(location => location.name).join(', '),
      society: i18n.t('storyLab:scaffold.society', { lng }),
      technology: i18n.t('storyLab:scaffold.technology', { lng }),
      rules: [i18n.t('storyLab:scaffold.ruleContinuity', { lng })],
      visualLanguage: resolvedVisualStyle || i18n.t('storyLab:scaffold.visualLanguage', { lng }),
      visualPrompt: resolvedVisualStyle,
      negativePrompt: 'continuity errors, inconsistent characters, unreadable composition',
      locations,
    },
    characters,
    relationships: characters.length > 1 ? [{
      id: storyId('relationship'),
      fromCharacterId: characters[0].id,
      toCharacterId: characters[1].id,
      label: i18n.t('storyLab:scaffold.relationshipLabel', { lng }),
      dynamic: i18n.t('storyLab:scaffold.relationshipDynamic', { lng }),
      evolution: i18n.t('storyLab:scaffold.relationshipEvolution', { lng }),
    }] : [],
    beats,
    updatedAt: new Date().toISOString(),
  })
  if (project.projectType === 'music_video') {
    project = applyMusicVideoDirectVideoDefaults({
      ...project,
      musicVideoGenerationMode: 'direct_video',
    })
  }

  const library = await api.saveStoryLibrary(workspace, {
    version: 2,
    revision: current.libraryRevision,
    activeId: project.id,
    projects: { ...current.projects, [project.id]: project },
  })
  useStoryStore.setState({
    workspace,
    project: library.projects[project.id],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  await useStoryStore.getState().loadWorkspace(workspace)
  return storyResult(
    workspace,
    project,
    'overview',
    i18n.t('storyLab:replies.storyCreated', { title: project.title, characters: characters.length, locations: locations.length, beats: beats.length }),
  )
}

export async function updateFilledStory(action: UpdateStoryCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { changedSections }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeEditStory'))
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(project => normalizeName(project.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) {
    throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  }
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyActiveOperationBeforeCanon', { title: target.title }))
  }

  const candidate = structuredClone(target)
  if (action.title) candidate.title = action.title
  if (action.creativeBrief) candidate.creativeBrief.generalIdea = action.creativeBrief
  if (action.durationSeconds !== undefined) candidate.creativeBrief.durationSeconds = action.durationSeconds
  if (action.premise) candidate.premise = action.premise
  if (action.logline) candidate.logline = action.logline
  if (action.synopsis) candidate.synopsis = action.synopsis
  if (action.theme) candidate.theme = action.theme
  if (action.ending) candidate.ending = action.ending
  if (action.genre) candidate.genre = action.genre
  if (action.tone) candidate.tone = action.tone
  if (action.visualStyle) candidate.visualStyle = action.visualStyle
  if (action.worldSummary) candidate.world.summary = action.worldSummary
  if (action.language) Object.assign(candidate, applyLegacyStoryLanguage(candidate, action.language, action.languageIntent))
  if (action.languageIntent) {
    Object.assign(candidate, applyStoryLanguageIntent(candidate, action.languageIntent))
  }

  const lng = scaffoldLanguage(candidate.language)
  action.characters.forEach(character => {
    const index = candidate.characters.findIndex(item => normalizeName(item.name) === normalizeName(character.name))
    const existing = index >= 0 ? candidate.characters[index] : null
    const patched = {
      id: existing?.id || storyId('character'),
      name: character.name,
      role: character.role || existing?.role || i18n.t('storyLab:scaffold.roleUnspecified', { lng }),
      age: existing?.age || '',
      pronouns: existing?.pronouns || '',
      personality: character.personality || existing?.personality || '',
      desire: character.desire || existing?.desire || '',
      need: existing?.need || '',
      flaw: character.flaw || existing?.flaw || '',
      conflict: existing?.conflict || candidate.premise,
      arc: existing?.arc || candidate.ending,
      voice: character.voice || existing?.voice || '',
      appearance: character.appearance || existing?.appearance || '',
      wardrobe: existing?.wardrobe || '',
      visualPrompt: character.appearance
        ? `${character.appearance}. ${candidate.visualStyle}`.trim()
        : existing?.visualPrompt || '',
      negativePrompt: existing?.negativePrompt || 'inconsistent identity, duplicate character, unreadable face',
      referenceAssetIds: existing?.referenceAssetIds || [],
      primaryReferenceAssetId: existing?.primaryReferenceAssetId,
      approval: 'draft' as const,
    }
    if (index >= 0) candidate.characters[index] = patched
    else candidate.characters.push(patched)
  })

  action.locations.forEach(location => {
    const index = candidate.world.locations.findIndex(item => normalizeName(item.name) === normalizeName(location.name))
    const existing = index >= 0 ? candidate.world.locations[index] : null
    const patched = {
      id: existing?.id || storyId('location'),
      name: location.name,
      purpose: location.purpose || existing?.purpose || '',
      description: location.description || existing?.description || '',
      visualPrompt: location.description
        ? `${location.description}. ${candidate.visualStyle}`.trim()
        : existing?.visualPrompt || '',
      negativePrompt: existing?.negativePrompt || 'inconsistent layout, unreadable signage, visual clutter',
      referenceAssetIds: existing?.referenceAssetIds || [],
    }
    if (index >= 0) candidate.world.locations[index] = patched
    else candidate.world.locations.push(patched)
  })

  if (action.outlineBeats.length) {
    candidate.beats = action.outlineBeats.map((summary, index, all) => ({
      id: storyId('beat'),
      stage: index === 0
        ? i18n.t('storyLab:scaffold.stageOpening', { lng })
        : index === all.length - 1
          ? i18n.t('storyLab:scaffold.stageResolution', { lng })
          : i18n.t('storyLab:scaffold.stageDevelopment', { index, lng }),
      title: `Beat ${index + 1}`,
      summary,
      goal: index === all.length - 1
        ? i18n.t('storyLab:scaffold.beatGoalClose', { lng })
        : i18n.t('storyLab:scaffold.beatGoalAdvance', { lng }),
      conflict: index === 0 ? candidate.premise : i18n.t('storyLab:scaffold.beatConflict', { lng }),
      turn: index === all.length - 1 ? candidate.ending || summary : i18n.t('storyLab:scaffold.beatTurn', { lng }),
    }))
  }

  const normalized = normalizeStoryProject(candidate)
  const sections = changedSections(target, normalized)
  if (!sections.length) throw new Error(i18n.t('storyLab:errors.requestChangesNothing', { title: target.title }))
  const approvals = { ...normalized.approvals }
  const sectionVersions = { ...target.sectionVersions }
  sections.forEach(section => {
    sectionVersions[section] += 1
    delete approvals[section]
  })
  const project = normalizeStoryProject({
    ...normalized,
    revision: target.revision + 1,
    sectionVersions,
    approvals,
    updatedAt: new Date().toISOString(),
  })
  const library = await api.saveStoryLibrary(workspace, {
    version: 2,
    revision: current.libraryRevision,
    activeId: project.id,
    projects: { ...current.projects, [project.id]: project },
  })
  useStoryStore.setState({
    workspace,
    project: library.projects[project.id],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  await useStoryStore.getState().loadWorkspace(workspace)
  const section = sections.includes('structure')
    ? 'structure'
    : sections.includes('characters')
      ? 'characters'
      : sections.includes('world')
        ? 'world'
        : 'overview'
  return storyResult(
    workspace,
    project,
    section,
    i18n.t('storyLab:replies.storyUpdated', { title: project.title, sections: sections.join(', '), section }),
  )
}

export async function generateStorySectionDraft(
  action: GenerateStorySectionCommand,
  onStep?: (message: string) => void,
): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmGenerateProposal'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { resolveStoryWritingProvider }, api] = await Promise.all([
    import('./store'),
    import('./provider'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeProposal'))
  }
  const storedProject = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!storedProject) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  if (current.activeProjectOperations[storedProject.id]) {
    throw new Error(i18n.t('storyLab:errors.storyAlreadyActiveOperation', { title: storedProject.title }))
  }
  const premise = storedProject.premise.trim()
    || storedProject.creativeBrief.generalIdea.trim()
    || storedProject.logline.trim()
    || storedProject.synopsis.trim()
  if (!premise) throw new Error(i18n.t('storyLab:errors.needsPremiseOrBrief', { title: storedProject.title }))
  let project = storedProject
  if (action.languageIntent) {
    const intended = mergeLanguageIntent(storedProject.languageIntent, action.languageIntent, {
      contentLanguage: storedProject.language,
      spokenLanguage: storedProject.spokenLanguage,
    })
    const intendedLanguage = intended.contentLanguage || storedProject.language
    const intendedSpokenLanguage = intended.spokenLanguage || storedProject.spokenLanguage
    if (
      JSON.stringify(intended) !== JSON.stringify(storedProject.languageIntent)
      || intendedLanguage !== storedProject.language
      || intendedSpokenLanguage !== storedProject.spokenLanguage
    ) {
      project = await saveActiveStoryProjectMutation(workspace, current, storedProject.id, source => {
        const intendedSource = applyStoryLanguageIntent(source, action.languageIntent)
        const approvals = { ...source.approvals }
        delete approvals.overview
        return normalizeStoryProject({
          ...intendedSource,
          revision: source.revision + 1,
          sectionVersions: {
            ...source.sectionVersions,
            overview: source.sectionVersions.overview + 1,
          },
          approvals,
          updatedAt: new Date().toISOString(),
        })
      })
    }
  }
  useStoryStore.setState({ project, dirty: false })
  const visibleSection = action.scope === 'all' ? 'overview' : action.scope
  const resultKey = storyResultKey(workspace, project.id)
  const jobKey = storyJobKey(workspace, project.id)
  window.localStorage.setItem(resultKey, JSON.stringify({
    scope: action.scope,
    generateImagesAfterApply: false,
  }))
  useStoryStore.getState().beginProjectOperation(project.id)
  try {
    const resolvedWriting = resolveStoryWritingProvider(useStore.getState().productionProfile, project)
    const effectiveProvider = project.provider.useGlobalProfile
      ? {
          ...project.provider,
          writingProvider: resolvedWriting.provider,
          writingModel: resolvedWriting.model,
          writingBaseUrl: resolvedWriting.baseUrl,
          imageProvider: useStore.getState().productionProfile.image.provider === 'minimax' ? 'minimax' as const : 'maestro' as const,
          imageModel: useStore.getState().productionProfile.image.model,
        }
      : project.provider
    let jobId = ''
    const { result } = await api.generateStorySection({
      scope: action.scope,
      premise,
      language: project.language,
      genre: project.genre,
      tone: project.tone,
      audience: project.audience,
      instruction: compileProviderPrompt(action.instruction, project.languageIntent, { medium: 'story' }),
      project: { ...project, provider: effectiveProvider },
      writingProvider: effectiveProvider.writingProvider,
      writingModel: effectiveProvider.writingModel,
      writingBaseUrl: effectiveProvider.writingBaseUrl,
      workspace,
    }, progress => {
      jobId = progress.jobId
      window.localStorage.setItem(jobKey, progress.jobId)
      const count = progress.total ? ` ${progress.current}/${progress.total}` : ''
      onStep?.(`${progress.message}${count}`)
    })
    window.localStorage.setItem(resultKey, JSON.stringify({
      jobId,
      scope: action.scope,
      result,
      generateImagesAfterApply: false,
    }))
    return storyResult(
      workspace,
      project,
      visibleSection,
      i18n.t('storyLab:replies.proposalReady', { scope: action.scope, title: project.title }),
      { notifyDraft: true },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(project.id)
  }
}

export async function applyStoredStoryProposal(action: ApplyStoryProposalCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmApplyProposal'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { changedSections, normalizeStoryCharacter }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeApply'))
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  }
  const resultKey = storyResultKey(workspace, target.id)
  const jobKey = storyJobKey(workspace, target.id)
  let saved: { scope?: unknown; result?: unknown } | null = null
  try {
    saved = JSON.parse(window.localStorage.getItem(resultKey) || 'null')
  } catch {
    throw new Error(i18n.t('storyLab:errors.proposalDamaged', { title: target.title }))
  }
  if (!saved?.result || typeof saved.result !== 'object' || Array.isArray(saved.result)) {
    throw new Error(i18n.t('storyLab:errors.proposalMissing', { title: target.title }))
  }
  const result = saved.result as Record<string, unknown>
  const candidate = structuredClone(target)
  const overview = result.overview && typeof result.overview === 'object' && !Array.isArray(result.overview)
    ? result.overview as Record<string, unknown>
    : null
  if (overview) {
    const overviewFields = [
      'title', 'language', 'spokenLanguage', 'genre', 'tone', 'audience',
      'visualStyle', 'characterVisualStyle', 'premise', 'logline', 'synopsis', 'theme', 'ending',
    ] as const
    overviewFields.forEach(field => {
      const value = overview[field]
      if (typeof value === 'string') {
        ;(candidate as unknown as Record<string, unknown>)[field] = value
      }
    })
    if (overview.creativeBrief && typeof overview.creativeBrief === 'object' && !Array.isArray(overview.creativeBrief)) {
      const brief = overview.creativeBrief as Record<string, unknown>
      Object.keys(candidate.creativeBrief).forEach(field => {
        const value = brief[field]
        if (typeof value === 'string' || typeof value === 'number') {
          ;(candidate.creativeBrief as unknown as Record<string, unknown>)[field] = value
        }
      })
    }
  }

  const generatedWorld = result.world && typeof result.world === 'object' && !Array.isArray(result.world)
    ? result.world as Record<string, unknown>
    : null
  if (generatedWorld) {
    const worldFields = ['summary', 'period', 'geography', 'society', 'technology', 'visualLanguage', 'visualPrompt', 'negativePrompt'] as const
    worldFields.forEach(field => {
      if (typeof generatedWorld[field] === 'string') candidate.world[field] = generatedWorld[field]
    })
    if (Array.isArray(generatedWorld.rules)) {
      candidate.world.rules = generatedWorld.rules.filter((item): item is string => typeof item === 'string')
    }
    if (Array.isArray(generatedWorld.locations)) {
      candidate.world.locations = generatedWorld.locations.map((value, index) => {
        const raw = value && typeof value === 'object' && !Array.isArray(value)
          ? value as Record<string, unknown> : {}
        const name = typeof raw.name === 'string'
          ? raw.name
          : i18n.t('storyLab:scaffold.locationName', { index: index + 1, lng: scaffoldLanguage(candidate.language) })
        const existing = target.world.locations.find(item => (
          item.id === raw.id || normalizeName(item.name) === normalizeName(name)
        ))
        return {
          id: existing?.id || (typeof raw.id === 'string' && raw.id ? raw.id : storyId('location')),
          name,
          purpose: typeof raw.purpose === 'string' ? raw.purpose : '',
          description: typeof raw.description === 'string' ? raw.description : '',
          visualPrompt: typeof raw.visualPrompt === 'string' ? raw.visualPrompt : '',
          negativePrompt: typeof raw.negativePrompt === 'string' ? raw.negativePrompt : '',
          referenceAssetIds: existing?.referenceAssetIds || [],
        }
      })
    }
  }

  const characterIdMap = new Map<string, string>()
  if (Array.isArray(result.characters)) {
    candidate.characters = result.characters.map((value, index) => {
      const generated = normalizeStoryCharacter(value, index)
      const existing = target.characters.find(item => (
        item.id === generated.id || normalizeName(item.name) === normalizeName(generated.name)
      ))
      if (generated.id) characterIdMap.set(generated.id, existing?.id || generated.id)
      return {
        ...generated,
        id: existing?.id || generated.id || storyId('character'),
        referenceAssetIds: existing?.referenceAssetIds || [],
        primaryReferenceAssetId: existing?.primaryReferenceAssetId,
        approval: 'draft' as const,
      }
    })
  }
  if (Array.isArray(result.relationships)) {
    candidate.relationships = result.relationships.flatMap((value, index) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return []
      const raw = value as Record<string, unknown>
      const generatedId = typeof raw.id === 'string' ? raw.id : ''
      const existing = target.relationships.find(item => item.id === generatedId)
      return [{
        id: existing?.id || generatedId || storyId(`relationship-${index + 1}`),
        fromCharacterId: characterIdMap.get(String(raw.fromCharacterId || '')) || String(raw.fromCharacterId || ''),
        toCharacterId: characterIdMap.get(String(raw.toCharacterId || '')) || String(raw.toCharacterId || ''),
        label: typeof raw.label === 'string' ? raw.label : '',
        dynamic: typeof raw.dynamic === 'string' ? raw.dynamic : '',
        evolution: typeof raw.evolution === 'string' ? raw.evolution : '',
      }]
    })
  }
  const generatedStructure = Array.isArray(result.structure)
    ? result.structure
    : Array.isArray(result.beats) ? result.beats : null
  if (generatedStructure) {
    const normalizedStructure = normalizeStoryProject({ ...candidate, beats: generatedStructure }).beats
    candidate.beats = normalizedStructure.map(beat => {
      const existing = target.beats.find(item => (
        item.id === beat.id || (item.title && item.title === beat.title)
      ))
      return { ...beat, id: existing?.id || beat.id || storyId('beat') }
    })
  }

  const normalized = normalizeStoryProject(candidate)
  const sections = changedSections(target, normalized)
  if (!sections.length) throw new Error(i18n.t('storyLab:errors.proposalChangesNothing', { title: target.title }))
  const sectionVersions = { ...target.sectionVersions }
  const approvals = { ...normalized.approvals }
  sections.forEach(section => {
    sectionVersions[section] += 1
    delete approvals[section]
  })
  const project = normalizeStoryProject({
    ...normalized,
    revision: target.revision + 1,
    sectionVersions,
    approvals,
    updatedAt: new Date().toISOString(),
  })
  const library = await api.saveStoryLibrary(workspace, {
    version: 2,
    revision: current.libraryRevision,
    activeId: project.id,
    projects: { ...current.projects, [project.id]: project },
  })
  useStoryStore.setState({
    workspace,
    project: library.projects[project.id],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  window.localStorage.removeItem(resultKey)
  window.localStorage.removeItem(jobKey)
  await useStoryStore.getState().loadWorkspace(workspace)
  const reviewSections = new Set(['overview', 'world', 'characters', 'relationships', 'structure'])
  const visibleSection = typeof saved.scope === 'string' && reviewSections.has(saved.scope)
    ? saved.scope as 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
    : 'overview'
  return storyResult(
    workspace,
    project,
    visibleSection,
    i18n.t('storyLab:replies.proposalApplied', { title: project.title, sections: sections.join(', ') }),
    { notifyDraft: true },
  )
}

export async function approveStorySection(action: ApproveStorySectionCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmApproveSection'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { changedSections }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeApproveCanon'))
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  }

  if (action.section === 'overview' && (!target.premise.trim() || !target.logline.trim() || !target.synopsis.trim())) {
    throw new Error(i18n.t('storyLab:errors.overviewNeedsFields'))
  }
  if (action.section === 'world' && (!target.world.summary.trim() || !target.world.visualLanguage.trim())) {
    throw new Error(i18n.t('storyLab:errors.worldNeedsFields'))
  }
  const { storyRecipeRequiresVisualIdentities, storyVisualGuidanceMode } = await import('./storyVisualGuidance')
  const requiresVisualIdentities = storyRecipeRequiresVisualIdentities(storyVisualGuidanceMode(target))
  if (action.section === 'characters') {
    if (!target.characters.length) throw new Error(i18n.t('storyLab:errors.addCharacterBeforeCast'))
    if (requiresVisualIdentities) {
      const incomplete = target.characters.flatMap(character => {
        const reasons = [
          character.approval !== 'approved' ? i18n.t('storyLab:errors.reasonStillDraft') : '',
          !character.primaryReferenceAssetId ? i18n.t('storyLab:errors.reasonNoPrimary') : '',
          character.primaryReferenceAssetId
            && target.assets[character.primaryReferenceAssetId]?.approval !== 'approved'
            ? i18n.t('storyLab:errors.reasonUnapprovedPrimary') : '',
        ].filter(Boolean)
        const name = character.name || i18n.t('storyLab:errors.unnamedCharacter')
        return reasons.length ? [`${name} (${reasons.join(', ')})`] : []
      })
      if (incomplete.length) {
        throw new Error(i18n.t('storyLab:errors.cannotApproveCharacters', { details: incomplete.join(' · ') }))
      }
    }
  }
  if (action.section === 'relationships' && target.relationships.some(relationship => (
    !relationship.fromCharacterId
    || !relationship.toCharacterId
    || relationship.fromCharacterId === relationship.toCharacterId
    || !relationship.dynamic.trim()
  ))) {
    throw new Error(i18n.t('storyLab:errors.relationshipsNeedDynamic'))
  }
  if (action.section === 'structure' && (
    target.beats.length < 3
    || target.beats.some(beat => !beat.summary.trim() || !beat.conflict.trim() || !beat.turn.trim())
  )) {
    throw new Error(i18n.t('storyLab:errors.structureNeedsBeats'))
  }

  if (target.approvals[action.section]?.version === target.sectionVersions[action.section]) {
    return storyResult(
      workspace,
      target,
      action.section,
      i18n.t('storyLab:replies.sectionAlreadyApproved', { section: action.section, title: target.title }),
    )
  }
  const candidate = structuredClone(target)
  if (action.section === 'characters' && !requiresVisualIdentities) {
    candidate.characters = candidate.characters.map(character => ({ ...character, approval: 'approved' as const }))
  }
  const normalized = normalizeStoryProject(candidate)
  const changed = changedSections(target, normalized)
  const sectionVersions = { ...target.sectionVersions }
  changed.forEach(section => { sectionVersions[section] += 1 })
  const project = normalizeStoryProject({
    ...normalized,
    revision: target.revision + 1,
    sectionVersions,
    approvals: {
      ...normalized.approvals,
      [action.section]: {
        approvedAt: new Date().toISOString(),
        version: sectionVersions[action.section],
      },
    },
    updatedAt: new Date().toISOString(),
  })
  const library = await api.saveStoryLibrary(workspace, {
    version: 2,
    revision: current.libraryRevision,
    activeId: project.id,
    projects: { ...current.projects, [project.id]: project },
  })
  useStoryStore.setState({
    workspace,
    project: library.projects[project.id],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  await useStoryStore.getState().loadWorkspace(workspace)
  return storyResult(
    workspace,
    project,
    action.section,
    i18n.t('storyLab:replies.sectionApproved', { section: action.section, title: project.title }),
  )
}

export async function approveStoryVisuals(action: ApproveStoryVisualsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmApproveVisuals'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { changedSections }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeApproveVisuals'))
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  }

  const candidate = structuredClone(target)
  let changed = false
  const labels: string[] = []
  for (const selection of action.selections) {
    const assetMatches = Object.values(candidate.assets).filter(asset => normalizeName(asset.name) === normalizeName(selection.assetName))
    if (!assetMatches.length) throw new Error(i18n.t('storyLab:errors.assetMissing', { name: selection.assetName, title: target.title }))
    if (assetMatches.length > 1) throw new Error(i18n.t('storyLab:errors.duplicateAssets', { name: selection.assetName }))
    const asset = assetMatches[0]
    if (asset.approval !== 'approved') { asset.approval = 'approved'; changed = true }

    if (selection.targetKind === 'world') {
      if (selection.primary) throw new Error(i18n.t('storyLab:errors.primaryOnlyForCharacter'))
      if (!candidate.world.referenceAssetIds.includes(asset.id)) {
        candidate.world.referenceAssetIds.push(asset.id); changed = true
      }
      labels.push(`${asset.name} → ${i18n.t('storyLab:replies.worldLabel')}`)
      continue
    }

    if (selection.targetKind === 'location') {
      if (selection.primary) throw new Error(i18n.t('storyLab:errors.primaryOnlyForCharacter'))
      const matches = candidate.world.locations.filter(location => normalizeName(location.name) === normalizeName(selection.targetName))
      if (!matches.length) throw new Error(i18n.t('storyLab:errors.locationMissing', { name: selection.targetName, title: target.title }))
      if (matches.length > 1) throw new Error(i18n.t('storyLab:errors.duplicateLocations', { name: selection.targetName }))
      if (!matches[0].referenceAssetIds.includes(asset.id)) {
        matches[0].referenceAssetIds.push(asset.id); changed = true
      }
      labels.push(`${asset.name} → ${matches[0].name}`)
      continue
    }

    const matches = candidate.characters.filter(character => normalizeName(character.name) === normalizeName(selection.targetName))
    if (!matches.length) throw new Error(i18n.t('storyLab:errors.characterMissing', { name: selection.targetName, title: target.title }))
    if (matches.length > 1) throw new Error(i18n.t('storyLab:errors.duplicateCharacters', { name: selection.targetName }))
    const character = matches[0]
    if (!character.referenceAssetIds.includes(asset.id)) {
      character.referenceAssetIds.push(asset.id); changed = true
    }
    if (selection.primary || !character.primaryReferenceAssetId) {
      if (character.primaryReferenceAssetId !== asset.id) { character.primaryReferenceAssetId = asset.id; changed = true }
    }
    const primarySuffix = character.primaryReferenceAssetId === asset.id
      ? i18n.t('storyLab:replies.primarySuffix')
      : ''
    labels.push(`${asset.name} → ${character.name}${primarySuffix}`)
  }

  if (!changed) {
    useStoryStore.setState({ project: target, dirty: false })
    return storyResult(
      workspace,
      target,
      'assets',
      i18n.t('storyLab:replies.visualsAlreadyLinked', { title: target.title }),
    )
  }

  const normalized = normalizeStoryProject(candidate)
  const changedCanonSections = changedSections(target, normalized)
  const sectionVersions = { ...target.sectionVersions }
  const approvals = { ...normalized.approvals }
  changedCanonSections.forEach(section => {
    sectionVersions[section] += 1
    delete approvals[section]
  })
  const project = normalizeStoryProject({
    ...normalized,
    revision: target.revision + 1,
    sectionVersions,
    approvals,
    updatedAt: new Date().toISOString(),
  })
  const library = await api.saveStoryLibrary(workspace, {
    version: 2,
    revision: current.libraryRevision,
    activeId: project.id,
    projects: { ...current.projects, [project.id]: project },
  })
  useStoryStore.setState({
    workspace,
    project: library.projects[project.id],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  await useStoryStore.getState().loadWorkspace(workspace)
  return storyResult(
    workspace,
    project,
    'assets',
    i18n.t('storyLab:replies.referencesLinked', { count: labels.length, title: project.title, labels: labels.join(' · ') }),
  )
}

export async function generateStoryVisuals(action: GenerateStoryVisualsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmGenerateVisuals'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const { useStoryStore } = await import('./store')
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeImages'))
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyVisualOperationActive', { title: target.title }))
  }
  useStoryStore.setState({ project: target, dirty: false })
  return storyResult(
    workspace,
    target,
    'assets',
    i18n.t('storyLab:replies.willGenerateVisuals', { title: target.title }),
    {
      visualRequest: {
        projectId: target.id,
        scope: action.scope,
        targetNames: action.targetNames,
      },
    },
  )
}

export async function stageStoryComic(action: StageStoryComicCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmStageComic'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, { useComicStore }, api] = await Promise.all([
    import('./store'),
    import('./adaptations'),
    import('../comics/store'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error(i18n.t('storyLab:errors.conflictBeforeProduction'))
  }
  const storedTarget = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!storedTarget) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  const target = action.languageIntent
    ? normalizeStoryProject(applyStoryLanguageIntent(storedTarget, action.languageIntent))
    : storedTarget
  if (current.activeProjectOperations[target.id]) {
    throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  }
  if (!target.premise.trim() && !target.logline.trim() && !target.synopsis.trim()) {
    throw new Error(i18n.t('storyLab:errors.needsPremiseLoglineSynopsis', { title: target.title }))
  }

  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    const { comic, request } = adaptations.buildComicAdaptation(
      target,
      action.direction || adaptations.DEFAULT_COMIC_CHAPTER_DIRECTION,
      { pageCount: action.pageCount, panelsPerPage: action.panelsPerPage },
    )
    const production = {
      id: storyId('production'),
      kind: 'comic' as const,
      title: `${target.title} · comic chapter`,
      createdAt: new Date().toISOString(),
      sourceVersion: target.revision,
      sourceSnapshot: { ...structuredClone(target), productions: [] },
      targetId: comic.id,
      targetName: comic.title,
      targetSnapshot: {
        comic: structuredClone(comic) as unknown as Record<string, unknown>,
        request: structuredClone(request) as unknown as Record<string, unknown>,
      },
      status: 'staged' as const,
    }
    const project = normalizeStoryProject({
      ...target,
      revision: target.revision + 1,
      productions: [...target.productions, production],
      updatedAt: new Date().toISOString(),
    })
    const library = await api.saveStoryLibrary(workspace, {
      version: 2,
      revision: current.libraryRevision,
      activeId: project.id,
      projects: { ...current.projects, [project.id]: project },
    })
    useStoryStore.setState({
      workspace,
      project: library.projects[project.id],
      projects: library.projects,
      libraryRevision: library.revision,
      dirty: false,
      hydrated: false,
      loading: false,
      saveError: null,
      libraryConflicts: [],
    })
    await useStoryStore.getState().loadWorkspace(workspace)
    useComicStore.getState().setProject(comic)
    window.localStorage.removeItem('maestro-last-comic-plan-result')
    window.localStorage.removeItem('maestro-last-comic-plan-job')
    window.localStorage.removeItem('maestro-story-comic-auto-start')
    window.localStorage.setItem('maestro-story-comic-draft', JSON.stringify(request))
    window.dispatchEvent(new CustomEvent('maestro:comic-staged', { detail: request }))
    const app = useStore.getState()
    app.setSettingsOpen(false)
    app.setDashboardOpen(false)
    app.setMediaFilter('comics')
    app.setSidebarMode('director')
    app.setDirectorSkill('comic')
    app.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return storyResult(
      workspace,
      target,
      'overview',
      i18n.t('storyLab:replies.comicStaged', { title: comic.title, pages: action.pageCount, panels: action.panelsPerPage }),
      { destination: 'comics', comicId: comic.id, comicTitle: comic.title },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function stageStoryVideo(action: StageStoryVideoCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmStageVideo'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, api] = await Promise.all([
    import('./store'), import('./adaptations'), import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error(i18n.t('storyLab:errors.conflictBeforeProduction'))
  const storedTarget = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!storedTarget) throw new Error(i18n.t('storyLab:errors.storyMissingInWorkspace', { title: action.targetStoryTitle }))
  const target = action.languageIntent
    ? normalizeStoryProject(applyStoryLanguageIntent(storedTarget, action.languageIntent))
    : storedTarget
  if (current.activeProjectOperations[target.id]) throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))
  if (!target.synopsis.trim() || !target.characters.length) throw new Error(i18n.t('storyLab:errors.productionNeedsSynopsis'))
  const { assertStoryVisualRecipeReady } = await import('./storyVisualGuidance')
  assertStoryVisualRecipeReady(target)
  const duration = boundedDuration(
    action.durationSeconds,
    action.kind === 'trailer'
      ? target.productionRecipe.trailerDurationSeconds || target.creativeBrief.durationSeconds || 60
      : target.productionRecipe.filmDurationSeconds || target.creativeBrief.durationSeconds || 90,
  )
  const direction = action.direction || (action.kind === 'trailer' ? adaptations.DEFAULT_TRAILER_DIRECTION : adaptations.DEFAULT_SHORT_FILM_DIRECTION)
  const adaptation = action.kind === 'trailer'
    ? adaptations.buildTrailerAdaptation(target, direction, duration, {
        format: 'theatrical', narration: 'hybrid', spoiler: 'balanced', intensity: 'rising',
        tagline: target.logline, titleCards: false, preserveVisualStyle: true,
      })
    : adaptations.buildShortFilmAdaptation(target, direction, duration, { preserveVisualStyle: true })
  const title = `${target.title} · ${action.kind === 'trailer' ? 'epic trailer' : 'short episode'}`
  const production = {
    id: storyId('production'), kind: action.kind, title, createdAt: new Date().toISOString(),
    sourceVersion: target.revision, sourceSnapshot: { ...structuredClone(target), productions: [] },
    targetName: title,
    targetSnapshot: {
      direction, sceneDescription: adaptation.sceneDescription, characters: adaptation.characters,
      targetDuration: adaptation.targetDuration, narrative: adaptation.narrative,
      visualStyle: adaptation.visualStyle, preserveVisualStyle: adaptation.preserveVisualStyle,
      imageModel: target.provider.imageModel, videoModel: target.videoOverride.model,
      generationMode: target.musicVideoGenerationMode, resolution: target.videoOverride.resolution,
      aspectRatio: target.videoOverride.aspectRatio,
    },
    status: 'staged' as const,
  }
  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    const project = normalizeStoryProject({ ...target, revision: target.revision + 1, productions: [...target.productions, production], updatedAt: new Date().toISOString() })
    const library = await api.saveStoryLibrary(workspace, { version: 2, revision: current.libraryRevision, activeId: project.id, projects: { ...current.projects, [project.id]: project } })
    useStoryStore.setState({ workspace, project: library.projects[project.id], projects: library.projects, libraryRevision: library.revision, dirty: false, hydrated: false, loading: false, saveError: null, libraryConflicts: [] })
    await useStoryStore.getState().loadWorkspace(workspace)

    const director = useStore.getState()
    const directVideo = target.musicVideoGenerationMode === 'direct_video'
    const directReferences = target.musicVideoGenerationMode === 'direct_references'
    director.directorReset()
    director.setGenerationMode('video')
    if (!directVideo && !directReferences && target.provider.imageModel) director.selectDirectorImageModel(target.provider.imageModel)
    if (target.videoOverride.model) await director.selectDirectorVideoModel(target.videoOverride.model)
    director.setDirectorResolution(target.videoOverride.resolution)
    director.setDirectorAspectRatio(target.videoOverride.aspectRatio)
    director.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
    if (target.videoOverride.model.startsWith('minimax_h3')) director.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
    director.setSidebarMode('director')
    director.directorSetSceneDescription(adaptation.sceneDescription)
    director.setDirectorSkill('short_film')
    director.setDirectorMusicVideoTreatment({ generation_mode: directVideo ? 'direct_video' : 'image_guided', direct_video_master_prompt: target.directVideoMasterPrompt })
    director.shortFilmSetPath('story')
    director.shortFilmSetCharacters(adaptation.characters)
    director.shortFilmSetTargetDuration(adaptation.targetDuration)
    director.shortFilmSetNarrative(adaptation.narrative)
    director.shortFilmSetVisualStyle(directVideo ? '' : adaptation.visualStyle)
    director.shortFilmSetPreserveVisualStyle(directVideo ? false : adaptation.preserveVisualStyle)
    director.setDirectorCharacterVisualStyle(directVideo ? '' : target.characterVisualStyle)
    director.setDirectorAllowClipText(target.allowClipText)
    director.setDirectorSpokenLanguage(target.spokenLanguage)
    director.setDirectorAutoMode(false)
    useStore.setState({ directorWritingProvider: target.provider.writingProvider, directorWritingModel: target.provider.writingModel, directorWritingBaseUrl: target.provider.writingBaseUrl })
    for (const reference of directVideo ? [] : adaptation.characterReferences) {
      const asset = target.assets[reference.assetId]
      if (!asset) continue
      try {
        const response = await fetch(asset.source)
        if (!response.ok) continue
        const blob = await response.blob()
        director.directorAddCharacterRef(new File([blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' }))
        director.directorSetCharacterRefLabel(useStore.getState().directorCharacterRefs.length - 1, reference.label)
      } catch { /* The staged canon remains usable when an old reference disappeared. */ }
    }
    for (const reference of directVideo ? [] : adaptation.locationReferences) {
      const asset = target.assets[reference.assetId]
      if (!asset) continue
      try {
        const response = await fetch(asset.source)
        if (!response.ok) continue
        const blob = await response.blob()
        director.directorAddLocationRef(new File([blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' }))
        director.directorSetLocationRefLabel(useStore.getState().directorLocationRefs.length - 1, reference.label)
      } catch { /* Keep the written production even if a legacy asset is gone. */ }
    }
    useStore.setState({ directorStep: 'style' })
    useStore.setState({
      directorStoryProductionHandoff: {
        workspace,
        projectId: target.id,
        productionId: production.id,
      },
    })
    director.setMediaFilter('all')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return storyResult(
      workspace,
      target,
      'overview',
      i18n.t('storyLab:replies.videoStaged', { title, duration }),
      { destination: 'director', productionId: production.id },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function stageStoryMusicVideo(action: StageStoryMusicVideoCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmStageMusicVideo'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, api, selection] = await Promise.all([
    import('./store'),
    import('./adaptations'),
    import('../../api/client'),
    import('./musicVideoSelection'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error(i18n.t('storyLab:errors.conflictBeforeMusicVideo'))
  const stored = resolveStoryProject(current.projects, current.project, action.targetStoryId, action.targetStoryTitle)
  const found = action.languageIntent
    ? normalizeStoryProject(applyStoryLanguageIntent(stored, action.languageIntent))
    : stored
  if (current.activeProjectOperations[found.id]) throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: found.title }))
  const { cue, candidate } = selection.resolveStoryMusicSelection(
    found,
    action.songName,
    action.cueTitle,
    action.cueId,
    action.candidateId,
  )
  const resolvedCue = selection.effectiveStoryMusicCue(found, cue, candidate, action.cueId)
  const target = applyMusicVideoDirectVideoDefaults(found.projectType === 'music_video'
    ? found
    : { ...found, projectType: 'music_video', musicVideoGenerationMode: 'direct_video' })
  const adaptation = adaptations.buildMusicVideoAdaptation(target, resolvedCue, {
    generationMode: target.musicVideoGenerationMode,
  })
  const { directVideo, directReferences } = validateMusicVideoStaging(target, adaptation)
  const productionId = storyId('production')
  const production = buildMusicVideoProduction({
    id: productionId, project: target, cue: resolvedCue, candidate, adaptation,
    pacing: action.pacing, outputFolder: workspace,
  })

  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    const project = await saveActiveStoryProjectMutation(workspace, current, target.id, source => {
      const latestBase = applyMusicVideoDirectVideoDefaults(source.projectType === 'music_video'
        ? source
        : { ...source, projectType: 'music_video', musicVideoGenerationMode: 'direct_video' })
      const latestTarget = action.languageIntent
        ? normalizeStoryProject(applyStoryLanguageIntent(latestBase, action.languageIntent))
        : latestBase
      const latestCue = latestTarget.music.cues.find(item => item.id === resolvedCue.id)
      const latestCandidate = latestCue?.candidates.find(item => item.id === candidate.id)
      if (!latestCue || !latestCandidate) {
        throw new Error(i18n.t('storyLab:errors.songChangedWhileStaging'))
      }
      const latestResolvedCue = selection.effectiveStoryMusicCue(
        latestTarget, latestCue, latestCandidate, action.cueId,
      )
      const latestAdaptation = adaptations.buildMusicVideoAdaptation(latestTarget, latestResolvedCue, {
        generationMode: latestTarget.musicVideoGenerationMode,
      })
      const reconciledProduction = buildMusicVideoProduction({
        id: productionId, createdAt: production.createdAt, project: latestTarget,
        cue: latestResolvedCue, candidate: latestCandidate, adaptation: latestAdaptation,
        pacing: action.pacing, outputFolder: workspace,
      })
      return normalizeStoryProject({
        ...latestTarget,
        revision: latestTarget.revision + 1,
        productions: [...latestTarget.productions, reconciledProduction],
        updatedAt: new Date().toISOString(),
      })
    })

    const director = useStore.getState()
    director.directorReset()
    director.setGenerationMode('video')
    if (!directVideo && !directReferences && target.provider.imageModel) director.selectDirectorImageModel(target.provider.imageModel)
    if (target.videoOverride.model) {
      await director.selectDirectorVideoModel(target.videoOverride.model)
      const selected = useStore.getState().selectedModelPerMode.video
      if (selected !== target.videoOverride.model) {
        const selectedModel = selected || i18n.t('storyLab:errors.emptyModel')
        throw new Error(i18n.t('storyLab:errors.videoModelNotApplied', {
          model: target.videoOverride.model,
          selected: selectedModel,
        }))
      }
    }
    director.setDirectorResolution(target.videoOverride.resolution)
    director.setDirectorAspectRatio(target.videoOverride.aspectRatio)
    director.setSidebarMode('director')
    director.setDirectorSkill('music_video')
    director.setDirectorAutoMode(false)
    director.setDirectorShotImageGuidance(directVideo || directReferences ? 'prompt_only' : 'auto')
    if (String(target.videoOverride.model || '').startsWith('minimax_h3') && !directVideo) {
      director.setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')
    }
    director.setDirectorMusicVideoTreatment({
      generation_mode: directVideo ? 'direct_video' : 'image_guided',
      direct_video_master_prompt: target.directVideoMasterPrompt,
    })
    director.directorSetSceneDescription(adaptation.sceneDescription)
    director.shortFilmSetVisualStyle(directVideo ? '' : target.visualStyle)
    director.shortFilmSetPreserveVisualStyle(directVideo ? false : target.enforceVisualStyle)
    director.setDirectorCharacterVisualStyle(directVideo ? '' : target.characterVisualStyle)
    director.setDirectorAllowClipText(target.allowClipText)
    director.setDirectorSpokenLanguage(target.spokenLanguage)
    useStore.setState({
      directorMusicSource: 'upload',
      directorSongDescription: resolvedCue.brief,
      directorSongStyle: resolvedCue.style,
      directorSongLyrics: resolvedCue.lyrics,
      directorSongDuration: resolvedCue.durationSeconds,
      directorPacingProfile: action.pacing,
      directorStep: 'upload',
      directorWritingProvider: target.provider.writingProvider,
      directorWritingModel: target.provider.writingModel,
      directorWritingBaseUrl: target.provider.writingBaseUrl,
    })

    for (const reference of directVideo ? [] : adaptation.characterReferences) {
      const asset = target.assets[reference.assetId]
      if (!asset) continue
      try {
        const response = await fetch(asset.source)
        if (!response.ok) continue
        const blob = await response.blob()
        director.directorAddCharacterRef(new File([blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' }))
        director.directorSetCharacterRefLabel(useStore.getState().directorCharacterRefs.length - 1, reference.label)
      } catch { /* The written identity remains available in the visual brief. */ }
    }
    for (const reference of directVideo ? [] : adaptation.locationReferences) {
      const asset = target.assets[reference.assetId]
      if (!asset) continue
      try {
        const response = await fetch(asset.source)
        if (!response.ok) continue
        const blob = await response.blob()
        director.directorAddLocationRef(new File([blob], asset.name || `${reference.assetId}.png`, { type: blob.type || 'image/png' }))
        director.directorSetLocationRefLabel(useStore.getState().directorLocationRefs.length - 1, reference.label)
      } catch { /* The written world bible remains available in the visual brief. */ }
    }

    const songName = candidate.displayName || candidate.title || candidate.name
    const audioSource = api.getPlayableFileUrl(candidate.source, candidate.name, workspace)
    const audioResponse = await fetch(audioSource)
    if (!audioResponse.ok) throw new Error(i18n.t('storyLab:errors.audioUnreadable', { name: songName }))
    const audioBlob = await audioResponse.blob()
    await useStore.getState().directorUploadAndAnalyze(new File(
      [audioBlob], candidate.name, { type: audioBlob.type || 'audio/mpeg' },
    ), {
      lyricsHint: resolvedCue.lyrics || undefined,
      totalDuration: resolvedCue.durationSeconds,
    })
    const afterAnalyze = useStore.getState()
    if (afterAnalyze.directorError) throw new Error(afterAnalyze.directorError)
    if (afterAnalyze.directorStep !== 'structure') {
      throw new Error(i18n.t('storyLab:errors.songNotAnalyzed'))
    }

    useStore.setState({
      directorStoryProductionHandoff: {
        workspace,
        projectId: target.id,
        productionId: production.id,
        cueId: resolvedCue.id,
        candidateId: candidate.id,
      },
    })
    director.setSettingsOpen(false)
    director.setDashboardOpen(false)
    director.setMediaFilter('all')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return storyResult(
      workspace,
      project,
      'overview',
      i18n.t('storyLab:replies.musicVideoStaged', { title: production.title, song: songName, cue: resolvedCue.title }),
      {
        destination: 'director',
        projectId: project.id,
        productionId: production.id,
        cueId: resolvedCue.id,
        candidateId: candidate.id,
        taskId: candidate.taskId || candidate.provenance?.taskId,
        rootTaskId: candidate.rootTaskId || candidate.provenance?.rootTaskId,
        jobId: candidate.provenance?.jobId,
        provenance: { ...production.provenance, projectId: project.id },
      },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function startDirectorProduction(
  action: StartDirectorProductionCommand,
): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('storyLab:errors.confirmStartProduction'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, api] = await Promise.all([
    import('./store'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const stories = useStoryStore.getState()
  if (stories.libraryConflicts.length) throw new Error(i18n.t('storyLab:errors.conflictBeforeStart'))
  const target = resolveStoryProject(stories.projects, stories.project, action.targetStoryId, action.targetStoryTitle)
  if (stories.activeProjectOperations[target.id]) throw new Error(i18n.t('storyLab:errors.storyActiveOperation', { title: target.title }))

  const director = useStore.getState()
  const handoff = director.directorStoryProductionHandoff
  if (!handoff || handoff.workspace !== workspace || handoff.projectId !== target.id) {
    throw new Error(i18n.t('storyLab:errors.noStagedProduction', { title: target.title }))
  }
  const production = target.productions.find(item => item.id === handoff.productionId)
  if (!production || (production.kind !== 'film' && production.kind !== 'trailer' && production.kind !== 'music_video')) {
    throw new Error(i18n.t('storyLab:errors.stagedProductionGone'))
  }
  if (action.productionId && action.productionId !== production.id) {
    throw new Error(i18n.t('storyLab:errors.stagedProductionIdMismatch', { actual: production.id, expected: action.productionId }))
  }
  if (action.kind && production.kind !== action.kind) {
    throw new Error(i18n.t('storyLab:errors.stagedProductionKindMismatch', { actual: production.kind, expected: action.kind }))
  }
  const existingPipelineId = typeof production.targetSnapshot?.pipelineId === 'string'
    ? production.targetSnapshot.pipelineId.trim() : ''
  if (existingPipelineId) {
    director.setSettingsOpen(false)
    director.setDashboardOpen(false)
    director.setMediaFilter('all')
    director.setSidebarMode('director')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return storyResult(
      workspace,
      target,
      'overview',
      i18n.t('storyLab:replies.productionAlreadyStarted', { title: production.title, pipelineId: existingPipelineId }),
      directorResultDetails(production, workspace, target.id, existingPipelineId),
    )
  }
  if (director.pipelineId) {
    throw new Error(i18n.t('storyLab:errors.directorAlreadyLinked', { pipelineId: director.pipelineId }))
  }
  if (production.kind === 'music_video') {
    if (director.directorSkill !== 'music_video' || director.directorStep !== 'structure' || !director.directorSceneDescription.trim()) {
      throw new Error(i18n.t('storyLab:errors.musicVideoNotReady'))
    }
  } else if (director.directorSkill !== 'short_film' || director.directorStep !== 'style' || !director.directorSceneDescription.trim()) {
    throw new Error(i18n.t('storyLab:errors.filmNotReady'))
  }
  if (director.directorLoading) throw new Error(i18n.t('storyLab:errors.directorBusy'))

  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    director.setSettingsOpen(false)
    director.setDashboardOpen(false)
    director.setMediaFilter('all')
    director.setSidebarMode('director')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    if (production.kind === 'music_video' && useStore.getState().directorStep === 'structure') {
      useStore.getState().directorConfirmStructure()
    }
    // The Wizard reaches this adapter only after an explicit, confirmed
    // start action. Staging remains reviewable, while "execute" must not
    // silently stop at Director's manual prompt/image checkpoints.
    useStore.getState().setDirectorAutoMode(true)
    await useStore.getState().startDirectorPipeline()
    const pipelineId = useStore.getState().pipelineId
    if (!pipelineId) throw new Error(i18n.t('storyLab:errors.directorNoPipeline'))

    let linkWarning = ''
    try {
      let saved = false
      for (let attempt = 0; attempt < 2 && !saved; attempt += 1) {
        const remote = await api.fetchStoryLibrary(workspace)
        const remoteProject = remote.projects[target.id]
        const remoteProduction = remoteProject?.productions.find(item => item.id === production.id)
        if (!remoteProject || !remoteProduction) throw new Error(i18n.t('storyLab:errors.remoteProductionGone'))
        const linkedProject = normalizeStoryProject({
          ...remoteProject,
          revision: remoteProject.revision + 1,
          updatedAt: new Date().toISOString(),
          productions: remoteProject.productions.map(item => item.id === production.id ? {
            ...item,
            provenance: directorRunProvenance(
              item.provenance, workspace, target.id, item.id, pipelineId,
            ),
            targetSnapshot: {
              ...(item.targetSnapshot || {}),
              pipelineId,
              provenance: directorRunProvenance(
                item.targetSnapshot?.provenance as import('./types').StoryProvenance | undefined,
                workspace, target.id, item.id, pipelineId,
              ),
            },
          } : item),
        })
        try {
          const library = await api.saveStoryLibrary(workspace, {
            ...remote,
            projects: { ...remote.projects, [target.id]: linkedProject },
          })
          useStoryStore.setState({
            workspace,
            project: library.projects[library.activeId],
            projects: library.projects,
            libraryRevision: library.revision,
            dirty: false,
            hydrated: true,
            loading: false,
            saveError: null,
            libraryConflicts: [],
          })
          saved = true
        } catch (error) {
          if (!(error instanceof api.StoryLibraryRevisionError) || attempt === 1) throw error
        }
      }
    } catch (error) {
      linkWarning = i18n.t('storyLab:replies.pipelineLinkFailed', { message: (error as Error).message })
    }
    return storyResult(
      workspace,
      target,
      'overview',
      i18n.t('storyLab:replies.productionStarted', { title: production.title, pipelineId, linkWarning }),
      directorResultDetails(production, workspace, target.id, pipelineId),
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}
