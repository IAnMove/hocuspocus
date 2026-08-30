import { useStore } from '../../stores/useStore'
import type {
  AgentApplyStoryProposalAction,
  AgentApproveStorySectionAction,
  AgentCreateComicAction,
  AgentGenerateStorySectionAction,
  AgentGenerateSeriesPlanAction,
  AgentApplySeriesPlanAction,
  AgentRenderSeriesShotsAction,
  AgentReviewSeriesAttemptsAction,
  AgentAssembleSeriesEpisodeAction,
  AgentCommitSeriesCanonAction,
  AgentStageStoryComicAction,
  AgentStageStoryVideoAction,
  AgentUpdateSeriesEpisodeAction,
  AgentCreateSeriesEpisodeAction,
  AgentCreateStoryAction,
  AgentUpdateStoryAction,
  AgentCreativeCharacter,
  AgentCreativeLocation,
} from './agentActions'
import { clearAgentSeriesPlanJob, notifyAgentSeriesAssemblyJob, notifyAgentSeriesPlanJob, notifyAgentSeriesRenderJob, notifyAgentStoryDraft, openAgentSeriesReviewView, openAgentSeriesSection, openAgentStorySection } from './agentUiBus'

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

export async function applyStoredStoryProposal(action: AgentApplyStoryProposalAction): Promise<string> {
  if (!action.confirm) throw new Error('Aplicar una propuesta de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, { changedSections, normalizeStoryCharacter }, api] = await Promise.all([
    import('../stories/store'),
    import('../stories/model'),
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
  showLab('stories')
  const reviewSections = new Set(['overview', 'world', 'characters', 'relationships', 'structure'])
  const visibleSection = typeof saved.scope === 'string' && reviewSections.has(saved.scope)
    ? saved.scope as 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
    : 'overview'
  openAgentStorySection(visibleSection)
  notifyAgentStoryDraft(project.id)
  return `He aplicado y guardado la propuesta de “${project.title}” en: ${sections.join(', ')}. Sus aprobaciones afectadas vuelven a borrador.`
}

export async function approveStorySection(action: AgentApproveStorySectionAction): Promise<string> {
  if (!action.confirm) throw new Error('Aprobar una sección de Story Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject }, { changedSections }, api] = await Promise.all([
    import('../stories/store'),
    import('../stories/model'),
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
    showLab('stories')
    openAgentStorySection(action.section)
    return `Story Lab → ${action.section} ya estaba aprobado en la versión actual de “${target.title}”.`
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
  showLab('stories')
  openAgentStorySection(action.section)
  return `He validado, aprobado y guardado Story Lab → ${action.section} para “${project.title}”.`
}

export async function stageStoryComic(action: AgentStageStoryComicAction): Promise<string> {
  if (!action.confirm) throw new Error('Preparar una adaptación de cómic requiere confirm=true porque sustituye el borrador actual de Comics.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, { useComicStore }, api] = await Promise.all([
    import('../stories/store'),
    import('../stories/adaptations'),
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
    return `He preparado “${comic.title}” como capítulo editable de ${action.pageCount} páginas × ${action.panelsPerPage} viñetas en Comic Director. No he generado imágenes.`
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
  }
}

export async function stageStoryVideo(action: AgentStageStoryVideoAction): Promise<string> {
  if (!action.confirm) throw new Error('Preparar una producción de vídeo requiere confirm=true porque sustituye el borrador actual de Director.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useStoryStore, normalizeStoryProject, storyId }, adaptations, api] = await Promise.all([
    import('../stories/store'), import('../stories/adaptations'), import('../../api/client'),
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
    director.setMediaFilter('all')
    director.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return `He preparado “${title}” (${duration}s) en Short Film Director con el canon y las referencias aprobadas. No he iniciado ninguna generación.`
  } finally {
    useStoryStore.getState().endProjectOperation(target.id)
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

export async function updateSeriesEpisode(action: AgentUpdateSeriesEpisodeAction): Promise<string> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; renombra una para poder elegirla sin ambigüedad.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa que modificar.')

  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) {
    throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; usa un título inequívoco antes de modificarlos.`)
  }
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o un único episodio para poder inferir el destino.`)

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  useSeriesStore.getState().updateEpisode(episode.id, current => ({
    ...current,
    title: action.episodeTitle || current.title,
    premise: action.episodePremise || current.premise,
    logline: action.episodeLogline || current.logline,
    targetDurationSeconds: action.targetDurationSeconds ?? current.targetDurationSeconds,
    outline: action.outlineBeats.length ? { beats: action.outlineBeats } : current.outline,
  }))
  const saved = await useSeriesStore.getState().saveNow()
  const verified = saved?.episodesById[episode.id]
  if (!verified) throw new Error(`Series Lab no devolvió el episodio “${episode.title}” tras guardarlo.`)
  if (action.episodeTitle && verified.title !== action.episodeTitle) throw new Error('El backend no confirmó el nuevo título del episodio.')
  if (action.episodePremise && verified.premise !== action.episodePremise) throw new Error('El backend no confirmó la nueva premisa del episodio.')
  if (action.episodeLogline && verified.logline !== action.episodeLogline) throw new Error('El backend no confirmó la nueva logline del episodio.')
  if (action.outlineBeats.length && JSON.stringify(verified.outline.beats) !== JSON.stringify(action.outlineBeats)) {
    throw new Error('El backend no confirmó la nueva estructura del episodio.')
  }
  showLab('series')
  openAgentSeriesSection('episode')
  return `He actualizado y guardado “${verified.title}” en la serie “${saved.title}”; conserva ${verified.script.length} escenas y ${verified.shots.length} tomas existentes.`
}

export async function generateSeriesPlan(action: AgentGenerateSeriesPlanAction): Promise<string> {
  if (!action.confirm) throw new Error('Generar un plan de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa que planificar.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; el destino no es inequívoco.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o único.`)
  if (!episode.premise.trim()) throw new Error(`“${episode.title}” necesita una premisa antes de planificarse.`)
  if (action.scope === 'shots' && !episode.script.length) {
    throw new Error('Regenerar shots requiere un guion existente; genera script o complete primero.')
  }

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  showLab('series')
  openAgentSeriesSection('episode')
  const job = await api.startSeriesPlan(workspace, series.id, episode.id, {
    scope: action.scope,
    instruction: action.instruction,
    writingProvider: series.provider.writingProvider,
    writingModel: series.provider.writingModel,
    writingBaseUrl: series.provider.writingBaseUrl,
  })
  if (job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('Series Lab devolvió un job asociado a otro episodio; no lo mostraré como correcto.')
  }
  notifyAgentSeriesPlanJob(job)
  return `He iniciado el plan ${action.scope} de “${episode.title}” (${job.jobId}). El progreso y la propuesta recuperable están abiertos en Series Lab → Episode room; todavía no se ha aplicado ni renderizado.`
}

export async function applySeriesPlan(action: AgentApplySeriesPlanAction): Promise<string> {
  if (!action.confirm) throw new Error('Aplicar una propuesta de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa para aplicar la propuesta.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; el destino no es inequívoco.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o único.`)

  const job = action.jobId
    ? await api.fetchSeriesPlanJob(action.jobId)
    : (await api.fetchSeriesPlanRecovery(workspace)).jobs
        .filter(item => item.seriesId === series.id && item.episodeId === episode.id && item.status === 'completed' && item.episodeResult)
        .sort((left, right) => Number(right.updatedAt || right.finishedAt || 0) - Number(left.updatedAt || left.finishedAt || 0))[0]
  if (!job) throw new Error(`No hay una propuesta completada y recuperable para “${episode.title}”.`)
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('El job indicado pertenece a otro workspace, serie o episodio; no se aplicará.')
  }
  if (job.status !== 'completed' || !job.episodeResult) {
    throw new Error(`El job ${job.jobId} está ${job.status}; sólo se puede aplicar una propuesta completada.`)
  }
  const applied = await api.applySeriesPlanJob(job.jobId, job.episodeResult)
  if (applied.id !== episode.id) throw new Error('Series Lab aplicó la propuesta a un episodio inesperado; recarga antes de continuar.')
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  clearAgentSeriesPlanJob(episode.id)
  showLab('series')
  openAgentSeriesSection('episode')
  return `He aplicado el plan ${job.jobId} a “${applied.title}”: ${applied.outline.beats.length} beats, ${applied.script.length} escenas y ${applied.shots.length} tomas. No he renderizado ni comprometido el delta de canon.`
}

export async function renderSeriesShots(action: AgentRenderSeriesShotsAction): Promise<string> {
  if (!action.confirm) throw new Error('Renderizar tomas de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa que renderizar.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; el destino no es inequívoco.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o único.`)
  if (!episode.shots.length) throw new Error(`“${episode.title}” no tiene shots; genera y aplica un plan complete primero.`)
  if (episode.shots.some(shot => shot.dialogueBeats.length > 0) && !series.bestEffortLipSyncAcknowledged) {
    throw new Error('Este episodio tiene diálogo. Marca primero “I understand lip sync is best-effort” en Series Lab; el Wizard no puede inferir ese consentimiento.')
  }

  const byId = new Map(episode.shots.map(shot => [shot.id, shot]))
  if (action.mode === 'selected') {
    const unknown = action.shotIds.filter(id => !byId.has(id))
    if (unknown.length) throw new Error(`Shots desconocidos: ${unknown.join(', ')}.`)
    const approved = action.shotIds.filter(id => Boolean(byId.get(id)?.approvedAttemptId))
    if (approved.length) throw new Error(`Los shots ya aprobados no se vuelven a renderizar: ${approved.join(', ')}.`)
  }
  const eligible = episode.shots.filter(shot => {
    if (shot.approvedAttemptId) return false
    if (action.mode === 'selected') return action.shotIds.includes(shot.id)
    if (action.mode === 'missing') return !shot.attempts.some(attempt => attempt.status === 'completed')
    if (action.mode === 'failed') return shot.attempts.some(attempt => attempt.status === 'failed')
    return true
  })
  if (!eligible.length) throw new Error(`No hay shots elegibles para el modo ${action.mode}.`)

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const current = useSeriesStore.getState().library.seriesById[series.id] || series
  const job = await api.startSeriesRender(workspace, series.id, episode.id, {
    mode: action.mode,
    shotIds: action.mode === 'selected' ? eligible.map(shot => shot.id) : undefined,
    seed: action.seed === -1 ? undefined : action.seed,
    settings: current.provider.videoSettings,
  })
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('Series Lab devolvió un render job para otro destino; no se mostrará como correcto.')
  }
  notifyAgentSeriesRenderJob(job)
  showLab('series')
  openAgentSeriesSection('review')
  return `He encolado ${eligible.length} shots de “${episode.title}” (${job.jobId}) en modo ${action.mode}. El progreso recuperable está abierto en Series Lab → Render & review.`
}

export async function reviewSeriesAttempts(action: AgentReviewSeriesAttemptsAction): Promise<string> {
  if (!action.confirm) throw new Error('Revisar intentos de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa cuyos intentos revisar.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; el destino no es inequívoco.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o único.`)

  const shotsByOrder = new Map<number, typeof episode.shots[number]>()
  for (const shot of episode.shots) {
    if (shotsByOrder.has(shot.order)) throw new Error(`El episodio tiene más de un shot con el número ${shot.order}; no se puede resolver de forma segura.`)
    shotsByOrder.set(shot.order, shot)
  }
  const selectedShots = action.scope === 'all_latest'
    ? episode.shots
    : action.shotNumbers.map(number => {
        const shot = shotsByOrder.get(number)
        if (!shot) throw new Error(`No existe el shot ${number} en “${episode.title}”.`)
        return shot
      })

  if (action.decision === 'approve') {
    const selections = selectedShots.flatMap(shot => {
      const attempt = action.attemptId
        ? shot.attempts.find(item => item.id === action.attemptId)
        : [...shot.attempts].reverse().find(item => (
            item.status === 'completed'
            && item.reviewDecision !== 'rejected'
            && item.outputAssetIds.some(id => Boolean(series.assets[id]))
          ))
      if (!attempt) {
        if (action.attemptId) throw new Error(`El intento ${action.attemptId} no pertenece al shot ${shot.order}.`)
        if (action.scope === 'selected_latest') throw new Error(`El shot ${shot.order} no tiene un intento completado y reproducible que aprobar.`)
        return []
      }
      if (attempt.status !== 'completed' || attempt.reviewDecision === 'rejected') {
        throw new Error(`El intento ${attempt.id} del shot ${shot.order} no es aprobable.`)
      }
      if (!attempt.outputAssetIds.some(id => Boolean(series.assets[id]))) {
        throw new Error(`El intento ${attempt.id} del shot ${shot.order} no tiene un asset reproducible.`)
      }
      return attempt.id === shot.approvedAttemptId ? [] : [{ shotId: shot.id, attemptId: attempt.id }]
    })
    if (!selections.length) throw new Error('No hay nuevos intentos elegibles que aprobar; las tomas resueltas ya están aprobadas o no tienen vídeo válido.')
    const result = await api.approveSeriesAttemptsBulk(workspace, series.id, episode.id, selections)
    if (result.seriesId !== series.id || result.episodeId !== episode.id) {
      throw new Error('Series Lab aprobó intentos para otro destino; recarga antes de continuar.')
    }
    await useSeriesStore.getState().reload()
    await useSeriesStore.getState().openSeries(series.id)
    useSeriesStore.getState().openEpisode(episode.id)
    showLab('series')
    openAgentSeriesSection('review')
    return `He aprobado ${selections.length} intento${selections.length === 1 ? '' : 's'} en “${episode.title}” y he abierto Render & Review.`
  }

  const shot = selectedShots[0]
  const attempt = action.attemptId
    ? shot.attempts.find(item => item.id === action.attemptId)
    : [...shot.attempts].reverse().find(item => item.status === 'completed' && item.reviewDecision !== 'rejected')
  if (!attempt) throw new Error(action.attemptId
    ? `El intento ${action.attemptId} no pertenece al shot ${shot.order}.`
    : `El shot ${shot.order} no tiene un intento completado pendiente de rechazo.`)
  if (attempt.status !== 'completed' || attempt.reviewDecision === 'rejected') {
    throw new Error(`El intento ${attempt.id} del shot ${shot.order} no se puede rechazar.`)
  }
  if (shot.approvedAttemptId === attempt.id) {
    throw new Error(`El intento ${attempt.id} ya es el aprobado del shot ${shot.order}; la UI no permite rechazar el montaje final sin elegir antes otra toma.`)
  }
  const rejectedShot = await api.rejectSeriesAttempt(workspace, series.id, episode.id, shot.id, attempt.id)
  const rejectedAttempt = rejectedShot.attempts.find(item => item.id === attempt.id)
  if (rejectedShot.id !== shot.id || rejectedAttempt?.reviewDecision !== 'rejected') {
    throw new Error('Series Lab no confirmó el rechazo solicitado; recarga antes de continuar.')
  }
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  showLab('series')
  openAgentSeriesSection('review')
  return `He rechazado el intento ${attempt.id} del shot ${shot.order} en “${episode.title}” y he abierto Render & Review.`
}

export async function assembleSeriesEpisode(action: AgentAssembleSeriesEpisodeAction): Promise<string> {
  if (!action.confirm) throw new Error('Ensamblar un episodio de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('../series/store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `No existe la serie “${action.seriesTitle}” en este workspace.`
    : 'No hay una serie activa que ensamblar.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”; el destino no es inequívoco.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `No existe el episodio “${action.targetEpisodeTitle}” en “${series.title}”.`
    : `“${series.title}” necesita un episodio activo o único.`)
  if (!episode.shots.length) throw new Error(`“${episode.title}” no tiene shots que ensamblar.`)
  const incomplete = episode.shots.filter(shot => {
    const approved = shot.attempts.find(attempt => attempt.id === shot.approvedAttemptId)
    return !approved || approved.status !== 'completed'
      || !approved.outputAssetIds.some(id => Boolean(series.assets[id]))
  })
  if (incomplete.length) {
    throw new Error(`Aprueba primero un vídeo reproducible para todos los shots. Faltan: ${incomplete.map(shot => shot.order).join(', ')}.`)
  }

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const job = await api.startSeriesEpisodeAssembly(workspace, series.id, episode.id)
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('Series Lab devolvió un ensamblado para otro destino; no se mostrará como correcto.')
  }
  notifyAgentSeriesAssemblyJob(job)
  showLab('series')
  openAgentSeriesSection('review')
  return `He iniciado el ensamblado ordenado de ${episode.shots.length} shots de “${episode.title}” (${job.jobId}). El progreso recuperable y la descarga están abiertos en Render & Review; no he comprometido el delta de canon.`
}

export async function commitSeriesCanonDelta(action: AgentCommitSeriesCanonAction): Promise<string> {
  if (!action.confirm) throw new Error('Comprometer cambios de canon requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([import('../../api/client'), import('../series/store')])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const matches = action.seriesTitle ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle)) : []
  if (matches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  const series = matches[0] || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle ? `No existe la serie “${action.seriesTitle}”.` : 'No hay una serie activa.')
  const episodeMatches = action.targetEpisodeTitle ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle)) : []
  if (episodeMatches.length > 1) throw new Error(`Hay varios episodios titulados “${action.targetEpisodeTitle}”.`)
  const activeId = useSeriesStore.getState().activeSeriesId === series.id ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0] || (!action.targetEpisodeTitle && activeId ? series.episodesById[activeId] : null) || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle ? `No existe el episodio “${action.targetEpisodeTitle}”.` : 'La serie necesita un episodio activo o único.')
  const deltaIds = [...episode.proposedCanonDelta.add.map(item => item.id), ...episode.proposedCanonDelta.change.map(item => item.id), ...episode.proposedCanonDelta.retire.map(item => item.factId)]
  if (!deltaIds.length) throw new Error(`“${episode.title}” no tiene cambios de canon propuestos.`)
  const unknown = action.itemIds.filter(id => !deltaIds.includes(id))
  if (unknown.length) throw new Error(`Cambios de canon desconocidos: ${unknown.join(', ')}.`)
  const selected = action.decision.endsWith('_all') ? deltaIds : action.itemIds
  const value = action.decision.startsWith('accept_') ? 'accepted' : 'rejected'
  const decisions = Object.fromEntries(selected.map(id => [id, value])) as Record<string, 'accepted' | 'rejected'>
  const updated = await api.commitSeriesCanon(workspace, series.id, episode.id, episode.proposedCanonDelta.baseRevision, decisions)
  if (updated.id !== series.id || !updated.episodesById[episode.id]) throw new Error('Series Lab confirmó decisiones para otro destino.')
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  showLab('series')
  openAgentSeriesSection('review')
  openAgentSeriesReviewView('finish')
  return `He marcado ${selected.length} cambio${selected.length === 1 ? '' : 's'} de canon como ${value === 'accepted' ? 'aceptados' : 'rechazados'} en “${episode.title}”. Los demás permanecen pendientes.`
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
