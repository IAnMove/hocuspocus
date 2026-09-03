import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import {
  boundedDuration,
  creativeCharacters,
  creativeLocations,
  normalizeName,
  outlineBeats,
} from '../../lib/labHelpers'
import { useStore } from '../../stores/useStore'
import { compileProviderPrompt, mergeLanguageIntent } from '../../lib/languageIntent'
import { COMIC_HANDOFF_STORAGE_KEY } from '../comics/provenance'
import { buildSeriesComicHandoff } from './comicHandoff'
import { resolveSeriesLanguageIntent, seriesLanguageIntentAffectsCanon } from './languageIntent'
import type {
  ApplySeriesPlanCommand,
  AssembleSeriesEpisodeCommand,
  CommitSeriesCanonCommand,
  CreateSeriesEpisodeCommand,
  GenerateSeriesPlanCommand,
  RenderSeriesShotsCommand,
  ReviewSeriesAttemptsCommand,
  StageSeriesComicCommand,
  UpdateSeriesEpisodeCommand,
} from './commands'

function seriesEpisodeResult(
  workspaceId: string,
  episode: { id: string; title: string },
  section: 'episode' | 'review',
  message: string,
  extra: {
    taskIds?: string[]
    channel?: 'series_plan' | 'series_render' | 'series_assembly' | 'series_plan_clear'
    job?: Record<string, unknown>
    reviewView?: string
  } = {},
): CommandResult {
  const entity = { kind: 'series_episode', id: episode.id, workspaceId }
  return commandResultFromSlice({
    entity,
    taskIds: extra.taskIds,
    navigationTarget: {
      destination: 'series_lab',
      section,
      entity,
      ...(extra.reviewView ? { anchor: extra.reviewView } : {}),
    },
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'series:reply',
      metadata: {
        summary: message,
        ...(extra.channel ? { channel: extra.channel } : {}),
        ...(extra.job ? { job: extra.job } : {}),
      },
    }],
  })
}

function seriesComicResult(
  workspaceId: string,
  comic: { id: string; title: string },
  provenance: Record<string, unknown>,
  message: string,
): CommandResult {
  const entity = { kind: 'comic', id: comic.id, workspaceId }
  return commandResultFromSlice({
    entity,
    navigationTarget: { destination: 'comics', entity },
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: `comic:${comic.id}`,
      metadata: {
        summary: message,
        provenance,
      },
    }],
  })
}

export async function createFilledSeriesEpisode(action: CreateSeriesEpisodeCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }, seriesModel] = await Promise.all([
    import('../../api/client'),
    import('./store'),
    import('./model'),
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
    return seriesEpisodeResult(
      workspace,
      existingEpisode,
      'episode',
      `El episodio “${existingEpisode.title}” ya existía; lo he abierto en Series Lab → Episode room.`,
    )
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
  const languageIntent = resolveSeriesLanguageIntent(series, action.language, action.languageIntent, createdSeries)
  const languageSetupChanged = seriesLanguageIntentAffectsCanon(series, languageIntent)
  const needsSetup = createdSeries
    || !series.premise.trim()
    || !series.visualStyle.trim()
    || !series.canon.worldSummary.trim()
    || !series.characters.length
    || !series.locations.length
    || languageSetupChanged
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
      language: languageIntent.contentLanguage || action.language || series.language,
      spokenLanguage: languageIntent.spokenLanguage || action.language || series.spokenLanguage,
      languageIntent,
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
  const canonResult = approvedCanon ? 'preparado y aprobado el canon editable necesario, y ' : ''
  return seriesEpisodeResult(
    workspace,
    createdEpisode,
    'episode',
    `He ${createdSeries ? 'creado la serie, ' : ''}${canonResult}guardado el episodio “${createdEpisode.title}” con ${beats.length} beats; está abierto en Series Lab → Episode room.`,
  )
}

/**
 * Stage an exact Series episode as an editable Comic project. This is a
 * preparation step only: no image provider or render job is started.
 */
export async function stageSeriesComic(action: StageSeriesComicCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Preparar un cómic desde Series Lab requiere confirm=true porque sustituye el borrador actual de Comics.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [{ useSeriesStore }, { useComicStore }, api, seriesModel] = await Promise.all([
    import('./store'), import('../comics/store'), import('../../api/client'), import('./model'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  // The backend library is authoritative at the moment of staging. The
  // adapter receives both IDs explicitly and never reconstructs them from a
  // title or from whichever project happens to be active in another tab.
  const library = seriesModel.normalizeSeriesLibrary(
    await api.fetchSeriesLibrary(workspace), workspace,
  )
  const handoff = buildSeriesComicHandoff(library, {
    workspaceId: workspace,
    seriesId: action.seriesId,
    episodeId: action.episodeId,
    title: action.title,
    pageCount: action.pageCount,
    panelsPerPage: action.panelsPerPage,
    actor: action.actor || 'user',
  })
  useComicStore.getState().setProject(handoff.comic)
  useComicStore.setState({ dirty: true })
  try {
    window.localStorage.removeItem('maestro-story-comic-draft')
    window.localStorage.removeItem('maestro-story-comic-auto-start')
    window.localStorage.setItem(COMIC_HANDOFF_STORAGE_KEY, JSON.stringify({
      projectId: handoff.comic.id,
      request: handoff.request,
    }))
    window.dispatchEvent(new CustomEvent('maestro:comic-staged', { detail: handoff.request }))
  } catch {
    // Browser storage is only a reload aid; the in-memory project remains
    // available even when a privacy policy blocks localStorage.
  }
  const app = useStore.getState()
  app.setSettingsOpen(false)
  app.setDashboardOpen(false)
  app.setMediaFilter('comics')
  app.setSidebarMode('director')
  app.setDirectorSkill('comic')
  app.setSidebarOpen(true)
  window.dispatchEvent(new Event('maestro:director-open'))
  return seriesComicResult(
    workspace,
    handoff.comic,
    handoff.provenance as unknown as Record<string, unknown>,
    `He preparado “${handoff.comic.title}” desde el episodio exacto “${handoff.episode.title}” en Comic Director. El borrador queda editable y no he generado imágenes.`,
  )
}

export async function updateSeriesEpisode(action: UpdateSeriesEpisodeCommand): Promise<CommandResult> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; renombra una para poder elegirla sin ambigüedad.`)
  let series = seriesMatches[0]
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

  if (action.languageIntent) {
    const languageIntent = mergeLanguageIntent(series.languageIntent, action.languageIntent)
    series = await api.saveSeriesProject(workspace, {
      ...series,
      language: languageIntent.contentLanguage || series.language,
      spokenLanguage: languageIntent.spokenLanguage || series.spokenLanguage,
      languageIntent,
      updatedAt: new Date().toISOString(),
    }, series.revision)
    useSeriesStore.setState({ hydrated: false })
    await useSeriesStore.getState().loadWorkspace(workspace)
  }

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
  return seriesEpisodeResult(
    workspace,
    verified,
    'episode',
    `He actualizado y guardado “${verified.title}” en la serie “${saved.title}”; conserva ${verified.script.length} escenas y ${verified.shots.length} tomas existentes.`,
  )
}

export async function generateSeriesPlan(action: GenerateSeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Generar un plan de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
  ])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const seriesMatches = action.seriesTitle
    ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle))
    : []
  if (seriesMatches.length > 1) throw new Error(`Hay varias series tituladas “${action.seriesTitle}”; el destino no es inequívoco.`)
  let series = seriesMatches[0]
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
  if (action.languageIntent) {
    const languageIntent = mergeLanguageIntent(series.languageIntent, action.languageIntent, {
      contentLanguage: series.language,
      spokenLanguage: series.spokenLanguage,
    })
    const language = languageIntent.contentLanguage || series.language
    const spokenLanguage = languageIntent.spokenLanguage || series.spokenLanguage
    if (
      JSON.stringify(languageIntent) !== JSON.stringify(series.languageIntent)
      || language !== series.language
      || spokenLanguage !== series.spokenLanguage
    ) {
      series = await api.saveSeriesProject(workspace, {
        ...series,
        language,
        spokenLanguage,
        languageIntent,
        updatedAt: new Date().toISOString(),
      }, series.revision)
      useSeriesStore.setState({ hydrated: false })
      await useSeriesStore.getState().loadWorkspace(workspace)
    }
  }
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const job = await api.startSeriesPlan(workspace, series.id, episode.id, {
    scope: action.scope,
    instruction: compileProviderPrompt(
      action.instruction,
      mergeLanguageIntent(series.languageIntent, action.languageIntent),
      { medium: 'series' },
    ),
    writingProvider: series.provider.writingProvider,
    writingModel: series.provider.writingModel,
    writingBaseUrl: series.provider.writingBaseUrl,
  })
  if (job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('Series Lab devolvió un job asociado a otro episodio; no lo mostraré como correcto.')
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'episode',
    `He iniciado el plan ${action.scope} de “${episode.title}” (${job.jobId}). El progreso y la propuesta recuperable están abiertos en Series Lab → Episode room; todavía no se ha aplicado ni renderizado.`,
    { taskIds: [job.jobId], channel: 'series_plan', job: job as unknown as Record<string, unknown> },
  )
}

export async function applySeriesPlan(action: ApplySeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Aplicar una propuesta de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
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
  return seriesEpisodeResult(
    workspace,
    applied,
    'episode',
    `He aplicado el plan ${job.jobId} a “${applied.title}”: ${applied.outline.beats.length} beats, ${applied.script.length} escenas y ${applied.shots.length} tomas. No he renderizado ni comprometido el delta de canon.`,
    { taskIds: [job.jobId], channel: 'series_plan_clear' },
  )
}

export async function renderSeriesShots(action: RenderSeriesShotsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Renderizar tomas de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
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
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `He encolado ${eligible.length} shots de “${episode.title}” (${job.jobId}) en modo ${action.mode}. El progreso recuperable está abierto en Series Lab → Render & review.`,
    { taskIds: [job.jobId], channel: 'series_render', job: job as unknown as Record<string, unknown> },
  )
}

export async function reviewSeriesAttempts(action: ReviewSeriesAttemptsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Revisar intentos de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
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
    return seriesEpisodeResult(
      workspace,
      episode,
      'review',
      `He aprobado ${selections.length} intento${selections.length === 1 ? '' : 's'} en “${episode.title}” y he abierto Render & Review.`,
    )
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
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `He rechazado el intento ${attempt.id} del shot ${shot.order} en “${episode.title}” y he abierto Render & Review.`,
  )
}

export async function assembleSeriesEpisode(action: AssembleSeriesEpisodeCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Ensamblar un episodio de Series Lab requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([
    import('../../api/client'),
    import('./store'),
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
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `He iniciado el ensamblado ordenado de ${episode.shots.length} shots de “${episode.title}” (${job.jobId}). El progreso recuperable y la descarga están abiertos en Render & Review; no he comprometido el delta de canon.`,
    { taskIds: [job.jobId], channel: 'series_assembly', job: job as unknown as Record<string, unknown> },
  )
}

export async function commitSeriesCanonDelta(action: CommitSeriesCanonCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Comprometer cambios de canon requiere confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([import('../../api/client'), import('./store')])
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
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `He marcado ${selected.length} cambio${selected.length === 1 ? '' : 's'} de canon como ${value === 'accepted' ? 'aceptados' : 'rechazados'} en “${episode.title}”. Los demás permanecen pendientes.`,
    { reviewView: 'finish' },
  )
}
