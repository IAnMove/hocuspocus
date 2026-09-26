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
import { clearStagedComicHandoffs, COMIC_HANDOFF_STORAGE_KEY } from '../comics/provenance'
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
import { shouldApproveCanonForExplicitEpisodeCreate } from './canonPolicy'
import {
  bulkApproveSelections,
  explicitAttemptSelection,
  missingAssemblyShotOrders,
  requireSingleShotForAttempt,
} from './shotReviewPolicy'

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
    if (!action.createIfMissing) throw new Error(`There is no series “${action.seriesTitle}” and the request did not authorize creating it.`)
    series = await api.createSeriesProject(workspace, action.seriesTitle || 'New series')
  }
  const previousApproval = series.canon.approval
  const previousWorldSummary = series.canon.worldSummary.trim()
  const previousCharacterCount = series.characters.length

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
      `The episode “${existingEpisode.title}” already existed; I opened it in Series Lab → Episode room.`,
    )
  }

  const characters = series.characters.length ? series.characters : creativeCharacters(action.characters).map((character, index) => ({
    ...seriesModel.createSeriesCharacter(),
    name: character.name || `Character ${index + 1}`,
    role: character.role || (index ? 'Secundario' : 'Protagonist'),
    personality: character.personality,
    desire: character.desire,
    need: `Learn something that contradicts their immediate desire: ${character.desire || 'resolve the conflict'}.`,
    flaw: character.flaw,
    longArc: action.seriesPremise,
    voiceAndDialogue: character.voice,
    appearance: character.appearance,
    identityLock: `${character.appearance}. Keep identity, apparent age and wardrobe consistent across episodes.`,
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
      genre: series.genre || action.genre || 'Dramedy',
      tone: series.tone || action.tone || 'Cinematic',
      visualStyle: series.visualStyle || action.visualStyle || 'Cinematic TV continuity, clear composition and consistent characters.',
      characterVisualStyle: series.characterVisualStyle || action.visualStyle || 'Consistent identities and wardrobe across episodes.',
      cameraLanguage: series.cameraLanguage || 'Clear establishing shots, medium shots for dialogue and close-ups for reactions.',
      language: languageIntent.contentLanguage || action.language || series.language,
      spokenLanguage: languageIntent.spokenLanguage || action.language || series.spokenLanguage,
      languageIntent,
      sourceMode: action.knownUniverse ? 'known_universe_experimental' as const : series.sourceMode,
      masterUniversePrompt: series.masterUniversePrompt || (action.knownUniverse
        ? `Fan draft inspired by ${action.seriesTitle}; keep the general traits without claiming rights to the original work.`
        : ''),
      rightsNote: series.rightsNote || (action.knownUniverse
        ? 'Unofficial creative draft. Check the necessary rights before publishing or monetizing.'
        : ''),
      canon: {
        ...series.canon,
        worldSummary: series.canon.worldSummary || action.worldSummary || action.seriesPremise || action.episodePremise,
        immutableRules: series.canon.immutableRules.length ? series.canon.immutableRules : [{
          id: seriesModel.seriesId('fact'),
          description: 'Keep personalities, relationships, places and consequences consistent across episodes.',
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
    const decision = shouldApproveCanonForExplicitEpisodeCreate({
      createdSeries,
      previousApproval,
      previousWorldSummary,
      previousCharacterCount,
    })
    if (!decision.approve) throw new Error(decision.reason)
    series = await api.approveSeriesCanon(workspace, series.id, series.canon.revision)
    approvedCanon = true
  }

  const beats = outlineBeats(action.outlineBeats, action.episodePremise, action.ending)
  const createdEpisode = await api.createSeriesEpisode(
    workspace,
    series.id,
    series.seasons[0]?.id,
    {
      title: action.episodeTitle || `Episode ${Object.keys(series.episodesById).length + 1}`,
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
  const canonResult = approvedCanon ? 'prepared and approved the necessary editable canon, and ' : ''
  return seriesEpisodeResult(
    workspace,
    createdEpisode,
    'episode',
    `I ${createdSeries ? 'created the series, ' : ''}${canonResult}saved the episode “${createdEpisode.title}” with ${beats.length} beats; it is open in Series Lab → Episode room.`,
  )
}

/**
 * Stage an exact Series episode as an editable Comic project. This is a
 * preparation step only: no image provider or render job is started.
 */
export async function stageSeriesComic(action: StageSeriesComicCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Preparing a comic from Series Lab requires confirm=true because it replaces the current Comics draft.')
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
    clearStagedComicHandoffs(true)
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
    `I prepared “${handoff.comic.title}” from the exact episode “${handoff.episode.title}” in Comic Director. The draft stays editable and I have not generated images.`,
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; rename one so it can be chosen unambiguously.`)
  let series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series to modify.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) {
    throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; use an unambiguous title before modifying them.`)
  }
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active episode or a single episode to infer the target.`)

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
  if (!verified) throw new Error(`Series Lab did not return the episode “${episode.title}” after saving it.`)
  if (action.episodeTitle && verified.title !== action.episodeTitle) throw new Error('The backend did not confirm the episode\'s new title.')
  if (action.episodePremise && verified.premise !== action.episodePremise) throw new Error('The backend did not confirm the episode\'s new premise.')
  if (action.episodeLogline && verified.logline !== action.episodeLogline) throw new Error('The backend did not confirm the episode\'s new logline.')
  if (action.outlineBeats.length && JSON.stringify(verified.outline.beats) !== JSON.stringify(action.outlineBeats)) {
    throw new Error('The backend did not confirm the episode\'s new structure.')
  }
  return seriesEpisodeResult(
    workspace,
    verified,
    'episode',
    `I updated and saved “${verified.title}” in the series “${saved.title}”; it keeps ${verified.script.length} existing scenes and ${verified.shots.length} existing shots.`,
  )
}

export async function generateSeriesPlan(action: GenerateSeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Generating a Series Lab plan requires confirm=true.')
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  let series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series to plan.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; the target is ambiguous.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active or single episode.`)
  if (!episode.premise.trim()) throw new Error(`“${episode.title}” needs a premise before it can be planned.`)
  if (action.scope === 'shots' && !episode.script.length) {
    throw new Error('Regenerating shots requires an existing script; generate script or complete first.')
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
    throw new Error('Series Lab returned a job for another episode; I won\'t show it as correct.')
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'episode',
    `I started the ${action.scope} plan for “${episode.title}” (${job.jobId}). Progress and the recoverable proposal are open in Series Lab → Episode room; nothing has been applied or rendered yet.`,
    { taskIds: [job.jobId], channel: 'series_plan', job: job as unknown as Record<string, unknown> },
  )
}

export async function applySeriesPlan(action: ApplySeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Applying a Series Lab proposal requires confirm=true.')
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series to apply the proposal to.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; the target is ambiguous.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active or single episode.`)

  const job = action.jobId
    ? await api.fetchSeriesPlanJob(action.jobId)
    : (await api.fetchSeriesPlanRecovery(workspace)).jobs
        .filter(item => item.seriesId === series.id && item.episodeId === episode.id && item.status === 'completed' && item.episodeResult)
        .sort((left, right) => Number(right.updatedAt || right.finishedAt || 0) - Number(left.updatedAt || left.finishedAt || 0))[0]
  if (!job) throw new Error(`There is no completed, recoverable proposal for “${episode.title}”.`)
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('The specified job belongs to another workspace, series or episode; it won\'t be applied.')
  }
  if (job.status !== 'completed' || !job.episodeResult) {
    throw new Error(`Job ${job.jobId} is ${job.status}; only a completed proposal can be applied.`)
  }
  const applied = await api.applySeriesPlanJob(job.jobId, job.episodeResult)
  if (applied.id !== episode.id) throw new Error('Series Lab applied the proposal to an unexpected episode; reload before continuing.')
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  return seriesEpisodeResult(
    workspace,
    applied,
    'episode',
    `I applied plan ${job.jobId} to “${applied.title}”: ${applied.outline.beats.length} beats, ${applied.script.length} scenes and ${applied.shots.length} shots. I have not rendered or committed the canon delta.`,
    { taskIds: [job.jobId], channel: 'series_plan_clear' },
  )
}

export async function renderSeriesShots(action: RenderSeriesShotsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Rendering Series Lab shots requires confirm=true.')
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series to render.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; the target is ambiguous.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active or single episode.`)
  if (!episode.shots.length) throw new Error(`“${episode.title}” has no shots; generate and apply a complete plan first.`)
  const staleShots = episode.shots.filter(shot => (
    (action.mode !== 'selected' || action.shotIds.includes(shot.id))
    && (shot.scriptDialogueStatus === 'stale' || shot.scriptDialogueStatus === 'manual_conflict')
  ))
  if (staleShots.length) {
    throw new Error(
      `The dialogue in the script and in ${staleShots.length} shot(s) does not match. Sync the shots in Episode before rendering.`,
    )
  }
  if (episode.shots.some(shot => shot.dialogueBeats.length > 0) && !series.bestEffortLipSyncAcknowledged) {
    throw new Error('This episode has dialogue. First tick “I understand lip sync is best-effort” in Series Lab; the Wizard cannot infer that consent.')
  }

  const byId = new Map(episode.shots.map(shot => [shot.id, shot]))
  if (action.mode === 'selected') {
    const unknown = action.shotIds.filter(id => !byId.has(id))
    if (unknown.length) throw new Error(`Shots desconocidos: ${unknown.join(', ')}.`)
    const approved = action.shotIds.filter(id => Boolean(byId.get(id)?.approvedAttemptId))
    if (approved.length) throw new Error(`Already approved shots are not re-rendered: ${approved.join(', ')}.`)
  }
  const eligible = episode.shots.filter(shot => {
    if (shot.approvedAttemptId) return false
    if (action.mode === 'selected') return action.shotIds.includes(shot.id)
    if (action.mode === 'missing') return !shot.attempts.some(attempt => attempt.status === 'completed')
    if (action.mode === 'failed') return shot.attempts.some(attempt => attempt.status === 'failed')
    return true
  })
  if (!eligible.length) throw new Error(`There are no eligible shots for mode ${action.mode}.`)

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
    throw new Error('Series Lab returned a render job for another target; it won\'t be shown as correct.')
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `I queued ${eligible.length} shots of “${episode.title}” (${job.jobId}) in ${action.mode} mode. Recoverable progress is open in Series Lab → Results.`,
    { taskIds: [job.jobId], channel: 'series_render', job: job as unknown as Record<string, unknown> },
  )
}

export async function reviewSeriesAttempts(action: ReviewSeriesAttemptsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Reviewing Series Lab attempts requires confirm=true.')
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series whose attempts to review.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; the target is ambiguous.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active or single episode.`)

  const shotsByOrder = new Map<number, typeof episode.shots[number]>()
  for (const shot of episode.shots) {
    if (shotsByOrder.has(shot.order)) throw new Error(`The episode has more than one shot numbered ${shot.order}; it cannot be resolved safely.`)
    shotsByOrder.set(shot.order, shot)
  }
  const selectedShots = action.scope === 'all_latest' || action.scope === 'replace_latest'
    ? episode.shots
    : action.shotNumbers.map(number => {
        const shot = shotsByOrder.get(number)
        if (!shot) throw new Error(`There is no shot ${number} in “${episode.title}”.`)
        return shot
      })

  if (action.decision === 'approve') {
    const hasAsset = (assetId: string) => Boolean(series.assets[assetId])
    const bulk = action.attemptId
      ? null
      : bulkApproveSelections(selectedShots, hasAsset, {
        replaceFinals: action.scope === 'replace_latest' || action.scope === 'selected_latest',
      })
    const selections = action.attemptId
      ? explicitAttemptSelection(selectedShots, action.attemptId, hasAsset)
      : bulk?.selections ?? []
    if (action.scope === 'selected_latest' && action.attemptId === '' && bulk) {
      const missing = selectedShots.filter(shot => !bulk.selections.some(item => item.shotId === shot.id)
        && !shot.approvedAttemptId)
      if (missing.length) {
        throw new Error(`Shot ${missing[0].order} has no completed, playable attempt to approve.`)
      }
    }
    if (!selections.length) throw new Error('There are no new eligible attempts to approve; resolved shots are already approved or have no valid video.')
    const result = await api.approveSeriesAttemptsBulk(workspace, series.id, episode.id, selections)
    if (result.seriesId !== series.id || result.episodeId !== episode.id) {
      throw new Error('Series Lab approved attempts for another target; reload before continuing.')
    }
    await useSeriesStore.getState().reload()
    await useSeriesStore.getState().openSeries(series.id)
    useSeriesStore.getState().openEpisode(episode.id)
    return seriesEpisodeResult(
      workspace,
      episode,
      'review',
      `I approved ${selections.length} attempt${selections.length === 1 ? '' : 's'} in “${episode.title}” and opened Render & Review.`,
    )
  }

  const shot = action.attemptId
    ? requireSingleShotForAttempt(selectedShots, action.attemptId)
    : selectedShots[0]
  const attempt = action.attemptId
    ? shot.attempts.find(item => item.id === action.attemptId)
    : [...shot.attempts].reverse().find(item => item.status === 'completed' && item.reviewDecision !== 'rejected')
  if (!attempt) throw new Error(action.attemptId
    ? `Attempt ${action.attemptId} does not belong to shot ${shot.order}.`
    : `Shot ${shot.order} has no completed attempt awaiting rejection.`)
  if (attempt.status !== 'completed' || attempt.reviewDecision === 'rejected') {
    throw new Error(`Attempt ${attempt.id} of shot ${shot.order} cannot be rejected.`)
  }
  if (shot.approvedAttemptId === attempt.id) {
    throw new Error(`Attempt ${attempt.id} is already the approved one for shot ${shot.order}; the UI does not allow rejecting the final cut without first choosing another take.`)
  }
  const rejectedShot = await api.rejectSeriesAttempt(workspace, series.id, episode.id, shot.id, attempt.id)
  const rejectedAttempt = rejectedShot.attempts.find(item => item.id === attempt.id)
  if (rejectedShot.id !== shot.id || rejectedAttempt?.reviewDecision !== 'rejected') {
    throw new Error('Series Lab did not confirm the requested rejection; reload before continuing.')
  }
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `I rejected attempt ${attempt.id} of shot ${shot.order} in “${episode.title}” and opened Render & Review.`,
  )
}

export async function assembleSeriesEpisode(action: AssembleSeriesEpisodeCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Assembling a Series Lab episode requires confirm=true.')
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
  if (seriesMatches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? `There is no series “${action.seriesTitle}” in this workspace.`
    : 'There is no active series to assemble.')
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”; the target is ambiguous.`)
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? `There is no episode “${action.targetEpisodeTitle}” in “${series.title}”.`
    : `“${series.title}” needs an active or single episode.`)
  if (!episode.shots.length) throw new Error(`“${episode.title}” has no shots to assemble.`)
  const incomplete = missingAssemblyShotOrders(
    episode.shots,
    id => Boolean(series.assets[id]),
  )
  if (incomplete.length) {
    throw new Error(`First approve a playable video for every shot. Missing: ${incomplete.join(', ')}.`)
  }

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const job = await api.startSeriesEpisodeAssembly(workspace, series.id, episode.id)
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error('Series Lab returned an assembly for another target; it won\'t be shown as correct.')
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `I started the ordered assembly of ${episode.shots.length} shots of “${episode.title}” (${job.jobId}). Recoverable progress and the download are open in Render & Review; I have not committed the canon delta.`,
    { taskIds: [job.jobId], channel: 'series_assembly', job: job as unknown as Record<string, unknown> },
  )
}

export async function commitSeriesCanonDelta(action: CommitSeriesCanonCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Committing canon changes requires confirm=true.')
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([import('../../api/client'), import('./store')])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const matches = action.seriesTitle ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle)) : []
  if (matches.length > 1) throw new Error(`There are several series titled “${action.seriesTitle}”; the target is ambiguous.`)
  const series = matches[0] || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle ? `There is no series “${action.seriesTitle}”.` : 'There is no active series.')
  const episodeMatches = action.targetEpisodeTitle ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle)) : []
  if (episodeMatches.length > 1) throw new Error(`There are several episodes titled “${action.targetEpisodeTitle}”.`)
  const activeId = useSeriesStore.getState().activeSeriesId === series.id ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0] || (!action.targetEpisodeTitle && activeId ? series.episodesById[activeId] : null) || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle ? `There is no episode “${action.targetEpisodeTitle}”.` : 'The series needs an active or single episode.')
  const deltaIds = [...episode.proposedCanonDelta.add.map(item => item.id), ...episode.proposedCanonDelta.change.map(item => item.id), ...episode.proposedCanonDelta.retire.map(item => item.factId)]
  if (!deltaIds.length) throw new Error(`“${episode.title}” has no proposed canon changes.`)
  const unknown = action.itemIds.filter(id => !deltaIds.includes(id))
  if (unknown.length) throw new Error(`Cambios de canon desconocidos: ${unknown.join(', ')}.`)
  const selected = action.decision.endsWith('_all') ? deltaIds : action.itemIds
  const value = action.decision.startsWith('accept_') ? 'accepted' : 'rejected'
  const decisions = Object.fromEntries(selected.map(id => [id, value])) as Record<string, 'accepted' | 'rejected'>
  const updated = await api.commitSeriesCanon(workspace, series.id, episode.id, episode.proposedCanonDelta.baseRevision, decisions)
  if (updated.id !== series.id || !updated.episodesById[episode.id]) throw new Error('Series Lab confirmed decisions for another target.')
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    `I marked ${selected.length} canon change${selected.length === 1 ? '' : 's'} as ${value === 'accepted' ? 'accepted' : 'rejected'} in “${episode.title}”. The rest remain pending.`,
    { reviewView: 'finish' },
  )
}
