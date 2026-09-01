import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import {
  boundedDuration,
  creativeCharacters,
  creativeLocations,
  explicitMusicLanguage,
  normalizeName,
  outlineBeats,
} from '../../lib/labHelpers'
import { useStore } from '../../stores/useStore'
import { applyMusicVideoDirectVideoDefaults, resolveMusicVideoVisualStyle } from './musicVideoLook'
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
    pipelineIds: typeof extra.pipelineId === 'string' && extra.pipelineId ? [extra.pipelineId] : undefined,
    navigationTarget: {
      destination: extra.destination === 'director' ? 'director' : 'story_lab',
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

async function saveActiveStoryProjectMutation(
  workspace: string,
  current: { libraryRevision: number; projects: Record<string, import('./types').StoryProject> },
  projectId: string,
  mutate: (project: import('./types').StoryProject) => import('./types').StoryProject,
): Promise<import('./types').StoryProject> {
  const [{ useStoryStore }, api] = await Promise.all([
    import('./store'), import('../../api/client'),
  ])
  let baseline = current
  let library: Awaited<ReturnType<typeof api.saveStoryLibrary>> | null = null
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const source = baseline.projects[projectId]
    if (!source) throw new Error('La historia activa desapareció antes de poder guardarla.')
    const project = mutate(source)
    try {
      library = await api.saveStoryLibrary(workspace, {
        version: 2,
        revision: baseline.libraryRevision,
        activeId: project.id,
        projects: { ...baseline.projects, [project.id]: project },
      })
      break
    } catch (error) {
      if (!(error instanceof api.StoryLibraryRevisionError) || attempt === 2) throw error
      const remote = await api.fetchStoryLibrary(workspace)
      baseline = {
        libraryRevision: remote.revision,
        projects: remote.projects,
      }
    }
  }
  if (!library?.projects[projectId]) throw new Error('Story Lab guardó la biblioteca sin devolver la historia editada.')
  useStoryStore.setState({
    workspace,
    project: library.projects[projectId],
    projects: library.projects,
    libraryRevision: library.revision,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
  })
  await useStoryStore.getState().loadWorkspace(workspace)
  return library.projects[projectId]
}

export async function configureStorySong(action: ConfigureStorySongCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { normalizeStoryMusicModel, songWriteTarget }, { resolveStoryWritingProvider }, api] = await Promise.all([
    import('./store'), import('./musicModel'), import('./provider'), import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de editar la canción.')
  const found = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!found) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  const target = found.projectType === 'music_video'
    ? applyMusicVideoDirectVideoDefaults(found)
    : applyMusicVideoDirectVideoDefaults({
      ...found,
      projectType: 'music_video',
      musicVideoGenerationMode: 'direct_video',
    })
  if (current.activeProjectOperations[target.id]) throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  const lyricsLanguage = explicitMusicLanguage(action.lyricsLanguage || target.language)
  const durationSeconds = boundedDuration(action.durationSeconds, target.music.targetDurationSeconds)
  const model = normalizeStoryMusicModel(action.model)
  const brief = action.brief.trim() || target.music.brief || target.creativeBrief.songStory || target.premise
  let style = action.style.trim()
  let lyrics = action.instrumental ? '' : action.lyrics.trim()
  let lyriaPrompt = ''
  if (!action.instrumental && !lyrics && action.writeLyrics) {
    const writing = resolveStoryWritingProvider(useStore.getState().productionProfile, target)
    const storyContext = [
      `Título: ${target.title}`,
      `Premisa: ${target.premise}`,
      target.synopsis ? `Sinopsis: ${target.synopsis}` : '',
      target.theme ? `Tema: ${target.theme}` : '',
      target.beats.length ? `Progresión: ${target.beats.map(item => item.summary).join(' → ')}` : '',
    ].filter(Boolean).join('\n')
    const written = await api.writeSong({
      description: `${brief}\nEscribe el prompt musical y la letra completa en ${lyricsLanguage}.`,
      instrumental: false,
      target: songWriteTarget(model),
      model,
      style_direction: `${style}\nRedacta también la dirección musical visible en ${lyricsLanguage}.`,
      lyrics_direction: `Letra vocal completamente original en ${lyricsLanguage}, con secciones [Verse], [Chorus], [Bridge] y [Outro].`,
      story_context: storyContext,
      language: lyricsLanguage,
      duration_seconds: durationSeconds,
      max_new_tokens: 2200,
      writingProvider: writing.provider,
      writingModel: writing.model,
      writingBaseUrl: writing.baseUrl,
    })
    style = written.style.trim() || style
    lyrics = written.lyrics.trim()
    lyriaPrompt = written.lyria_prompt.trim()
  }
  if (!action.instrumental && !lyrics) throw new Error('El compositor no devolvió una letra vocal completa para la ficha.')
  const existing = target.music.cues.find(item => item.kind === 'story')
  const cueTitle = action.songTitle.trim() || existing?.title || `${target.title} · canción`
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
  if (!savedCue) throw new Error('Story Lab guardó la ficha sin devolver el cue musical.')
  return storyResult(
    workspace,
    project,
    'music',
    `He rellenado y guardado la canción “${savedCue.title}” en Story Lab → Music con ${project.music.model}, modo ${savedCue.instrumental ? 'instrumental' : 'vocal'} y la letra editable en ${savedCue.lyricsLanguage}.`,
    { cueId: savedCue.id, cueTitle: savedCue.title },
  )
}

export async function generateStorySong(action: GenerateStorySongCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Generar la canción requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { isAceStepMusicModel, ACE_STEP_MUSIC_MODEL }, api] = await Promise.all([
    import('./store'), import('./musicModel'), import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de generar la canción.')
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  const exactCue = action.cueTitle
    ? target.music.cues.find(item => normalizeName(item.title) === normalizeName(action.cueTitle))
    : undefined
  // A resumed Wizard workflow may retain a guessed future candidate label
  // such as "Cue · Español". When the persisted project has exactly one cue,
  // its identity is unambiguous and must win over that stale label.
  const cue = exactCue
    || (target.music.cues.length === 1 ? target.music.cues[0] : undefined)
    || (!action.cueTitle ? target.music.cues.find(item => item.kind === 'story') : undefined)
  if (!cue) throw new Error(`No existe la canción “${action.cueTitle || 'principal'}” en “${target.title}”.`)
  if (!cue.style.trim()) throw new Error(`“${cue.title}” necesita un estilo musical antes de generarse.`)
  if (!cue.instrumental && !cue.lyrics.trim()) throw new Error(`“${cue.title}” necesita letra antes de generarse.`)
  if (!isAceStepMusicModel(target.music.model)) {
    throw new Error('Este contrato automatizado genera canciones con ACE-Step 1.5 XL. Selecciónalo o genera MiniMax desde Story Lab.')
  }
  if (current.activeProjectOperations[target.id]) throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  useStoryStore.getState().beginProjectOperation(target.id)
  try {
    const rendered = await api.generateMusic({
      style: cue.style.trim(),
      lyrics: cue.instrumental ? '[Instrumental]' : cue.lyrics,
      instrumental: cue.instrumental,
      duration_seconds: cue.durationSeconds,
      model_type: ACE_STEP_MUSIC_MODEL,
      workspace,
      initiator: `Story Lab · ${target.projectType === 'music_video' ? 'Videoclip' : 'Story song'}`,
    })
    if (!rendered.filename || !rendered.audio_path) throw new Error('ACE-Step terminó sin devolver un archivo de audio verificable.')
    const candidateId = storyId('song')
    let version = 1
    const project = await saveActiveStoryProjectMutation(
      workspace,
      useStoryStore.getState(),
      target.id,
      source => {
        const latestCue = source.music.cues.find(item => item.id === cue.id)
        if (!latestCue) throw new Error(`El cue “${cue.title}” desapareció mientras se generaba el audio.`)
        const existingCandidate = latestCue.candidates.find(item => item.id === candidateId)
        version = existingCandidate?.version || (latestCue.candidates.length + 1)
        const candidate = existingCandidate || {
          id: candidateId,
          displayName: `${latestCue.title} · ${latestCue.lyricsLanguage || source.language} · v${version}`,
          title: latestCue.title,
          language: latestCue.lyricsLanguage || source.language,
          version,
          name: rendered.filename,
          source: api.getFileUrl(rendered.filename, workspace),
          prompt: latestCue.style,
          lyrics: latestCue.instrumental ? '' : latestCue.lyrics,
          provider: 'local' as const,
          model: ACE_STEP_MUSIC_MODEL,
          durationSeconds: latestCue.durationSeconds,
          createdAt: new Date().toISOString(),
        }
        return normalizeStoryProject({
          ...source,
          revision: source.revision + 1,
          music: {
            ...source.music,
            selectedCandidateId: candidateId,
            cues: source.music.cues.map(item => item.id === latestCue.id ? {
              ...item,
              candidates: existingCandidate ? item.candidates : [...item.candidates, candidate],
              selectedCandidateId: candidateId,
            } : item),
          },
          updatedAt: new Date().toISOString(),
        })
      },
    )
    const savedCue = project.music.cues.find(item => item.id === cue.id)
    if (!savedCue?.candidates.some(item => item.id === candidateId)) {
      throw new Error('Story Lab guardó la canción sin devolver el candidato generado.')
    }
    return storyResult(
      workspace,
      project,
      'music',
      `ACE-Step ha generado “${savedCue.title}” y la versión v${version} ha quedado seleccionada en Story Lab → Music.`,
      { candidateId, cueTitle: savedCue.title, outputName: rendered.filename },
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
    throw new Error('Story Lab tiene un conflicto pendiente entre la copia local y la del workspace; resuélvelo antes de crear otra historia.')
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
      `El videoclip “${sameTitle.title}” ya existía; lo he abierto en Story Lab → Overview.`,
    )
  }
  if (duplicate && !(action.projectType === 'music_video' && duplicate.projectType !== 'music_video')) {
    useStoryStore.setState({ project: duplicate, dirty: false })
    return storyResult(
      workspace,
      duplicate,
      'overview',
      `La historia “${duplicate.title}” ya existía; la he abierto en Story Lab → Overview.`,
    )
  }

  const base = createStoryProject(action.projectType || 'full_story')
  const resolvedVisualStyle = resolveMusicVideoVisualStyle(
    action.projectType || 'full_story',
    action.visualStyle,
    action.creativeBrief,
  )
  const characters = creativeCharacters(action.characters).map((character, index) => ({
    id: storyId('character'),
    name: character.name || `Personaje ${index + 1}`,
    role: character.role || (index ? 'Secundario' : 'Protagonista'),
    age: '', pronouns: '',
    personality: character.personality,
    desire: character.desire,
    need: `Aprender algo que contradice su deseo inmediato: ${character.desire || 'resolver el conflicto'}.`,
    flaw: character.flaw,
    conflict: action.premise,
    arc: action.ending || 'La experiencia cambia su manera de afrontar el conflicto.',
    voice: character.voice,
    appearance: character.appearance,
    wardrobe: 'Vestuario coherente y reconocible durante toda la historia.',
    visualPrompt: `${character.appearance}. ${resolvedVisualStyle}`.trim(),
    negativePrompt: 'inconsistent identity, duplicate character, unreadable face',
    referenceAssetIds: [], approval: 'draft' as const,
  }))
  const locations = creativeLocations(action.locations).map((location, index) => ({
    id: storyId('location'),
    name: location.name || `Localización ${index + 1}`,
    purpose: location.purpose,
    description: location.description,
    visualPrompt: `${location.description}. ${resolvedVisualStyle}`.trim(),
    negativePrompt: 'inconsistent layout, unreadable signage, visual clutter',
    referenceAssetIds: [],
  }))
  const beats = outlineBeats(action.outlineBeats, action.premise, action.ending).map((beat, index, all) => ({
    id: storyId('beat'),
    stage: index === 0 ? 'Inicio' : index === all.length - 1 ? 'Resolución' : `Desarrollo ${index}`,
    title: `Beat ${index + 1}`,
    summary: beat,
    goal: index === all.length - 1 ? 'Cerrar el arco y mostrar la consecuencia.' : 'Hacer avanzar el objetivo del protagonista.',
    conflict: index === 0 ? action.premise : 'La situación se complica y obliga a tomar una decisión.',
    turn: index === all.length - 1 ? action.ending || beat : 'La nueva información cambia el rumbo de la historia.',
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
    language: action.language || 'Español',
    spokenLanguage: action.language || 'Español de España',
    genre: action.genre || 'Narrativa',
    tone: action.tone || 'Cinematográfico',
    visualStyle: resolvedVisualStyle || 'Dirección visual cinematográfica coherente, personajes legibles y continuidad entre escenas.',
    characterVisualStyle: resolvedVisualStyle || 'Identidades consistentes, siluetas reconocibles y expresiones claras.',
    premise: action.premise,
    logline: action.logline,
    synopsis: action.synopsis || action.premise,
    theme: action.theme,
    ending: action.ending,
    world: {
      ...base.world,
      summary: action.worldSummary || action.synopsis || action.premise,
      period: 'Época indicada por la historia.',
      geography: locations.map(location => location.name).join(', '),
      society: 'Las relaciones y normas sociales sostienen el conflicto dramático.',
      technology: 'Coherente con la época y el universo narrativo.',
      rules: ['Mantener la continuidad de personajes, espacios y consecuencias entre beats.'],
      visualLanguage: resolvedVisualStyle || 'Lenguaje cinematográfico claro y consistente.',
      visualPrompt: resolvedVisualStyle,
      negativePrompt: 'continuity errors, inconsistent characters, unreadable composition',
      locations,
    },
    characters,
    relationships: characters.length > 1 ? [{
      id: storyId('relationship'),
      fromCharacterId: characters[0].id,
      toCharacterId: characters[1].id,
      label: 'Conflicto principal',
      dynamic: 'Sus objetivos chocan y hacen avanzar la historia.',
      evolution: 'La resolución modifica su relación de forma visible.',
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
    `He creado y guardado “${project.title}” con ${characters.length} personajes, ${locations.length} localizaciones y ${beats.length} beats; está abierto en Story Lab → Overview.`,
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
    throw new Error('Story Lab tiene un conflicto pendiente entre la copia local y la del workspace; resuélvelo antes de editar la historia.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(project => normalizeName(project.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) {
    throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  }
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” tiene una operación activa; espera a que termine antes de modificar su canon.`)
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
  if (action.language) {
    candidate.language = action.language
    candidate.spokenLanguage = action.language
  }

  action.characters.forEach(character => {
    const index = candidate.characters.findIndex(item => normalizeName(item.name) === normalizeName(character.name))
    const existing = index >= 0 ? candidate.characters[index] : null
    const patched = {
      id: existing?.id || storyId('character'),
      name: character.name,
      role: character.role || existing?.role || 'Personaje',
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
      stage: index === 0 ? 'Inicio' : index === all.length - 1 ? 'Resolución' : `Desarrollo ${index}`,
      title: `Beat ${index + 1}`,
      summary,
      goal: index === all.length - 1 ? 'Cerrar el arco y mostrar la consecuencia.' : 'Hacer avanzar el objetivo dramático.',
      conflict: index === 0 ? candidate.premise : 'Una complicación obliga a cambiar de estrategia.',
      turn: index === all.length - 1 ? candidate.ending || summary : 'La consecuencia cambia el rumbo de la historia.',
    }))
  }

  const normalized = normalizeStoryProject(candidate)
  const sections = changedSections(target, normalized)
  if (!sections.length) throw new Error(`La petición no cambia ningún campo de “${target.title}”.`)
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
    `He actualizado y guardado “${project.title}”: ${sections.join(', ')}. Está abierto en Story Lab → ${section}.`,
  )
}

export async function generateStorySectionDraft(
  action: GenerateStorySectionCommand,
  onStep?: (message: string) => void,
): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Generar una propuesta de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore }, { resolveStoryWritingProvider }, api] = await Promise.all([
    import('./store'),
    import('./provider'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de generar otra propuesta.')
  }
  const project = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!project) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[project.id]) {
    throw new Error(`La historia “${project.title}” ya tiene una operación activa.`)
  }
  const premise = project.premise.trim()
    || project.creativeBrief.generalIdea.trim()
    || project.logline.trim()
    || project.synopsis.trim()
  if (!premise) throw new Error(`“${project.title}” necesita una premisa o briefing antes de invocar al escritor.`)

  useStoryStore.setState({ project, dirty: false })
  const visibleSection = action.scope === 'all' ? 'overview' : action.scope
  const resultKey = `maestro-story-plan-result:${workspace}:${project.id}`
  const jobKey = `maestro-story-plan-job:${workspace}:${project.id}`
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
      instruction: action.instruction,
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
      `La propuesta de ${action.scope} para “${project.title}” está lista en Story Lab. Revísala y elige qué cambios aplicar; todavía no he modificado ni aprobado el canon.`,
      { notifyDraft: true },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(project.id)
  }
}

export async function applyStoredStoryProposal(action: ApplyStoryProposalCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Aplicar una propuesta de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { changedSections, normalizeStoryCharacter }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de aplicar la propuesta.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  }
  const resultKey = `maestro-story-plan-result:${workspace}:${target.id}`
  const jobKey = `maestro-story-plan-job:${workspace}:${target.id}`
  let saved: { scope?: unknown; result?: unknown } | null = null
  try {
    saved = JSON.parse(window.localStorage.getItem(resultKey) || 'null')
  } catch {
    throw new Error(`La propuesta guardada de “${target.title}” está dañada; vuelve a generarla.`)
  }
  if (!saved?.result || typeof saved.result !== 'object' || Array.isArray(saved.result)) {
    throw new Error(`No hay una propuesta terminada para “${target.title}”. Genera una sección y revísala primero.`)
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
        const name = typeof raw.name === 'string' ? raw.name : `Localización ${index + 1}`
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
  if (!sections.length) throw new Error(`La propuesta no cambia ningún campo de “${target.title}”.`)
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
    `He aplicado y guardado la propuesta de “${project.title}” en: ${sections.join(', ')}. Sus aprobaciones afectadas vuelven a borrador.`,
    { notifyDraft: true },
  )
}

export async function approveStorySection(action: ApproveStorySectionCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Aprobar una sección de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { changedSections }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de aprobar canon.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  }

  if (action.section === 'overview' && (!target.premise.trim() || !target.logline.trim() || !target.synopsis.trim())) {
    throw new Error('Overview necesita premise, logline y synopsis antes de aprobarse.')
  }
  if (action.section === 'world' && (!target.world.summary.trim() || !target.world.visualLanguage.trim())) {
    throw new Error('World necesita un resumen y un lenguaje visual antes de aprobarse.')
  }
  const directVideo = target.musicVideoGenerationMode === 'direct_video'
  if (action.section === 'characters') {
    if (!target.characters.length) throw new Error('Añade al menos un personaje antes de aprobar el reparto.')
    if (!directVideo) {
      const incomplete = target.characters.flatMap(character => {
        const reasons = [
          character.approval !== 'approved' ? 'sigue en borrador' : '',
          !character.primaryReferenceAssetId ? 'no tiene identidad primaria' : '',
          character.primaryReferenceAssetId
            && target.assets[character.primaryReferenceAssetId]?.approval !== 'approved'
            ? 'su identidad primaria falta o no está aprobada' : '',
        ].filter(Boolean)
        return reasons.length ? [`${character.name || 'Personaje sin nombre'} (${reasons.join(', ')})`] : []
      })
      if (incomplete.length) {
        throw new Error(`No se puede aprobar Characters: ${incomplete.join(' · ')}.`)
      }
    }
  }
  if (action.section === 'relationships' && target.relationships.some(relationship => (
    !relationship.fromCharacterId
    || !relationship.toCharacterId
    || relationship.fromCharacterId === relationship.toCharacterId
    || !relationship.dynamic.trim()
  ))) {
    throw new Error('Cada relación necesita dos personajes distintos y una dinámica actual.')
  }
  if (action.section === 'structure' && (
    target.beats.length < 3
    || target.beats.some(beat => !beat.summary.trim() || !beat.conflict.trim() || !beat.turn.trim())
  )) {
    throw new Error('Structure necesita al menos tres beats causales con acción, conflicto y consecuencia.')
  }

  if (target.approvals[action.section]?.version === target.sectionVersions[action.section]) {
    return storyResult(
      workspace,
      target,
      action.section,
      `Story Lab → ${action.section} ya estaba aprobado en la versión actual de “${target.title}”.`,
    )
  }
  const candidate = structuredClone(target)
  if (action.section === 'characters' && directVideo) {
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
    `He validado, aprobado y guardado Story Lab → ${action.section} para “${project.title}”.`,
  )
}

export async function approveStoryVisuals(action: ApproveStoryVisualsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Aprobar referencias visuales requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { changedSections }, api] = await Promise.all([
    import('./store'),
    import('./model'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de aprobar referencias visuales.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  }

  const candidate = structuredClone(target)
  let changed = false
  const labels: string[] = []
  for (const selection of action.selections) {
    const assetMatches = Object.values(candidate.assets).filter(asset => normalizeName(asset.name) === normalizeName(selection.assetName))
    if (!assetMatches.length) throw new Error(`No existe el asset visual “${selection.assetName}” en “${target.title}”.`)
    if (assetMatches.length > 1) throw new Error(`Hay varios assets llamados “${selection.assetName}”; renómbralos para elegir uno sin ambigüedad.`)
    const asset = assetMatches[0]
    if (asset.approval !== 'approved') { asset.approval = 'approved'; changed = true }

    if (selection.targetKind === 'world') {
      if (selection.primary) throw new Error('primary sólo puede usarse con una referencia de personaje.')
      if (!candidate.world.referenceAssetIds.includes(asset.id)) {
        candidate.world.referenceAssetIds.push(asset.id); changed = true
      }
      labels.push(`${asset.name} → mundo`)
      continue
    }

    if (selection.targetKind === 'location') {
      if (selection.primary) throw new Error('primary sólo puede usarse con una referencia de personaje.')
      const matches = candidate.world.locations.filter(location => normalizeName(location.name) === normalizeName(selection.targetName))
      if (!matches.length) throw new Error(`No existe la localización “${selection.targetName}” en “${target.title}”.`)
      if (matches.length > 1) throw new Error(`Hay varias localizaciones llamadas “${selection.targetName}”; renómbralas antes de elegir referencias.`)
      if (!matches[0].referenceAssetIds.includes(asset.id)) {
        matches[0].referenceAssetIds.push(asset.id); changed = true
      }
      labels.push(`${asset.name} → ${matches[0].name}`)
      continue
    }

    const matches = candidate.characters.filter(character => normalizeName(character.name) === normalizeName(selection.targetName))
    if (!matches.length) throw new Error(`No existe el personaje “${selection.targetName}” en “${target.title}”.`)
    if (matches.length > 1) throw new Error(`Hay varios personajes llamados “${selection.targetName}”; renómbralos antes de elegir su identidad.`)
    const character = matches[0]
    if (!character.referenceAssetIds.includes(asset.id)) {
      character.referenceAssetIds.push(asset.id); changed = true
    }
    if (selection.primary || !character.primaryReferenceAssetId) {
      if (character.primaryReferenceAssetId !== asset.id) { character.primaryReferenceAssetId = asset.id; changed = true }
    }
    labels.push(`${asset.name} → ${character.name}${character.primaryReferenceAssetId === asset.id ? ' (primaria)' : ''}`)
  }

  if (!changed) {
    useStoryStore.setState({ project: target, dirty: false })
    return storyResult(
      workspace,
      target,
      'assets',
      `Las referencias solicitadas de “${target.title}” ya estaban vinculadas y aprobadas; he abierto Story Lab → Assets.`,
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
    `He vinculado y aprobado ${labels.length} referencia${labels.length === 1 ? '' : 's'} en “${project.title}”: ${labels.join(' · ')}.`,
  )
}

export async function generateStoryVisuals(action: GenerateStoryVisualsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Generar referencias visuales de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const { useStoryStore } = await import('./store')
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de generar imágenes.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” ya tiene una operación visual activa.`)
  }
  useStoryStore.setState({ project: target, dirty: false })
  return storyResult(
    workspace,
    target,
    'assets',
    `Generaré las referencias visuales de “${target.title}”.`,
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
  if (!action.confirm) throw new Error('Preparar una adaptación de cómic requiere confirm=true porque sustituye el borrador actual de Comics.')
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
    throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de preparar una producción.')
  }
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) {
    throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  }
  if (!target.premise.trim() && !target.logline.trim() && !target.synopsis.trim()) {
    throw new Error(`“${target.title}” necesita una premisa, logline o synopsis antes de adaptarse.`)
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
      `He preparado “${comic.title}” como capítulo editable de ${action.pageCount} páginas × ${action.panelsPerPage} viñetas en Comic Director. No he generado imágenes.`,
      { destination: 'comics', comicId: comic.id, comicTitle: comic.title },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function stageStoryVideo(action: StageStoryVideoCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Preparar una producción de vídeo requiere confirm=true porque sustituye el borrador actual de Director.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, api] = await Promise.all([
    import('./store'), import('./adaptations'), import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de preparar una producción.')
  const target = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[target.id]) throw new Error(`La historia “${target.title}” tiene una operación activa.`)
  if (!target.synopsis.trim() || !target.characters.length) throw new Error('La producción necesita una sinopsis y al menos un personaje.')
  const duration = boundedDuration(action.durationSeconds, target.creativeBrief.durationSeconds || (action.kind === 'trailer' ? 60 : 90))
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
      `He preparado “${title}” (${duration}s) en Short Film Director con el canon y las referencias aprobadas. No he iniciado ninguna generación.`,
      { destination: 'director', productionId: production.id },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function stageStoryMusicVideo(action: StageStoryMusicVideoCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Preparar un videoclip requiere confirm=true porque sustituye el borrador actual de Director.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, api, selection] = await Promise.all([
    import('./store'),
    import('./adaptations'),
    import('../../api/client'),
    import('./musicVideoSelection'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de preparar el videoclip.')
  const found = action.targetStoryTitle
    ? Object.values(current.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : current.project
  if (!found) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (current.activeProjectOperations[found.id]) throw new Error(`La historia “${found.title}” tiene una operación activa.`)
  const { cue, candidate } = selection.resolveStoryMusicSelection(found, action.songName, action.cueTitle)
  const resolvedCue = selection.effectiveStoryMusicCue(found, cue, candidate)
  const target = applyMusicVideoDirectVideoDefaults(found.projectType === 'music_video'
    ? found
    : { ...found, projectType: 'music_video', musicVideoGenerationMode: 'direct_video' })
  const directVideo = target.musicVideoGenerationMode === 'direct_video'
  const directReferences = target.musicVideoGenerationMode === 'direct_references'
  if (directReferences && !String(target.videoOverride.model || '').startsWith('minimax_h3')) {
    throw new Error('Las referencias directas de este videoclip requieren un modelo MiniMax H3 con Ref2VA.')
  }
  const adaptation = adaptations.buildMusicVideoAdaptation(target, resolvedCue, {
    generationMode: target.musicVideoGenerationMode,
  })
  if (directReferences && !adaptation.characterReferences.length && !adaptation.locationReferences.length) {
    throw new Error('No hay referencias aprobadas para este cue. Aprueba una imagen de mundo, localización o personaje antes de preparar el videoclip.')
  }
  const production = {
    id: storyId('production'),
    kind: 'music_video' as const,
    title: `${adaptation.focusLabel} · music video`,
    createdAt: new Date().toISOString(),
    sourceVersion: target.revision,
    sourceSnapshot: { ...structuredClone(target), productions: [] },
    targetId: adaptation.focusTargetId,
    targetName: adaptation.focusLabel,
    targetSnapshot: {
      cueId: resolvedCue.id,
      cueTitle: resolvedCue.title,
      candidateId: candidate.id,
      candidateName: candidate.name,
      candidateSource: candidate.source,
      provider: candidate.provider,
      model: candidate.model,
      lyrics: resolvedCue.lyrics,
      focusKind: adaptation.focusKind,
      focusTargetId: adaptation.focusTargetId,
      sceneDescription: adaptation.sceneDescription,
      pacing: action.pacing,
      mode: 'full',
      imageModel: target.provider.imageModel,
      videoModel: target.videoOverride.model,
      resolution: target.videoOverride.resolution,
      aspectRatio: target.videoOverride.aspectRatio,
      generationMode: target.musicVideoGenerationMode,
      directVideoMasterPrompt: target.directVideoMasterPrompt,
      writingProvider: target.provider.writingProvider,
      writingModel: target.provider.writingModel,
      writingBaseUrl: target.provider.writingBaseUrl,
    },
    status: 'staged' as const,
  }

  useStoryStore.getState().beginProjectOperation(target.id)
  try {
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

    const director = useStore.getState()
    director.directorReset()
    director.setGenerationMode('video')
    if (!directVideo && !directReferences && target.provider.imageModel) director.selectDirectorImageModel(target.provider.imageModel)
    if (target.videoOverride.model) {
      await director.selectDirectorVideoModel(target.videoOverride.model)
      const selected = useStore.getState().selectedModelPerMode.video
      if (selected !== target.videoOverride.model) {
        throw new Error(`Director no aplicó el modelo de vídeo ${target.videoOverride.model}; quedó ${selected || 'vacío'}.`)
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

    const audioSource = api.getPlayableFileUrl(candidate.source, candidate.name, workspace)
    const audioResponse = await fetch(audioSource)
    if (!audioResponse.ok) throw new Error(`No pude leer el audio de “${candidate.displayName || candidate.title || candidate.name}”.`)
    const audioBlob = await audioResponse.blob()
    await useStore.getState().directorUploadAndAnalyze(new File(
      [audioBlob], candidate.name, { type: audioBlob.type || 'audio/mpeg' },
    ), { lyricsHint: resolvedCue.lyrics || undefined })
    const afterAnalyze = useStore.getState()
    if (afterAnalyze.directorError) throw new Error(afterAnalyze.directorError)
    if (afterAnalyze.directorStep !== 'structure') {
      throw new Error('La canción no quedó analizada en el paso Structure; el videoclip no está preparado.')
    }

    useStore.setState({
      directorStoryProductionHandoff: {
        workspace,
        projectId: target.id,
        productionId: production.id,
      },
    })
    director.setSettingsOpen(false)
    director.setDashboardOpen(false)
    director.setMediaFilter('all')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return storyResult(
      workspace,
      target,
      'overview',
      `He preparado “${production.title}” en Music Video Director con la canción “${candidate.displayName || candidate.title || candidate.name}” y el cue “${resolvedCue.title}”. Estado: preparado. No lo he encolado ni iniciado.`,
      { destination: 'director', productionId: production.id },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function startDirectorProduction(
  action: StartDirectorProductionCommand,
): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Iniciar una producción de Director requiere confirm=true porque consume cómputo.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, api] = await Promise.all([
    import('./store'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const stories = useStoryStore.getState()
  if (stories.libraryConflicts.length) throw new Error('Story Lab tiene un conflicto pendiente; resuélvelo antes de iniciar la producción.')
  const target = action.targetStoryTitle
    ? Object.values(stories.projects).find(item => normalizeName(item.title) === normalizeName(action.targetStoryTitle))
    : stories.project
  if (!target) throw new Error(`No existe la historia “${action.targetStoryTitle}” en este workspace.`)
  if (stories.activeProjectOperations[target.id]) throw new Error(`La historia “${target.title}” tiene una operación activa.`)

  const director = useStore.getState()
  const handoff = director.directorStoryProductionHandoff
  if (!handoff || handoff.workspace !== workspace || handoff.projectId !== target.id) {
    throw new Error(`No hay una producción de “${target.title}” preparada por el Wizard en Director. Usa stage_story_video o stage_story_music_video primero.`)
  }
  const production = target.productions.find(item => item.id === handoff.productionId)
  if (!production || (production.kind !== 'film' && production.kind !== 'trailer' && production.kind !== 'music_video')) {
    throw new Error('La producción preparada ya no existe en el historial de Story Lab.')
  }
  if (action.kind && production.kind !== action.kind) {
    throw new Error(`La producción preparada es ${production.kind}, no ${action.kind}.`)
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
      `La producción “${production.title}” ya estaba iniciada en Director (pipeline ${existingPipelineId}); no la he duplicado.`,
      { destination: 'director', pipelineId: existingPipelineId, productionId: production.id, productionTitle: production.title },
    )
  }
  if (director.pipelineId) {
    throw new Error(`Director ya está vinculado al pipeline ${director.pipelineId}; no iniciaré otro sobre el mismo borrador.`)
  }
  if (production.kind === 'music_video') {
    if (director.directorSkill !== 'music_video' || director.directorStep !== 'structure' || !director.directorSceneDescription.trim()) {
      throw new Error('El videoclip preparado ya no está listo en el paso Structure de Music Video Director. Vuelve a prepararlo antes de lanzarlo.')
    }
  } else if (director.directorSkill !== 'short_film' || director.directorStep !== 'style' || !director.directorSceneDescription.trim()) {
    throw new Error('El borrador exacto de Story ya no está listo en el paso Style de Short Film Director. Vuelve a prepararlo antes de lanzarlo.')
  }
  if (director.directorLoading) throw new Error('Director ya está procesando otra operación; espera a que termine antes de iniciar.')

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
    if (!pipelineId) throw new Error('Director no devolvió un pipelineId; la producción no se inició.')

    let linkWarning = ''
    try {
      let saved = false
      for (let attempt = 0; attempt < 2 && !saved; attempt += 1) {
        const remote = await api.fetchStoryLibrary(workspace)
        const remoteProject = remote.projects[target.id]
        const remoteProduction = remoteProject?.productions.find(item => item.id === production.id)
        if (!remoteProject || !remoteProduction) throw new Error('La producción ya no existe en la biblioteca remota.')
        const linkedProject = normalizeStoryProject({
          ...remoteProject,
          revision: remoteProject.revision + 1,
          updatedAt: new Date().toISOString(),
          productions: remoteProject.productions.map(item => item.id === production.id ? {
            ...item,
            targetSnapshot: { ...(item.targetSnapshot || {}), pipelineId },
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
      linkWarning = ` El pipeline sí está en marcha, pero no pude enlazarlo al historial de Story Lab: ${(error as Error).message}`
    }
    return storyResult(
      workspace,
      target,
      'overview',
      `He iniciado “${production.title}” en Director con el pipeline real ${pipelineId}. Está en marcha; todavía no está terminado.${linkWarning}`,
      { destination: 'director', pipelineId, productionId: production.id, productionTitle: production.title },
    )
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}
