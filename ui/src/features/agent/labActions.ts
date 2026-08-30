import { useStore } from '../../stores/useStore'
import type {
  AgentCreateComicAction,
  AgentGenerateStorySectionAction,
  AgentCreateSeriesEpisodeAction,
  AgentCreateStoryAction,
  AgentUpdateStoryAction,
  AgentCreativeCharacter,
  AgentCreativeLocation,
} from './agentActions'
import { notifyAgentStoryDraft, openAgentSeriesSection, openAgentStorySection } from './agentUiBus'

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

export async function updateFilledStory(action: AgentUpdateStoryAction): Promise<string> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { changedSections }, api] = await Promise.all([
    import('../stories/store'),
    import('../stories/model'),
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
  showLab('stories')
  const section = sections.includes('structure')
    ? 'structure'
    : sections.includes('characters')
      ? 'characters'
      : sections.includes('world')
        ? 'world'
        : 'overview'
  openAgentStorySection(section)
  return `He actualizado y guardado “${project.title}”: ${sections.join(', ')}. Está abierto en Story Lab → ${section}.`
}

export async function generateStorySectionDraft(
  action: AgentGenerateStorySectionAction,
  onStep?: (message: string) => void,
): Promise<string> {
  if (!action.confirm) throw new Error('Generar una propuesta de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore }, { resolveStoryWritingProvider }, api] = await Promise.all([
    import('../stories/store'),
    import('../stories/provider'),
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
  showLab('stories')
  const visibleSection = action.scope === 'all' ? 'overview' : action.scope
  openAgentStorySection(visibleSection)
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
    notifyAgentStoryDraft(project.id)
    return `La propuesta de ${action.scope} para “${project.title}” está lista en Story Lab. Revísala y elige qué cambios aplicar; todavía no he modificado ni aprobado el canon.`
  } finally {
    useStoryStore.getState().endProjectOperation(project.id)
  }
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

function showComics(): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter('comics')
  state.setSidebarOpen(false)
}

export async function createFilledComic(action: AgentCreateComicAction): Promise<string> {
  const [{ useComicStore }, { comicId, projectFromPlan }] = await Promise.all([
    import('../comics/store'),
    import('../comics/model'),
  ])
  const characters = (action.characters.length ? action.characters : [{
    name: 'Protagonista',
    role: 'Protagonista',
    personality: '',
    desire: '',
    flaw: '',
    appearance: 'Silueta clara y reconocible',
    voice: '',
  }]).map((character, index) => ({
    id: comicId('character'),
    name: character.name || `Personaje ${index + 1}`,
    description: character.appearance || character.role || character.name,
    role: character.role || (index ? 'Secundario' : 'Protagonista'),
    personality: character.personality,
    motivation: character.desire,
    voice: character.voice,
    wardrobe: character.appearance || 'Vestuario fijo y reconocible durante todo el cómic.',
    visualNotes: [character.appearance, action.styleName, 'Silueta, escala y paleta constantes.'].filter(Boolean).join('. '),
    negativePrompt: 'inconsistent face, changed wardrobe, duplicate character, extra limbs, unreadable silhouette',
    referenceAssetIds: [],
    locked: false,
  }))
  const panels = action.panels.length ? action.panels : [
    { caption: action.synopsis || action.title, dialogue: '', sfx: '', scene: action.synopsis },
  ]
  const ending = panels.at(-1)?.dialogue
    || panels.at(-1)?.caption
    || `El conflicto de “${action.title}” se resuelve con una consecuencia visual clara.`
  const castBible = characters.map(character => [
    `${character.name} (${character.role || 'personaje'})`,
    character.description,
    character.personality,
    character.motivation,
  ].filter(Boolean).join(': ')).join('\n')
  const storyContext = [
    `Premisa: ${action.synopsis || action.title}`,
    `Personajes:\n${castBible}`,
    `Progresión: ${panels.map((panel, index) => `${index + 1}. ${panel.scene || panel.caption || panel.dialogue}`).join(' → ')}`,
    `Final: ${ending}`,
  ].join('\n\n')
  const worldContext = [
    `Universo visual de “${action.title}”.`,
    action.synopsis,
    `Mantener localizaciones, época, escala y utilería coherentes durante las ${panels.length} viñetas.`,
  ].filter(Boolean).join(' ')
  const forbiddenElements = [
    'No cambiar el diseño, la edad aparente, la paleta ni el vestuario de los personajes entre viñetas.',
    'No añadir texto, bocadillos, marcos, cuadrículas, logotipos ni marcas de agua dentro de las imágenes generadas.',
    'No duplicar personajes ni introducir elementos ajenos a la escena.',
  ].join(' ')
  const planId = comicId('plan')
  const plan = {
    version: 1 as const,
    id: planId,
    title: action.title,
    logline: action.synopsis,
    synopsis: action.synopsis || action.title,
    language: action.language || 'Español',
    styleBible: action.styleName || 'Tira cómica clara, 4 viñetas',
    characters,
    storyStructure: [{
      pageNumber: 1,
      stage: 'Planteamiento, complicación y remate',
      goal: action.synopsis || `Contar “${action.title}” con una progresión clara y legible.`,
      turningPoint: ending,
    }],
    pages: [{
      pageNumber: 1,
      layoutHint: 'grid' as const,
      panels: panels.map((panel, index) => {
        const beat = panel.scene || panel.caption || panel.dialogue || action.synopsis
        const who = characters.map(character => `${character.name}: ${character.description}`).join('; ')
        return {
          id: comicId('panel-plan'),
          order: index + 1,
          narrativeRole: `Viñeta ${index + 1}`,
          sceneDescription: beat,
          imagePrompt: [
            `Single comic panel for "${action.title}".`,
            action.styleName,
            beat ? `Scene: ${beat}.` : '',
            who ? `Characters: ${who}.` : '',
            'Clear acting, readable silhouette, no lettering, no balloons, no captions.',
          ].filter(Boolean).join(' '),
          characters: characters.map(character => character.id),
          framing: 'medium',
          dialogue: panel.dialogue ? [{ text: panel.dialogue, bubbleType: 'speech' as const }] : [],
          captions: panel.caption ? [panel.caption] : [],
          soundEffects: panel.sfx ? [panel.sfx] : [],
          continuityNotes: `Conservar identidad, vestuario, paleta, iluminación y eje espacial respecto a la viñeta ${Math.max(1, index)}.`,
        }
      }),
    }],
  }
  const project = projectFromPlan(plan)
  if (action.styleName) {
    project.style = {
      ...project.style,
      name: action.styleName,
      promptSuffix: `${action.styleName}. Consistent character design, readable acting, coherent palette and continuity across panels.`,
    }
  }
  const studio = useStore.getState()
  const provider = studio.productionProfile.image.provider === 'minimax' ? 'minimax' as const : 'maestro' as const
  const imageModel = studio.productionProfile.image.model
    || studio.selectedModelPerMode.image
    || ''
  project.director = {
    planId,
    provider,
    imageModel,
    input: {
      useGlobalProfile: true,
      premise: action.synopsis || action.title,
      storyContext,
      productionMode: 'comic',
      pageCount: 1,
      language: action.language || 'Español',
      format: project.format.preset,
      panelsPerPage: panels.length,
      genre: 'Comedy',
      tone: 'Warm',
      audience: 'General',
      artStyle: action.styleName,
      worldContext,
      forbiddenElements,
      dialogueDensity: 'medium',
      provider,
      imageModel,
      characters,
      ending,
    },
    plan,
    completedPanelIds: [],
    panelJobs: {},
    scriptVersion: 1,
    scriptApprovedAt: new Date().toISOString(),
  }
  useComicStore.getState().setProject(project)
  useComicStore.setState({ dirty: true })
  showComics()
  return `He abierto Comics con “${project.title}”, ${characters.length} personajes y ${panels.length} viñetas con globos. El plan de Director está listo. Dime **lánzalo** para dibujar las viñetas, o pulsa **Generate all images** en Comic Director.`
}

export async function generateFilledComicArtwork(
  onProgress?: (message: string) => void,
): Promise<string> {
  showComics()
  const [{ useComicStore }, { comicId }, { generateDirectorArtwork }] = await Promise.all([
    import('../comics/store'),
    import('../comics/model'),
    import('../comics/generateArtwork'),
  ])
  const state = useComicStore.getState()
  if (!state.project.director) {
    const project = state.project
    const characters = (project.characters.length ? project.characters : [{
      id: comicId('character'),
      name: 'Protagonista',
      description: 'Silueta clara',
      locked: false,
    }]).map(character => ({
      ...character,
      role: character.role || 'Personaje principal',
      personality: character.personality || 'Expresivo y coherente con el tono del cómic.',
      motivation: character.motivation || project.synopsis || 'Resolver el conflicto de la historia.',
      voice: character.voice || 'Voz breve, clara y diferenciada.',
      wardrobe: character.wardrobe || character.description || 'Vestuario fijo y reconocible.',
      visualNotes: character.visualNotes || `${character.description}. Silueta, escala y paleta constantes.`,
      negativePrompt: character.negativePrompt || 'inconsistent face, changed wardrobe, duplicate character, extra limbs',
      referenceAssetIds: character.referenceAssetIds || [],
    }))
    const pages = project.pages.map((page, pageIndex) => {
      const panels = page.elements
        .filter(element => element.type === 'panel' && !element.parentId)
        .sort((left, right) => left.zIndex - right.zIndex)
      return {
        pageNumber: pageIndex + 1,
        layoutHint: 'grid' as const,
        panels: panels.map((panel, index) => {
          const texts = page.elements.filter(element => element.type === 'text' && element.parentId === panel.id)
          const captions = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'caption' || text.bubble === 'caption'))
            .map(text => text.type === 'text' ? text.content : '')
          const soundEffects = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'sound-effect' || text.bubble === 'burst'))
            .map(text => text.type === 'text' ? text.content : '')
          const dialogue = texts
            .filter(text => text.type === 'text' && (text.letteringType === 'dialogue' || text.bubble === 'speech'))
            .map(text => text.type === 'text' ? text.content : '')
            .filter(content => !captions.includes(content) && !soundEffects.includes(content))
          const beat = captions[0] || dialogue[0] || project.synopsis || project.title
          return {
            id: comicId('panel-plan'),
            order: index + 1,
            narrativeRole: `Viñeta ${index + 1}`,
            sceneDescription: beat,
            imagePrompt: [
              `Single comic panel for "${project.title}".`,
              project.style.name,
              beat ? `Scene: ${beat}.` : '',
              'Clear acting, readable silhouette, no lettering, no balloons, no captions.',
            ].filter(Boolean).join(' '),
            characters: characters.map(character => character.id),
            framing: 'medium',
            dialogue: dialogue.map(text => ({ text, bubbleType: 'speech' as const })),
            captions,
            soundEffects,
            continuityNotes: `Conservar identidad, vestuario, paleta y eje espacial respecto a la viñeta ${Math.max(1, index)}.`,
          }
        }),
      }
    })
    if (!pages.some(page => page.panels.length)) {
      throw new Error('El cómic abierto no tiene viñetas que dibujar.')
    }
    const studio = useStore.getState()
    const provider = studio.productionProfile.image.provider === 'minimax' ? 'minimax' as const : 'maestro' as const
    const imageModel = studio.productionProfile.image.model || studio.selectedModelPerMode.image || ''
    const plan = {
      version: 1 as const,
      id: comicId('plan'),
      title: project.title,
      logline: project.synopsis,
      synopsis: project.synopsis || project.title,
      language: project.language,
      styleBible: project.style.name,
      characters,
      storyStructure: pages.map((page, index) => ({
        pageNumber: page.pageNumber,
        stage: index === 0 ? 'Planteamiento y complicación' : `Desarrollo ${index + 1}`,
        goal: project.synopsis || `Hacer avanzar “${project.title}”.`,
        turningPoint: page.panels.at(-1)?.dialogue.at(-1)?.text
          || page.panels.at(-1)?.captions.at(-1)
          || `Cerrar el beat de la página ${page.pageNumber}.`,
      })),
      pages,
    }
    const storyContext = [
      `Premisa: ${project.synopsis || project.title}`,
      `Personajes: ${characters.map(character => `${character.name}: ${character.description}`).join('; ')}`,
      `Estructura: ${plan.storyStructure.map(beat => beat.turningPoint).join(' → ')}`,
    ].join('\n\n')
    useComicStore.getState().patchProject({
      characters,
      director: {
        planId: plan.id,
        provider,
        imageModel,
        input: {
          useGlobalProfile: true,
          premise: project.synopsis || project.title,
          storyContext,
          productionMode: 'comic',
          pageCount: pages.length,
          language: project.language,
          format: project.format.preset,
          panelsPerPage: Math.max(1, pages[0]?.panels.length || 4),
          genre: 'Comedy',
          tone: 'Warm',
          audience: 'General',
          artStyle: project.style.name,
          worldContext: `Universo visual de “${project.title}”. Mantener época, localizaciones, escala y utilería coherentes entre páginas.`,
          forbiddenElements: 'No cambiar identidades ni vestuario. No añadir texto, cuadrículas, marcos, logos o marcas de agua dentro de la ilustración.',
          dialogueDensity: 'medium',
          provider,
          imageModel,
          characters,
          ending: plan.storyStructure.at(-1)?.turningPoint,
        },
        plan,
        completedPanelIds: [],
        panelJobs: {},
        scriptVersion: 1,
        scriptApprovedAt: new Date().toISOString(),
      },
    })
  }
  if (!useComicStore.getState().project.director) {
    throw new Error('No hay un cómic con plan de Director abierto. Pide primero un cómic de ejemplo o crea uno con tema.')
  }
  const result = await generateDirectorArtwork({
    onProgress: (message, current, total) => {
      onProgress?.(`${message} (${current}/${total})`)
    },
  })
  if (!result.total) return 'Todas las viñetas de este cómic ya tenían dibujo.'
  return `He dibujado ${result.generated} viñetas en la cola local, una detrás de otra en la misma GPU. Aparecen dentro de cada recuadro al terminar.`
}

export async function generateComicPanelArtwork(
  pageNumber: number,
  panelNumber: number,
  onProgress?: (message: string) => void,
): Promise<string> {
  showComics()
  const [{ useComicStore }, { generateDirectorArtwork }] = await Promise.all([
    import('../comics/store'),
    import('../comics/generateArtwork'),
  ])
  if (!useComicStore.getState().project.director) {
    throw new Error('El cómic abierto no tiene un plan de Director. Crea primero el borrador completo antes de regenerar una viñeta.')
  }
  const result = await generateDirectorArtwork({
    force: true,
    target: { pageNumber, panelNumber },
    onProgress: (message, current, total) => onProgress?.(`${message} (${current}/${total})`),
  })
  return `He regenerado únicamente la viñeta ${panelNumber} de la página ${pageNumber}; las demás imágenes permanecen intactas (${result.generated}/${result.total}).`
}
