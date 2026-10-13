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
import i18n from '../../i18n'
import { contentLanguageForUi, scaffoldLanguage } from '../../lib/contentLanguage'
import { seriesRenderCandidates } from './productionMethods'
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
    if (!action.createIfMissing) throw new Error(i18n.t('seriesLab:errors.seriesMissingUnauthorized', { title: action.seriesTitle }))
    series = await api.createSeriesProject(
      workspace,
      action.seriesTitle || i18n.t('seriesLab:scaffold.newSeries', { lng: scaffoldLanguage(action.language) }),
      action.language || contentLanguageForUi().code,
    )
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
      i18n.t('seriesLab:replies.episodeAlreadyOpen', { title: existingEpisode.title }),
    )
  }

  const languageIntent = resolveSeriesLanguageIntent(series, action.language, action.languageIntent, createdSeries)
  const languageSetupChanged = seriesLanguageIntentAffectsCanon(series, languageIntent)
  const authoredLanguage = languageIntent.contentLanguage || action.language || series.language
  const lng = scaffoldLanguage(authoredLanguage)
  const characters = series.characters.length ? series.characters : creativeCharacters(action.characters, authoredLanguage).map((character, index) => ({
    ...seriesModel.createSeriesCharacter(),
    name: character.name || i18n.t('seriesLab:scaffold.characterName', { lng, index: index + 1 }),
    role: character.role || (index
      ? i18n.t('seriesLab:scaffold.roleSupport', { lng })
      : i18n.t('seriesLab:scaffold.roleLead', { lng })),
    personality: character.personality,
    desire: character.desire,
    need: i18n.t('seriesLab:scaffold.need', {
      lng,
      desire: character.desire || i18n.t('seriesLab:scaffold.needDesire', { lng }),
    }),
    flaw: character.flaw,
    longArc: action.seriesPremise,
    voiceAndDialogue: character.voice,
    appearance: character.appearance,
    identityLock: i18n.t('seriesLab:scaffold.identityLock', { lng, appearance: character.appearance }),
  }))
  const locations = series.locations.length ? series.locations : creativeLocations(action.locations, authoredLanguage).map(location => ({
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
    || languageSetupChanged
  if (needsSetup) {
    const patched = {
      ...series,
      title: series.title === 'Untitled series' ? action.seriesTitle : series.title,
      premise: series.premise || action.seriesPremise || action.episodePremise,
      logline: series.logline || action.seriesLogline || action.episodeLogline,
      genre: series.genre || action.genre || i18n.t('seriesLab:scaffold.genre', { lng }),
      tone: series.tone || action.tone || i18n.t('seriesLab:scaffold.tone', { lng }),
      visualStyle: series.visualStyle || action.visualStyle || i18n.t('seriesLab:scaffold.visualStyle', { lng }),
      characterVisualStyle: series.characterVisualStyle || action.visualStyle || i18n.t('seriesLab:scaffold.characterVisualStyle', { lng }),
      cameraLanguage: series.cameraLanguage || i18n.t('seriesLab:scaffold.camera', { lng }),
      language: languageIntent.contentLanguage || action.language || series.language,
      spokenLanguage: languageIntent.spokenLanguage || action.language || series.spokenLanguage,
      languageIntent,
      sourceMode: action.knownUniverse ? 'known_universe_experimental' as const : series.sourceMode,
      masterUniversePrompt: series.masterUniversePrompt || (action.knownUniverse
        ? i18n.t('seriesLab:scaffold.fanPrompt', { lng, title: action.seriesTitle })
        : ''),
      rightsNote: series.rightsNote || (action.knownUniverse
        ? i18n.t('seriesLab:scaffold.rights', { lng })
        : ''),
      canon: {
        ...series.canon,
        worldSummary: series.canon.worldSummary || action.worldSummary || action.seriesPremise || action.episodePremise,
        immutableRules: series.canon.immutableRules.length ? series.canon.immutableRules : [{
          id: seriesModel.seriesId('fact'),
          description: i18n.t('seriesLab:scaffold.canonRule', { lng }),
          status: 'draft' as const,
        }],
        themes: series.canon.themes.length ? series.canon.themes : [action.theme || i18n.t('seriesLab:scaffold.theme', { lng })],
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

  const beats = outlineBeats(action.outlineBeats, action.episodePremise, action.ending, authoredLanguage)
  const createdEpisode = await api.createSeriesEpisode(
    workspace,
    series.id,
    series.seasons[0]?.id,
    {
      title: action.episodeTitle || i18n.t('seriesLab:scaffold.episode', {
        lng,
        number: Object.keys(series.episodesById).length + 1,
      }),
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
  const createdPrefix = createdSeries ? i18n.t('seriesLab:replies.createdSeriesPrefix') : ''
  const canonPrefix = approvedCanon ? i18n.t('seriesLab:replies.canonPreparedPrefix') : ''
  const savedEpisode = series.episodesById[createdEpisode.id] || createdEpisode
  const synopsis = [
    series.premise.trim()
      ? i18n.t('seriesLab:replies.seriesPremiseLine', { title: series.title, premise: series.premise.trim() })
      : '',
    savedEpisode.premise.trim()
      ? i18n.t('seriesLab:replies.episodeDraftLine', { title: savedEpisode.title, premise: savedEpisode.premise.trim() })
      : '',
  ].filter(Boolean).join('\n\n')
  const synopsisBlock = synopsis ? `\n\n${synopsis}` : ''
  return seriesEpisodeResult(
    workspace,
    savedEpisode,
    'episode',
    i18n.t('seriesLab:replies.episodeSaved', {
      createdPrefix,
      canonPrefix,
      title: savedEpisode.title,
      beats: savedEpisode.outline.beats.length,
      synopsis: synopsisBlock,
    }),
  )
}

/**
 * Stage an exact Series episode as an editable Comic project. This is a
 * preparation step only: no image provider or render job is started.
 */
export async function stageSeriesComic(action: StageSeriesComicCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.stageComicNeedsConfirm'))
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
    i18n.t('seriesLab:replies.comicStaged', { title: handoff.comic.title, episode: handoff.episode.title }),
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeriesRename', { title: action.seriesTitle }))
  let series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToUpdate'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) {
    throw new Error(i18n.t('seriesLab:errors.ambiguousEpisodeBeforeEdit', { title: action.targetEpisodeTitle }))
  }
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.episodeTargetUnclear', { title: series.title }))

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
  if (!verified) throw new Error(i18n.t('seriesLab:errors.episodeNotReturned', { title: episode.title }))
  if (action.episodeTitle && verified.title !== action.episodeTitle) throw new Error(i18n.t('seriesLab:errors.titleNotConfirmed'))
  if (action.episodePremise && verified.premise !== action.episodePremise) throw new Error(i18n.t('seriesLab:errors.premiseNotConfirmed'))
  if (action.episodeLogline && verified.logline !== action.episodeLogline) throw new Error(i18n.t('seriesLab:errors.loglineNotConfirmed'))
  if (action.outlineBeats.length && JSON.stringify(verified.outline.beats) !== JSON.stringify(action.outlineBeats)) {
    throw new Error(i18n.t('seriesLab:errors.structureNotConfirmed'))
  }
  return seriesEpisodeResult(
    workspace,
    verified,
    'episode',
    i18n.t('seriesLab:replies.episodeUpdated', { title: verified.title, series: saved.title, scenes: verified.script.length, shots: verified.shots.length }),
  )
}

export async function generateSeriesPlan(action: GenerateSeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.generatePlanNeedsConfirm'))
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  let series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToPlan'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisode', { title: action.targetEpisodeTitle }))
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.needsActiveOrOnlyEpisode', { title: series.title }))
  if (!episode.premise.trim()) throw new Error(i18n.t('seriesLab:errors.premiseRequired', { title: episode.title }))
  if (action.scope === 'shots' && !episode.script.length) {
    throw new Error(i18n.t('seriesLab:errors.shotsNeedScript'))
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
    throw new Error(i18n.t('seriesLab:errors.planJobWrongEpisode'))
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'episode',
    i18n.t('seriesLab:replies.planStarted', { scope: action.scope, title: episode.title, jobId: job.jobId }),
    { taskIds: [job.jobId], channel: 'series_plan', job: job as unknown as Record<string, unknown> },
  )
}

export async function applySeriesPlan(action: ApplySeriesPlanCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.applyPlanNeedsConfirm'))
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToApply'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisode', { title: action.targetEpisodeTitle }))
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.needsActiveOrOnlyEpisode', { title: series.title }))

  const job = action.jobId
    ? await api.fetchSeriesPlanJob(action.jobId)
    : (await api.fetchSeriesPlanRecovery(workspace)).jobs
        .filter(item => item.seriesId === series.id && item.episodeId === episode.id && item.status === 'completed' && item.episodeResult)
        .sort((left, right) => Number(right.updatedAt || right.finishedAt || 0) - Number(left.updatedAt || left.finishedAt || 0))[0]
  if (!job) throw new Error(i18n.t('seriesLab:errors.noRecoverableProposal', { title: episode.title }))
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error(i18n.t('seriesLab:errors.jobWrongDestination'))
  }
  if (job.status !== 'completed' || !job.episodeResult) {
    throw new Error(i18n.t('seriesLab:errors.jobNotCompleted', { jobId: job.jobId, status: job.status }))
  }
  const applied = await api.applySeriesPlanJob(job.jobId, job.episodeResult)
  if (applied.id !== episode.id) throw new Error(i18n.t('seriesLab:errors.appliedUnexpectedEpisode'))
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  return seriesEpisodeResult(
    workspace,
    applied,
    'episode',
    i18n.t('seriesLab:replies.planApplied', { jobId: job.jobId, title: applied.title, beats: applied.outline.beats.length, scenes: applied.script.length, shots: applied.shots.length }),
    { taskIds: [job.jobId], channel: 'series_plan_clear' },
  )
}

export async function renderSeriesShots(action: RenderSeriesShotsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.renderNeedsConfirm'))
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToRender'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisode', { title: action.targetEpisodeTitle }))
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.needsActiveOrOnlyEpisode', { title: series.title }))
  if (!episode.shots.length) throw new Error(i18n.t('seriesLab:errors.noShotsToRender', { title: episode.title }))
  const eligible = seriesRenderCandidates(series, episode, action.mode, action.shotIds)
  if (!eligible.length) throw new Error(i18n.t('seriesLab:renderActions.noCandidates'))
  const staleShots = eligible.filter(shot => shot.scriptDialogueStatus === 'stale' || shot.scriptDialogueStatus === 'manual_conflict')
  if (staleShots.length) {
    throw new Error(
      i18n.t('seriesLab:errors.staleDialogue', { total: staleShots.length }),
    )
  }
  if (eligible.some(shot => shot.dialogueBeats.length > 0) && !series.bestEffortLipSyncAcknowledged) {
    throw new Error(i18n.t('seriesLab:errors.lipSyncConsentRequired'))
  }

  const byId = new Map(episode.shots.map(shot => [shot.id, shot]))
  if (action.mode === 'selected') {
    const unknown = action.shotIds.filter(id => !byId.has(id))
    if (unknown.length) throw new Error(i18n.t('seriesLab:errors.unknownShots', { shots: unknown.join(', ') }))
    const approved = action.shotIds.filter(id => Boolean(byId.get(id)?.approvedAttemptId))
    if (approved.length) throw new Error(i18n.t('seriesLab:errors.approvedShotsBlocked', { shots: approved.join(', ') }))
  }

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
    throw new Error(i18n.t('seriesLab:errors.renderJobWrongDestination'))
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    i18n.t('seriesLab:replies.shotsQueued', { total: eligible.length, title: episode.title, jobId: job.jobId, mode: action.mode }),
    { taskIds: [job.jobId], channel: 'series_render', job: job as unknown as Record<string, unknown> },
  )
}

export async function reviewSeriesAttempts(action: ReviewSeriesAttemptsCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.reviewNeedsConfirm'))
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToReview'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisode', { title: action.targetEpisodeTitle }))
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.needsActiveOrOnlyEpisode', { title: series.title }))

  const shotsByOrder = new Map<number, typeof episode.shots[number]>()
  for (const shot of episode.shots) {
    if (shotsByOrder.has(shot.order)) throw new Error(i18n.t('seriesLab:errors.duplicateShotOrder', { order: shot.order }))
    shotsByOrder.set(shot.order, shot)
  }
  const selectedShots = action.scope === 'all_latest' || action.scope === 'replace_latest'
    ? episode.shots
    : action.shotNumbers.map(number => {
        const shot = shotsByOrder.get(number)
        if (!shot) throw new Error(i18n.t('seriesLab:errors.shotMissing', { number, title: episode.title }))
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
        throw new Error(i18n.t('seriesLab:errors.shotNotApprovable', { order: missing[0].order }))
      }
    }
    if (!selections.length) throw new Error(i18n.t('seriesLab:errors.noEligibleAttempts'))
    const result = await api.approveSeriesAttemptsBulk(workspace, series.id, episode.id, selections, 'wizard')
    if (result.seriesId !== series.id || result.episodeId !== episode.id) {
      throw new Error(i18n.t('seriesLab:errors.approvedWrongDestination'))
    }
    await useSeriesStore.getState().reload()
    await useSeriesStore.getState().openSeries(series.id)
    useSeriesStore.getState().openEpisode(episode.id)
    const attemptWord = selections.length === 1
      ? i18n.t('seriesLab:replies.attemptSingular')
      : i18n.t('seriesLab:replies.attemptPlural')
    return seriesEpisodeResult(
      workspace,
      episode,
      'review',
      i18n.t('seriesLab:replies.attemptsApproved', {
        total: selections.length,
        attempt: attemptWord,
        title: episode.title,
      }),
    )
  }

  const shot = action.attemptId
    ? requireSingleShotForAttempt(selectedShots, action.attemptId)
    : selectedShots[0]
  const attempt = action.attemptId
    ? shot.attempts.find(item => item.id === action.attemptId)
    : [...shot.attempts].reverse().find(item => item.status === 'completed' && item.reviewDecision !== 'rejected')
  if (!attempt) throw new Error(action.attemptId
    ? i18n.t('seriesLab:errors.attemptNotOnShot', { attemptId: action.attemptId, order: shot.order })
    : i18n.t('seriesLab:errors.shotNothingToReject', { order: shot.order }))
  if (attempt.status !== 'completed' || attempt.reviewDecision === 'rejected') {
    throw new Error(i18n.t('seriesLab:errors.attemptNotRejectable', { attemptId: attempt.id, order: shot.order }))
  }
  if (shot.approvedAttemptId === attempt.id) {
    throw new Error(i18n.t('seriesLab:errors.cannotRejectFinalTake', { attemptId: attempt.id, order: shot.order }))
  }
  const rejectedShot = await api.rejectSeriesAttempt(workspace, series.id, episode.id, shot.id, attempt.id, 'wizard')
  const rejectedAttempt = rejectedShot.attempts.find(item => item.id === attempt.id)
  if (rejectedShot.id !== shot.id || rejectedAttempt?.reviewDecision !== 'rejected') {
    throw new Error(i18n.t('seriesLab:errors.rejectNotConfirmed'))
  }
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    i18n.t('seriesLab:replies.attemptRejected', { attemptId: attempt.id, order: shot.order, title: episode.title }),
  )
}

export async function assembleSeriesEpisode(action: AssembleSeriesEpisodeCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.assembleNeedsConfirm'))
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
  if (seriesMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  const series = seriesMatches[0]
    || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle
    ? i18n.t('seriesLab:errors.seriesMissingInWorkspace', { title: action.seriesTitle })
    : i18n.t('seriesLab:errors.noActiveSeriesToAssemble'))
  const episodeMatches = action.targetEpisodeTitle
    ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle))
    : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisode', { title: action.targetEpisodeTitle }))
  const activeEpisodeId = useSeriesStore.getState().activeSeriesId === series.id
    ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0]
    || (!action.targetEpisodeTitle && activeEpisodeId ? series.episodesById[activeEpisodeId] : null)
    || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle
    ? i18n.t('seriesLab:errors.episodeMissingInSeries', { title: action.targetEpisodeTitle, series: series.title })
    : i18n.t('seriesLab:errors.needsActiveOrOnlyEpisode', { title: series.title }))
  if (!episode.shots.length) throw new Error(i18n.t('seriesLab:errors.noShotsToAssemble', { title: episode.title }))
  const incomplete = missingAssemblyShotOrders(
    episode.shots,
    id => Boolean(series.assets[id]),
  )
  if (incomplete.length) {
    throw new Error(i18n.t('seriesLab:errors.assemblyIncomplete', { shots: incomplete.join(', ') }))
  }

  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const job = await api.startSeriesEpisodeAssembly(workspace, series.id, episode.id)
  if (job.workspace !== workspace || job.seriesId !== series.id || job.episodeId !== episode.id) {
    throw new Error(i18n.t('seriesLab:errors.assemblyWrongDestination'))
  }
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    i18n.t('seriesLab:replies.assemblyStarted', { total: episode.shots.length, title: episode.title, jobId: job.jobId }),
    { taskIds: [job.jobId], channel: 'series_assembly', job: job as unknown as Record<string, unknown> },
  )
}

export async function commitSeriesCanonDelta(action: CommitSeriesCanonCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error(i18n.t('seriesLab:errors.commitCanonNeedsConfirm'))
  const workspace = useStore.getState().activeWorkspace || 'default'
  const [api, { useSeriesStore }] = await Promise.all([import('../../api/client'), import('./store')])
  await useSeriesStore.getState().loadWorkspace(workspace)
  await useSeriesStore.getState().saveNow()
  const library = await api.fetchSeriesLibrary(workspace)
  const matches = action.seriesTitle ? Object.values(library.seriesById).filter(item => normalizeName(item.title) === normalizeName(action.seriesTitle)) : []
  if (matches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousSeries', { title: action.seriesTitle }))
  const series = matches[0] || (!action.seriesTitle ? library.seriesById[useSeriesStore.getState().activeSeriesId] : null)
  if (!series) throw new Error(action.seriesTitle ? i18n.t('seriesLab:errors.seriesMissing', { title: action.seriesTitle }) : i18n.t('seriesLab:errors.noActiveSeries'))
  const episodeMatches = action.targetEpisodeTitle ? Object.values(series.episodesById).filter(item => normalizeName(item.title) === normalizeName(action.targetEpisodeTitle)) : []
  if (episodeMatches.length > 1) throw new Error(i18n.t('seriesLab:errors.ambiguousEpisodeTitle', { title: action.targetEpisodeTitle }))
  const activeId = useSeriesStore.getState().activeSeriesId === series.id ? useSeriesStore.getState().activeEpisodeId : ''
  const episodes = Object.values(series.episodesById)
  const episode = episodeMatches[0] || (!action.targetEpisodeTitle && activeId ? series.episodesById[activeId] : null) || (!action.targetEpisodeTitle && episodes.length === 1 ? episodes[0] : null)
  if (!episode) throw new Error(action.targetEpisodeTitle ? i18n.t('seriesLab:errors.episodeMissing', { title: action.targetEpisodeTitle }) : i18n.t('seriesLab:errors.seriesNeedsActiveEpisode'))
  const deltaIds = [...episode.proposedCanonDelta.add.map(item => item.id), ...episode.proposedCanonDelta.change.map(item => item.id), ...episode.proposedCanonDelta.retire.map(item => item.factId)]
  if (!deltaIds.length) throw new Error(i18n.t('seriesLab:errors.noCanonChanges', { title: episode.title }))
  const unknown = action.itemIds.filter(id => !deltaIds.includes(id))
  if (unknown.length) throw new Error(i18n.t('seriesLab:errors.unknownCanonChanges', { ids: unknown.join(', ') }))
  const selected = action.decision.endsWith('_all') ? deltaIds : action.itemIds
  const value = action.decision.startsWith('accept_') ? 'accepted' : 'rejected'
  const decisions = Object.fromEntries(selected.map(id => [id, value])) as Record<string, 'accepted' | 'rejected'>
  const updated = await api.commitSeriesCanon(workspace, series.id, episode.id, episode.proposedCanonDelta.baseRevision, decisions)
  if (updated.id !== series.id || !updated.episodesById[episode.id]) throw new Error(i18n.t('seriesLab:errors.canonWrongDestination'))
  await useSeriesStore.getState().reload()
  await useSeriesStore.getState().openSeries(series.id)
  useSeriesStore.getState().openEpisode(episode.id)
  const changeWord = selected.length === 1
    ? i18n.t('seriesLab:replies.changeSingular')
    : i18n.t('seriesLab:replies.changePlural')
  const decisionWord = value === 'accepted'
    ? i18n.t('seriesLab:replies.canonAccepted')
    : i18n.t('seriesLab:replies.canonRejected')
  return seriesEpisodeResult(
    workspace,
    episode,
    'review',
    i18n.t('seriesLab:replies.canonMarked', {
      total: selected.length,
      change: changeWord,
      decision: decisionWord,
      title: episode.title,
    }),
    { reviewView: 'finish' },
  )
}
