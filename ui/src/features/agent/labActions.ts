import { useStore } from '../../stores/useStore'
import type {
  AgentCreateSeriesEpisodeAction,
  AgentCreateStoryAction,
  AgentCreativeCharacter,
  AgentCreativeLocation,
} from './agentActions'
import { openAgentSeriesSection, openAgentStorySection } from './agentUiBus'

const normalizeName = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

const boundedDuration = (value: number | undefined, fallback: number): number => (
  Math.max(15, Math.min(3_600, Math.round(value || fallback)))
)

function creativeCharacters(values: AgentCreativeCharacter[]): AgentCreativeCharacter[] {
  return values.length ? values : [{
    name: 'Protagonista',
    role: 'Protagonista',
    personality: 'Ingenioso, curioso y decidido.',
    desire: 'Resolver el conflicto central.',
    flaw: 'Se precipita cuando cree tener razón.',
    appearance: 'Silueta clara, vestuario reconocible y expresiones legibles.',
    voice: 'Natural, expresiva y coherente con el tono.',
  }]
}

function creativeLocations(values: AgentCreativeLocation[]): AgentCreativeLocation[] {
  return values.length ? values : [{
    name: 'Escenario principal',
    purpose: 'Reunir a los personajes y hacer visible el conflicto.',
    description: 'Un lugar reconocible, visualmente coherente y con espacio para la acción.',
  }]
}

function outlineBeats(values: string[], premise: string, ending: string): string[] {
  if (values.length >= 3) return values
  return [
    `Inicio: ${premise || 'se presenta el deseo del protagonista y aparece una complicación.'}`,
    'Desarrollo: el plan inicial empeora el conflicto y obliga a los personajes a cambiar de estrategia.',
    `Final: ${ending || 'la decisión final resuelve el problema con una consecuencia clara y memorable.'}`,
  ]
}

function showLab(filter: 'stories' | 'series'): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter(filter)
  state.setSidebarOpen(false)
}

export async function createFilledStory(action: AgentCreateStoryAction): Promise<string> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, createStoryProject, normalizeStoryProject, storyId }, api] = await Promise.all([
    import('../stories/store'),
    import('../../api/client'),
  ])
  await useStoryStore.getState().loadWorkspace(workspace)
  const current = useStoryStore.getState()
  if (current.libraryConflicts.length) {
    throw new Error('Story Lab tiene un conflicto pendiente entre la copia local y la del workspace; resuélvelo antes de crear otra historia.')
  }

  const duplicate = Object.values(current.projects).find(project => (
    normalizeName(project.title) === normalizeName(action.title)
    && normalizeName(project.premise) === normalizeName(action.premise)
  ))
  if (duplicate) {
    useStoryStore.setState({ project: duplicate, dirty: false })
    showLab('stories')
    openAgentStorySection('overview')
    return `La historia “${duplicate.title}” ya existía; la he abierto en Story Lab → Overview.`
  }

  const base = createStoryProject(action.projectType || 'full_story')
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
    visualPrompt: `${character.appearance}. ${action.visualStyle}`.trim(),
    negativePrompt: 'inconsistent identity, duplicate character, unreadable face',
    referenceAssetIds: [], approval: 'draft' as const,
  }))
  const locations = creativeLocations(action.locations).map((location, index) => ({
    id: storyId('location'),
    name: location.name || `Localización ${index + 1}`,
    purpose: location.purpose,
    description: location.description,
    visualPrompt: `${location.description}. ${action.visualStyle}`.trim(),
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
  const project = normalizeStoryProject({
    ...base,
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
    visualStyle: action.visualStyle || 'Dirección visual cinematográfica coherente, personajes legibles y continuidad entre escenas.',
    characterVisualStyle: action.visualStyle || 'Identidades consistentes, siluetas reconocibles y expresiones claras.',
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
      visualLanguage: action.visualStyle || 'Lenguaje cinematográfico claro y consistente.',
      visualPrompt: action.visualStyle,
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
  showLab('stories')
  openAgentStorySection('overview')
  return `He creado y guardado “${project.title}” con ${characters.length} personajes, ${locations.length} localizaciones y ${beats.length} beats; está abierto en Story Lab → Overview.`
}

export async function createFilledSeriesEpisode(action: AgentCreateSeriesEpisodeAction): Promise<string> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }, seriesModel] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
    import('../series/model'),
  ])
  const store = useSeriesStore.getState()
  await store.loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()

  let library = await api.fetchSeriesLibrary(workspace)
  const requestedName = normalizeName(action.seriesTitle)
  let series = requestedName
    ? Object.values(library.seriesById).find(item => normalizeName(item.title) === requestedName)
    : library.seriesById[useSeriesStore.getState().activeSeriesId]
  const createdSeries = !series
  if (!series) {
    if (!action.createIfMissing) throw new Error(`No existe la serie “${action.seriesTitle}” y la orden no autorizó crearla.`)
    series = await api.createSeriesProject(workspace, action.seriesTitle || 'Nueva serie')
  }

  const existingEpisode = Object.values(series.episodesById).find(episode => (
    normalizeName(episode.title) === normalizeName(action.episodeTitle)
    && normalizeName(episode.premise) === normalizeName(action.episodePremise)
  ))
  if (existingEpisode) {
    await useSeriesStore.getState().reload()
    await useSeriesStore.getState().openSeries(series.id)
    useSeriesStore.getState().openEpisode(existingEpisode.id)
    showLab('series')
    openAgentSeriesSection('episode')
    return `El episodio “${existingEpisode.title}” ya existía; lo he abierto en Series Lab → Episode room.`
  }

  const characters = series.characters.length ? series.characters : creativeCharacters(action.characters).map((character, index) => ({
    ...seriesModel.createSeriesCharacter(),
    name: character.name || `Personaje ${index + 1}`,
    role: character.role || (index ? 'Secundario' : 'Protagonista'),
    personality: character.personality,
    desire: character.desire,
    need: `Aprender algo que contradice su deseo inmediato: ${character.desire || 'resolver el conflicto'}.`,
    flaw: character.flaw,
    longArc: action.seriesPremise,
    voiceAndDialogue: character.voice,
    appearance: character.appearance,
    identityLock: `${character.appearance}. Mantener identidad, edad aparente y vestuario entre episodios.`,
  }))
  const locations = series.locations.length ? series.locations : creativeLocations(action.locations).map(location => ({
    ...seriesModel.createSeriesLocation(),
    name: location.name,
    purpose: location.purpose,
    description: location.description,
  }))
  const needsSetup = createdSeries
    || !series.premise.trim()
    || !series.visualStyle.trim()
    || !series.canon.worldSummary.trim()
    || !series.characters.length
    || !series.locations.length
  if (needsSetup) {
    const patched = {
      ...series,
      title: series.title === 'Untitled series' ? action.seriesTitle : series.title,
      premise: series.premise || action.seriesPremise || action.episodePremise,
      logline: series.logline || action.seriesLogline || action.episodeLogline,
      genre: series.genre || action.genre || 'Comedia dramática',
      tone: series.tone || action.tone || 'Cinematográfico',
      visualStyle: series.visualStyle || action.visualStyle || 'Continuidad televisiva cinematográfica, composición clara y personajes consistentes.',
      characterVisualStyle: series.characterVisualStyle || action.visualStyle || 'Identidades y vestuario consistentes entre episodios.',
      cameraLanguage: series.cameraLanguage || 'Planos de situación claros, planos medios para diálogo y primeros planos para reacciones.',
      language: action.language || series.language,
      spokenLanguage: action.language || series.spokenLanguage,
      sourceMode: action.knownUniverse ? 'known_universe_experimental' as const : series.sourceMode,
      masterUniversePrompt: series.masterUniversePrompt || (action.knownUniverse
        ? `Borrador fan inspirado en ${action.seriesTitle}; conservar los rasgos generales sin afirmar derechos sobre la obra original.`
        : ''),
      rightsNote: series.rightsNote || (action.knownUniverse
        ? 'Borrador creativo no oficial. Verifica los derechos necesarios antes de publicar o monetizar.'
        : ''),
      canon: {
        ...series.canon,
        worldSummary: series.canon.worldSummary || action.worldSummary || action.seriesPremise || action.episodePremise,
        immutableRules: series.canon.immutableRules.length ? series.canon.immutableRules : [{
          id: seriesModel.seriesId('fact'),
          description: 'Mantener personalidades, relaciones, espacios y consecuencias coherentes entre episodios.',
          status: 'draft' as const,
        }],
        themes: series.canon.themes.length ? series.canon.themes : [action.theme || 'Relaciones y consecuencias cotidianas'],
        approval: 'draft' as const,
        approvedAt: undefined,
      },
      characters,
      locations,
      updatedAt: new Date().toISOString(),
    }
    series = await api.saveSeriesProject(workspace, patched, series.revision)
  }
  let approvedCanon = false
  if (series.canon.approval !== 'approved') {
    series = await api.approveSeriesCanon(workspace, series.id, series.canon.revision)
    approvedCanon = true
  }

  const beats = outlineBeats(action.outlineBeats, action.episodePremise, action.ending)
  const createdEpisode = await api.createSeriesEpisode(
    workspace,
    series.id,
    series.seasons[0]?.id,
    {
      title: action.episodeTitle || `Episodio ${Object.keys(series.episodesById).length + 1}`,
      premise: action.episodePremise,
      logline: action.episodeLogline,
      targetDurationSeconds: boundedDuration(action.targetDurationSeconds, series.defaultEpisodeDurationSeconds),
      status: 'outline',
      outline: { beats },
    },
  )

  library = await api.fetchSeriesLibrary(workspace)
  series = library.seriesById[series.id]
  useSeriesStore.setState({ hydrated: false })
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(createdEpisode.id)
  showLab('series')
  openAgentSeriesSection('episode')
  const canonResult = approvedCanon ? 'preparado y aprobado el canon editable necesario, y ' : ''
  return `He ${createdSeries ? 'creado la serie, ' : ''}${canonResult}guardado el episodio “${createdEpisode.title}” con ${beats.length} beats; está abierto en Series Lab → Episode room.`
}
