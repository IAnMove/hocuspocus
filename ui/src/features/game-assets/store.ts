import { create } from 'zustand'
import * as api from '../../api/gameAssets'
import { GameApiError, GameRevisionConflict } from '../../api/gameAssets'
import { errorText, gameText, GameCodeError, problemsOf, type GameAction } from './gameErrors'
import { approvableClean } from './reviewModel'
import { newCharacterId } from './styles'
import {
  applyGamePatch, finishedSteps, forgetGame, isActiveJob, mergeGamePatch, pollDelay, readSelection, rememberGame, rememberJob, upsertGame,
} from './storeModel'
import type { Game, GamePatch, GameProblem, GameSection, ListReport, ProduceJob, StylePatch, StylePreset, StyleReference } from './types'

export interface ListBodyInput { text?: string; csv?: string; items?: unknown[]; format?: string; replace?: boolean }
export type ListOutcome = { ok: true; report: ListReport } | { ok: false; error: string; problems: GameProblem[] }

interface GameAssetsState {
  workspace: string
  ready: boolean
  games: Game[]
  game: Game | null
  serverRevision: number
  /** Setup and style edits that the server has not stored yet. */
  unsaved: GamePatch | null
  dirty: boolean
  editSeq: number
  saving: boolean
  error: string | null
  problems: GameProblem[]
  notice: string | null
  section: GameSection
  presets: StylePreset[]
  styleJob: ProduceJob | null
  produceJob: ProduceJob | null
  selectedIds: string[]
  load: (workspace: string) => Promise<void>
  openGame: (gameId: string) => Promise<void>
  setSection: (section: GameSection) => void
  patchGame: (patch: GamePatch) => void
  applyPreset: (presetId: string) => Promise<boolean>
  /** Saves every pending edit, one request at a time. ``null`` when a save failed. */
  saveNow: () => Promise<Game | null>
  createGame: () => Promise<boolean>
  duplicateGame: () => Promise<boolean>
  deleteGame: () => Promise<boolean>
  startStyleSheet: () => Promise<boolean>
  approveStyle: (references: StyleReference[]) => Promise<boolean>
  discardSample: (assetId: string, attemptId: string, note: string) => Promise<boolean>
  addCharacter: (name: string) => Promise<boolean>
  linkKit: (assetId: string, kitId: string) => Promise<boolean>
  toggleSelected: (assetId: string) => void
  saveAsset: (assetId: string, patch: Record<string, unknown>) => Promise<boolean>
  previewList: (body: ListBodyInput) => Promise<ListOutcome>
  commitList: (body: ListBodyInput) => Promise<ListOutcome>
  startProduce: (body: { assetIds?: string[]; rerender?: boolean }) => Promise<boolean>
  cancelProduce: () => Promise<boolean>
  resumeProduce: () => Promise<boolean>
  approveAttempt: (assetId: string, attemptId: string) => Promise<boolean>
  rejectAttempt: (assetId: string, attemptId: string, note: string) => Promise<boolean>
  setLock: (assetId: string, locked: boolean) => Promise<boolean>
  approveClean: () => Promise<boolean>
  regenerateAsset: (assetId: string) => Promise<boolean>
  showError: (error: unknown, action: GameAction) => void
}

type JobSlot = 'produceJob' | 'styleJob'

let saveTimer: ReturnType<typeof setTimeout> | undefined
let saveRun: Promise<Game | null> | null = null
/** The patch of the PUT in flight; a server copy read meanwhile keeps it on top. */
let inflight: GamePatch | null = null
let watching = true
const pollTimers: Partial<Record<JobSlot, ReturnType<typeof setTimeout>>> = {}
const pollFailures: Record<JobSlot, number> = { produceJob: 0, styleJob: 0 }

const store = () => useGameAssetsStore.getState()
const update = (partial: Partial<GameAssetsState>) => useGameAssetsStore.setState(partial)
const setJob = (slot: JobSlot, job: ProduceJob | null) => update(slot === 'produceJob' ? { produceJob: job } : { styleJob: job })

function fail(error: unknown, action: GameAction): void {
  update({ error: errorText(error, action), problems: problemsOf(error) })
}

/** Adopt a server copy of the open game; unsaved and in-flight edits stay on top of it. */
function adoptGame(fresh: Game, workspace: string): void {
  const state = store()
  if (state.workspace !== workspace) return
  const games = upsertGame(state.games, fresh)
  if (state.game?.id !== fresh.id) {
    update({ games })
    return
  }
  if (fresh.revision < state.serverRevision) return // an older read finished after a newer save
  update({ game: applyGamePatch(fresh, mergeGamePatch(inflight, state.unsaved)), serverRevision: fresh.revision, games })
}

async function reloadCurrent(): Promise<void> {
  const { workspace, game } = store()
  if (!game) return
  adoptGame(await api.fetchGame(workspace, game.id), workspace)
}

function refreshQuietly(): Promise<void> {
  return reloadCurrent().catch(() => undefined)
}

async function reloadAfterConflict(): Promise<void> {
  try {
    await reloadCurrent()
    update({ notice: 'revision_conflict' })
  } catch (error) {
    fail(error, 'open')
  }
}

function stopPoll(slot: JobSlot): void {
  clearTimeout(pollTimers[slot])
  pollTimers[slot] = undefined
}

function stopAllPolls(): void {
  stopPoll('produceJob')
  stopPoll('styleJob')
}

function schedulePoll(slot: JobSlot, jobId: string, delay: number): void {
  stopPoll(slot)
  if (!watching) return
  pollTimers[slot] = setTimeout(() => { void pollJob(slot, jobId) }, delay)
}

/** Show ``job`` and poll it while the server works on it. */
function watchJob(slot: JobSlot, job: ProduceJob): void {
  watching = true
  pollFailures[slot] = 0
  setJob(slot, job)
  if (isActiveJob(job)) schedulePoll(slot, job.id, pollDelay(0))
  else stopPoll(slot)
}

async function pollJob(slot: JobSlot, jobId: string): Promise<void> {
  pollTimers[slot] = undefined
  const { workspace } = store()
  const before = store()[slot]
  if (before?.id !== jobId) return
  try {
    const next = await api.fetchProduceJob(workspace, jobId)
    if (store().workspace !== workspace || store()[slot]?.id !== jobId) return
    pollFailures[slot] = 0
    setJob(slot, next)
    const active = isActiveJob(next)
    // A job bumps the game revision on every attempt it writes; keep the copy current.
    if (!active || finishedSteps(next) !== finishedSteps(before)) await refreshQuietly()
    if (active) schedulePoll(slot, jobId, pollDelay(0))
  } catch (error) {
    pollFailed(slot, jobId, error)
  }
}

function pollFailed(slot: JobSlot, jobId: string, error: unknown): void {
  if (store()[slot]?.id !== jobId) return
  if (error instanceof GameApiError && error.status === 404) {
    setJob(slot, null)
    return
  }
  pollFailures[slot] += 1
  if (pollFailures[slot] === 3) fail(error, 'poll')
  schedulePoll(slot, jobId, pollDelay(pollFailures[slot]))
}

/** Resume polling the jobs that are still running, e.g. when the panel mounts again. */
export function watchGameJobs(): void {
  watching = true
  for (const slot of ['produceJob', 'styleJob'] as const) {
    const job = store()[slot]
    if (job && isActiveJob(job) && !pollTimers[slot]) schedulePoll(slot, job.id, pollDelay(0))
  }
}

/** Stop every poll; the jobs stay in the store. */
export function stopGamePolling(): void {
  watching = false
  stopAllPolls()
}

function switchGame(workspace: string, game: Game): void {
  clearTimeout(saveTimer)
  stopAllPolls()
  rememberGame(workspace, game.id)
  update({
    game, games: upsertGame(store().games, game), serverRevision: game.revision, unsaved: null, dirty: false,
    error: null, problems: [], notice: null, selectedIds: [], produceJob: null, styleJob: null,
  })
}

async function restoreJob(workspace: string, gameId: string): Promise<void> {
  const jobId = readSelection(workspace).jobs[gameId]
  if (!jobId) return
  try {
    const job = await api.fetchProduceJob(workspace, jobId)
    if (store().workspace !== workspace || store().game?.id !== gameId) return
    watchJob('produceJob', job)
  } catch (error) {
    if (error instanceof GameApiError && error.status === 404) rememberJob(workspace, gameId, '')
  }
}

function takeUnsaved(): GamePatch {
  const sent = store().unsaved || {}
  inflight = sent
  update({ unsaved: null, saving: true })
  return sent
}

async function putUnsaved(workspace: string, gameId: string, baseRevision: number): Promise<void> {
  const sent = takeUnsaved()
  try {
    const saved = await api.updateGame(workspace, gameId, sent, baseRevision)
    inflight = null
    adoptGame(saved, workspace)
  } catch (error) {
    inflight = null
    if (store().game?.id === gameId) update({ unsaved: mergeGamePatch(sent, store().unsaved) })
    throw error
  }
}

/** A second conflict: show the server copy and drop the edits that could not be saved. */
async function dropUnsaved(workspace: string, gameId: string): Promise<boolean> {
  update({ unsaved: null })
  try {
    adoptGame(await api.fetchGame(workspace, gameId), workspace)
  } catch (error) {
    fail(error, 'open')
  }
  update({ notice: 'revision_conflict' })
  return false
}

/** Reload, keep the unsaved edits on top of the fresh copy and send them once more. */
async function retryAfterConflict(workspace: string, gameId: string): Promise<boolean> {
  try {
    const fresh = await api.fetchGame(workspace, gameId)
    adoptGame(fresh, workspace)
    update({ notice: 'revision_conflict' })
    await putUnsaved(workspace, gameId, fresh.revision)
    return true
  } catch (error) {
    if (error instanceof GameRevisionConflict) return dropUnsaved(workspace, gameId)
    fail(error, 'save')
    return false
  }
}

async function saveRound(gameId: string): Promise<boolean> {
  const { workspace, serverRevision } = store()
  try {
    await putUnsaved(workspace, gameId, serverRevision)
    return true
  } catch (error) {
    // Awaited so ``finally`` runs after the retry, not before it.
    if (error instanceof GameRevisionConflict) return await retryAfterConflict(workspace, gameId)
    fail(error, 'save')
    return false
  } finally {
    update({ saving: false, dirty: Boolean(store().unsaved) })
  }
}

async function flushSaves(): Promise<Game | null> {
  // Edits made while a PUT is in flight are sent next, with the revision that PUT returned.
  for (let round = 0; round < 8; round += 1) {
    const { game, unsaved } = store()
    if (!game) return null
    if (!unsaved) return game
    if (!(await saveRound(game.id))) return null
  }
  return store().game
}

interface RunOptions {
  /** Save pending edits first (default). */
  save?: boolean
  /** On revision_conflict reload and run once more instead of only showing the notice. */
  retry?: boolean
}

/** Run one server action: errors become a translated message, a conflict reloads the game. */
async function run(action: GameAction, work: (game: Game, workspace: string) => Promise<void>, options: RunOptions = {}): Promise<boolean> {
  if (!store().game) return false
  if (options.save !== false && !(await store().saveNow())) return false
  const game = store().game
  if (!game) return false
  try {
    await work(game, store().workspace)
  } catch (error) {
    if (!(error instanceof GameRevisionConflict)) {
      fail(error, action)
      return false
    }
    await reloadAfterConflict()
    return options.retry ? run(action, work, { save: false }) : false
  }
  update({ error: null, problems: [] })
  return true
}

function listFailure(error: unknown, action: GameAction): ListOutcome {
  return { ok: false, error: errorText(error, action), problems: problemsOf(error) }
}

export const useGameAssetsStore = create<GameAssetsState>((set, get) => ({
  workspace: '',
  ready: false,
  games: [],
  game: null,
  serverRevision: 0,
  unsaved: null,
  dirty: false,
  editSeq: 0,
  saving: false,
  error: null,
  problems: [],
  notice: null,
  section: 'setup',
  presets: [],
  styleJob: null,
  produceJob: null,
  selectedIds: [],

  load: async workspace => {
    if (get().game && get().workspace !== workspace) await get().saveNow()
    clearTimeout(saveTimer)
    stopAllPolls()
    set({
      workspace, ready: false, error: null, problems: [], notice: null, games: [], game: null, serverRevision: 0,
      unsaved: null, dirty: false, produceJob: null, styleJob: null, selectedIds: [],
    })
    try {
      const [library, presets] = await Promise.all([api.fetchGameLibrary(workspace), api.fetchGamePresets()])
      if (get().workspace !== workspace) return
      const games = library.games || []
      set({ games, presets: presets.presets || [], ready: true })
      const wanted = readSelection(workspace).gameId
      const id = games.some(item => item.id === wanted) ? wanted : games[0]?.id
      if (id) await get().openGame(id)
    } catch (error) {
      if (get().workspace !== workspace) return
      set({ ready: true })
      fail(error, 'load')
    }
  },

  openGame: async gameId => {
    const { workspace, game: current } = get()
    if (current && current.id !== gameId) await get().saveNow()
    try {
      const game = await api.fetchGame(workspace, gameId)
      if (get().workspace !== workspace) return
      if (get().game?.id === game.id) {
        adoptGame(game, workspace)
        return
      }
      switchGame(workspace, game)
      await restoreJob(workspace, game.id)
    } catch (error) {
      if (get().workspace === workspace) fail(error, 'open')
    }
  },

  setSection: section => set({ section }),

  patchGame: patch => {
    const game = get().game
    if (!game) return
    set({
      game: applyGamePatch(game, patch), unsaved: mergeGamePatch(get().unsaved, patch),
      dirty: true, editSeq: get().editSeq + 1, notice: null,
    })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { void get().saveNow() }, 750)
  },

  // The server resets the preset-derived keys itself; send only the preset and adopt its answer.
  applyPreset: presetId => run('preset', async (game, workspace) => {
    const preset = store().presets.find(item => item.id === presetId)
    const style: StylePatch = { preset: presetId }
    if (preset?.screenDefault && preset.screenDefault !== game.style.screen) style.screen = preset.screenDefault
    adoptGame(await api.updateGame(workspace, game.id, { style }, store().serverRevision), workspace)
  }),

  saveNow: () => {
    clearTimeout(saveTimer)
    if (!saveRun) saveRun = flushSaves().finally(() => { saveRun = null })
    return saveRun
  },

  createGame: async () => {
    if (get().game && !(await get().saveNow())) return false
    const workspace = get().workspace
    try {
      const created = await api.createGame(workspace, { title: gameText('untitled'), genre: 'platformer', view: 'side' })
      switchGame(workspace, created)
      set({ section: 'setup' })
      return true
    } catch (error) {
      fail(error, 'create')
      return false
    }
  },

  duplicateGame: () => run('duplicate', async (source, workspace) => {
    const created = await api.createGame(workspace, {
      title: gameText('copyTitle', { title: source.title }), genre: source.genre, view: source.view,
      style: { ...source.style, approval: 'draft', approvedAt: null, references: [] },
    })
    switchGame(workspace, created)
  }),

  deleteGame: () => run('delete', async (current, workspace) => {
    clearTimeout(saveTimer) // no autosave PUT for a game that is going away
    await api.deleteGame(workspace, current.id)
    forgetGame(workspace, current.id)
    stopAllPolls()
    const games = store().games.filter(item => item.id !== current.id)
    update({ games, game: null, unsaved: null, dirty: false, produceJob: null, styleJob: null, selectedIds: [] })
    if (games[0]) await store().openGame(games[0].id)
  }, { save: false }),

  startStyleSheet: () => run('styleSheet', async (game, workspace) => {
    watchJob('styleJob', await api.startStyleSheet(workspace, game.id))
    await refreshQuietly()
  }),

  approveStyle: references => run('approveStyle', async (game, workspace) => {
    adoptGame(await api.approveGameStyle(workspace, game.id, store().serverRevision, references), workspace)
  }),

  discardSample: (assetId, attemptId, note) => run('discard', async (game, workspace) => {
    await api.rejectGameAttempt(workspace, game.id, assetId, attemptId, note, store().serverRevision)
    await reloadCurrent()
  }),

  addCharacter: name => run('addCharacter', async (_game, workspace) => {
    await reloadCurrent() // the id must be free on the server, not only in this copy
    const game = store().game
    if (!game) throw new GameCodeError('game_not_found')
    const id = newCharacterId(name, game.assets)
    await api.gameAssetsFromList(workspace, game.id, { items: [{ kind: 'character', id, name, description: name, options: ['jugador'] }] })
    await reloadCurrent()
  }),

  linkKit: (assetId, kitId) => run('linkKit', async (game, workspace) => {
    const asset = game.assets.find(item => item.id === assetId)
    if (!asset) throw new GameCodeError('missing_character')
    await api.updateGameAsset(workspace, game.id, assetId, { spec: { ...asset.spec, kitId } }, store().serverRevision)
    await reloadCurrent()
  }, { retry: true }),

  toggleSelected: assetId => {
    const selected = get().selectedIds
    set({ selectedIds: selected.includes(assetId) ? selected.filter(item => item !== assetId) : [...selected, assetId] })
  },

  saveAsset: (assetId, patch) => run('saveAsset', async (game, workspace) => {
    await api.updateGameAsset(workspace, game.id, assetId, patch, store().serverRevision)
    await reloadCurrent()
  }, { retry: true }),

  previewList: async body => {
    const game = get().game
    if (!game) return listFailure(null, 'checkList')
    try {
      return { ok: true, report: await api.gameAssetsFromList(get().workspace, game.id, { ...body, check: true }) }
    } catch (error) {
      return listFailure(error, 'checkList')
    }
  },

  commitList: async body => {
    const game = get().game
    if (!game) return listFailure(null, 'commitList')
    if (!(await get().saveNow())) return { ok: false, error: get().error || gameText('actions.save'), problems: [] }
    try {
      const report = await api.gameAssetsFromList(get().workspace, game.id, { ...body, check: false })
      await refreshQuietly()
      return { ok: true, report }
    } catch (error) {
      return listFailure(error, 'commitList')
    }
  },

  startProduce: body => run('produce', async (game, workspace) => {
    const job = await api.produceGame(workspace, game.id, body)
    rememberJob(workspace, game.id, job.id)
    watchJob('produceJob', job)
  }),

  cancelProduce: () => run('cancel', async (_game, workspace) => {
    const job = store().produceJob
    if (job) watchJob('produceJob', await api.cancelProduceJob(workspace, job.id))
  }, { save: false }),

  resumeProduce: () => run('resume', async (_game, workspace) => {
    const job = store().produceJob
    if (job) watchJob('produceJob', await api.resumeProduceJob(workspace, job.id))
  }),

  approveAttempt: (assetId, attemptId) => run('approve', async (game, workspace) => {
    await api.approveGameAttempt(workspace, game.id, assetId, attemptId, store().serverRevision)
    await reloadCurrent()
  }),

  rejectAttempt: async (assetId, attemptId, note) => {
    if (!note.trim()) return false
    return run('reject', async (game, workspace) => {
      await api.rejectGameAttempt(workspace, game.id, assetId, attemptId, note.trim(), store().serverRevision)
      await reloadCurrent()
    })
  },

  setLock: (assetId, locked) => run('lock', async (game, workspace) => {
    await api.lockGameAsset(workspace, game.id, assetId, locked, store().serverRevision)
    await reloadCurrent()
  }),

  approveClean: () => run('approveClean', async (game, workspace) => {
    for (const pick of approvableClean(game.assets)) {
      await api.approveGameAttempt(workspace, game.id, pick.assetId, pick.attemptId, store().serverRevision)
      await reloadCurrent()
    }
  }),

  regenerateAsset: async assetId => {
    const started = await get().startProduce({ assetIds: [assetId], rerender: true })
    if (started) get().setSection('produce')
    return started
  },

  showError: (error, action) => fail(error, action),
}))

