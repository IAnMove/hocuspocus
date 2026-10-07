import { create } from 'zustand'
import * as api from '../../api/gameAssets'
import { GameRevisionConflict } from '../../api/gameAssets'
import { approvableClean } from './reviewModel'
import type { Game, GameSection, GameStyle, ListReport, PaletteMode, ProduceJob, StylePreset, StyleReference } from './types'

const SELECTION = 'hocuspocus.gameAssets.'
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'canceled', 'interrupted'])

interface GameAssetsState {
  workspace: string
  ready: boolean
  games: Game[]
  game: Game | null
  serverRevision: number
  dirty: boolean
  editSeq: number
  saving: boolean
  error: string | null
  notice: string | null
  section: GameSection
  presets: StylePreset[]
  styleJob: ProduceJob | null
  produceJob: ProduceJob | null
  selectedIds: string[]
  load: (workspace: string) => Promise<void>
  openGame: (gameId: string) => Promise<void>
  setSection: (section: GameSection) => void
  patchGame: (patch: Partial<Pick<Game, 'title' | 'genre' | 'view'>> & { style?: Partial<GameStyle> }) => void
  applyPreset: (presetId: string) => void
  saveNow: () => Promise<Game | null>
  createGame: () => Promise<void>
  duplicateGame: () => Promise<void>
  deleteGame: () => Promise<void>
  startStyleSheet: () => Promise<void>
  approveStyle: (references: StyleReference[]) => Promise<void>
  discardSample: (assetId: string, attemptId: string, note: string) => Promise<void>
  addCharacter: (name: string) => Promise<void>
  linkKit: (assetId: string, kitId: string) => Promise<void>
  toggleSelected: (assetId: string) => void
  saveAsset: (assetId: string, patch: Record<string, unknown>) => Promise<void>
  previewList: (body: { text?: string; csv?: string; items?: unknown[]; format?: string }) => Promise<ListReport>
  commitList: (body: { text?: string; csv?: string; items?: unknown[]; format?: string; replace?: boolean }) => Promise<ListReport>
  startProduce: (body: { assetIds?: string[]; rerender?: boolean }) => Promise<void>
  cancelProduce: () => Promise<void>
  resumeProduce: () => Promise<void>
  approveAttempt: (assetId: string, attemptId: string) => Promise<void>
  rejectAttempt: (assetId: string, attemptId: string, note: string) => Promise<void>
  setLock: (assetId: string, locked: boolean) => Promise<void>
  approveClean: () => Promise<void>
  regenerateAsset: (assetId: string) => Promise<void>
}

let saveTimer: ReturnType<typeof setTimeout> | undefined
let pollTimer: ReturnType<typeof setTimeout> | undefined
let produceTimer: ReturnType<typeof setTimeout> | undefined

function remember(workspace: string, gameId: string, produceJobId?: string): void {
  try {
    const previous = JSON.parse(window.localStorage.getItem(SELECTION + workspace) || '{}') as { produceJobId?: string }
    const jobId = produceJobId === undefined ? previous.produceJobId || '' : produceJobId
    window.localStorage.setItem(SELECTION + workspace, JSON.stringify({ gameId, produceJobId: jobId }))
  } catch { /* selection is optional */ }
}

function rememberedJob(workspace: string): string {
  try { return JSON.parse(window.localStorage.getItem(SELECTION + workspace) || '{}').produceJobId || '' } catch { return '' }
}

function remembered(workspace: string): string {
  try { return JSON.parse(window.localStorage.getItem(SELECTION + workspace) || '{}').gameId || '' } catch { return '' }
}

function setupPatch(game: Game): Record<string, unknown> {
  const style = game.style
  return {
    title: game.title, genre: game.genre, view: game.view,
    style: {
      preset: style.preset, traits: style.traits, negative: style.negative, palette: style.palette,
      paletteMode: style.paletteMode, pixel: style.pixel, light: style.light, screen: style.screen,
      model3d: style.model3d, audio: style.audio,
    },
  }
}

function mergeStyle(style: GameStyle, patch?: Partial<GameStyle>): GameStyle {
  if (!patch) return style
  return {
    ...style, ...patch,
    pixel: { ...style.pixel, ...(patch.pixel || {}) },
    audio: { ...style.audio, ...(patch.audio || {}) },
    model3d: { ...style.model3d, ...(patch.model3d || {}) },
  }
}

function armProducePoll(jobId: string): void {
  const tick = async () => {
    const state = useGameAssetsStore.getState()
    if (state.produceJob?.id !== jobId || TERMINAL.has(state.produceJob.status)) return
    try {
      const next = await api.fetchProduceJob(state.workspace, jobId)
      if (useGameAssetsStore.getState().produceJob?.id !== jobId) return
      useGameAssetsStore.setState({ produceJob: next })
      if (!TERMINAL.has(next.status)) {
        produceTimer = setTimeout(() => { void tick() }, 1000)
        return
      }
      const gameId = useGameAssetsStore.getState().game?.id
      if (gameId) await useGameAssetsStore.getState().openGame(gameId)
    } catch (error) {
      useGameAssetsStore.setState({ error: error instanceof Error ? error.message : 'Could not read production' })
    }
  }
  clearTimeout(produceTimer)
  produceTimer = setTimeout(() => { void tick() }, 1000)
}

export const useGameAssetsStore = create<GameAssetsState>((set, get) => ({
  workspace: '',
  ready: false,
  games: [],
  game: null,
  serverRevision: 0,
  dirty: false,
  editSeq: 0,
  saving: false,
  error: null,
  notice: null,
  section: 'setup',
  presets: [],
  styleJob: null,
  produceJob: null,
  selectedIds: [],

  load: async workspace => {
    set({ workspace, ready: false, error: null })
    try {
      const [library, presets] = await Promise.all([api.fetchGameLibrary(workspace), api.fetchGamePresets()])
      if (get().workspace !== workspace) return
      const games = library.games || []
      const wanted = remembered(workspace)
      const id = games.some(item => item.id === wanted) ? wanted : games[0]?.id || ''
      set({ games, presets: presets.presets || [], ready: true })
      if (id) await get().openGame(id)
      else set({ game: null, serverRevision: 0, dirty: false })
      const jobId = rememberedJob(workspace)
      if (jobId && get().workspace === workspace) {
        try {
          const job = await api.fetchProduceJob(workspace, jobId)
          if (get().workspace !== workspace || (job.gameId && job.gameId !== get().game?.id)) return
          set({ produceJob: job })
          if (!TERMINAL.has(job.status)) armProducePoll(job.id)
        } catch { /* an old job id is optional */ }
      }
    } catch (error) {
      if (get().workspace === workspace) set({ ready: true, error: error instanceof Error ? error.message : 'Could not load games' })
    }
  },

  openGame: async gameId => {
    const workspace = get().workspace
    const game = await api.fetchGame(workspace, gameId)
    if (get().workspace !== workspace) return
    remember(workspace, game.id)
    set({
      game, serverRevision: game.revision, dirty: false, error: null, selectedIds: [],
      games: get().games.some(item => item.id === game.id) ? get().games.map(item => item.id === game.id ? game : item) : [...get().games, game],
    })
  },

  setSection: section => set({ section }),

  patchGame: patch => {
    const game = get().game
    if (!game) return
    const next: Game = { ...game, ...patch, style: mergeStyle(game.style, patch.style) }
    set({ game: next, dirty: true, editSeq: get().editSeq + 1, notice: null })
    clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { void get().saveNow() }, 750)
  },

  applyPreset: presetId => {
    const preset = get().presets.find(item => item.id === presetId)
    const game = get().game
    if (!preset || !game) return
    get().patchGame({
      style: {
        preset: preset.id,
        traits: preset.traits,
        negative: preset.negative,
        palette: [...preset.palette],
        pixel: { ...preset.pixel },
        screen: preset.screenDefault || game.style.screen,
        audio: { ...game.style.audio, genre: preset.audio.genre, instruments: preset.audio.instruments, bpm: [...preset.audio.bpm] },
      },
    })
  },

  saveNow: async () => {
    clearTimeout(saveTimer)
    const state = get()
    const game = state.game
    if (!game || !state.dirty) return game
    const seq = state.editSeq
    const id = game.id
    set({ saving: true })
    try {
      const saved = await api.updateGame(state.workspace, id, setupPatch(game), state.serverRevision || game.revision)
      const latest = get()
      const current = latest.game
      if (!current || current.id !== id) {
        set({ saving: false })
        return saved
      }
      const edited = latest.editSeq !== seq
      const visible = edited ? { ...current, revision: saved.revision } : saved
      set({
        game: edited ? current : saved,
        games: latest.games.map(item => item.id === saved.id ? visible : item),
        serverRevision: saved.revision,
        dirty: edited,
        saving: false,
        error: null,
      })
      return edited ? get().saveNow() : saved
    } catch (error) {
      if (error instanceof GameRevisionConflict && get().game?.id === id) {
        const fresh = await api.fetchGame(get().workspace, id)
        set({
          game: fresh, serverRevision: fresh.revision, dirty: false, saving: false,
          notice: 'revision_conflict', error: null,
          games: get().games.map(item => item.id === fresh.id ? fresh : item),
        })
        return fresh
      }
      set({ saving: false, error: error instanceof Error ? error.message : 'Could not save the game' })
      throw error
    }
  },

  createGame: async () => {
    await get().saveNow()
    const created = await api.createGame(get().workspace, { title: 'Untitled game', genre: 'platformer', view: 'side' })
    remember(get().workspace, created.id, '')
    set({ games: [...get().games, created], game: created, serverRevision: created.revision, dirty: false, section: 'setup', error: null, produceJob: null, selectedIds: [] })
  },

  duplicateGame: async () => {
    const source = get().game
    if (!source) return
    await get().saveNow()
    const created = await api.createGame(get().workspace, {
      title: `${source.title} copy`, genre: source.genre, view: source.view,
      style: { ...source.style, approval: 'draft', approvedAt: null, references: [] },
    })
    remember(get().workspace, created.id, '')
    set({ games: [...get().games, created], game: created, serverRevision: created.revision, dirty: false, error: null, produceJob: null, selectedIds: [] })
  },

  deleteGame: async () => {
    const current = get().game
    if (!current) return
    await api.deleteGame(get().workspace, current.id)
    const games = get().games.filter(item => item.id !== current.id)
    set({ games, game: null, dirty: false })
    if (games[0]) await get().openGame(games[0].id)
  },

  startStyleSheet: async () => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    const job = await api.startStyleSheet(get().workspace, game.id)
    set({ styleJob: job })
    const watch = async () => {
      const current = get().styleJob
      if (!current || current.id !== job.id || TERMINAL.has(current.status)) return
      try {
        const next = await api.fetchProduceJob(get().workspace, job.id)
        if (get().styleJob?.id === job.id) set({ styleJob: next })
        if (!TERMINAL.has(next.status)) pollTimer = setTimeout(() => { void watch() }, 1000)
        else await get().openGame(game.id)
      } catch (error) {
        set({ error: error instanceof Error ? error.message : 'Could not read the style sheet' })
      }
    }
    clearTimeout(pollTimer)
    pollTimer = setTimeout(() => { void watch() }, 1000)
  },

  approveStyle: async references => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    const saved = await api.approveGameStyle(get().workspace, game.id, get().serverRevision, references)
    set({ game: saved, serverRevision: saved.revision, dirty: false, games: get().games.map(item => item.id === saved.id ? saved : item) })
  },

  discardSample: async (assetId, attemptId, note) => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    await api.rejectGameAttempt(get().workspace, game.id, assetId, attemptId, note, get().serverRevision)
    await get().openGame(game.id)
  },

  addCharacter: async name => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    const slug = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'personaje'
    const report = await api.gameAssetsFromList(get().workspace, game.id, { text: `personaje ${slug}: ${name} | jugador` })
    if (report.problems?.length) {
      set({ error: report.problems.map(item => item.message || item.code || 'invalid').join(' ') })
      return
    }
    await get().openGame(game.id)
  },

  linkKit: async (assetId, kitId) => {
    const game = get().game
    const asset = game?.assets.find(item => item.id === assetId)
    if (!game || !asset) return
    await get().saveNow()
    await api.updateGameAsset(get().workspace, game.id, assetId, { spec: { ...asset.spec, kitId } }, get().serverRevision)
    await get().openGame(game.id)
  },

  toggleSelected: assetId => {
    const selected = get().selectedIds
    set({ selectedIds: selected.includes(assetId) ? selected.filter(item => item !== assetId) : [...selected, assetId] })
  },

  saveAsset: async (assetId, patch) => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    await api.updateGameAsset(get().workspace, game.id, assetId, patch, get().serverRevision)
    await get().openGame(game.id)
  },

  previewList: async body => {
    const game = get().game
    if (!game) throw new Error('No game')
    return api.gameAssetsFromList(get().workspace, game.id, { ...body, check: true })
  },

  commitList: async body => {
    const game = get().game
    if (!game) throw new Error('No game')
    await get().saveNow()
    const report = await api.gameAssetsFromList(get().workspace, game.id, body)
    if (report.problems?.length) {
      set({ error: report.problems.map(item => item.message || item.code || 'invalid').join(' ') })
      return report
    }
    await get().openGame(game.id)
    return report
  },

  startProduce: async body => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    const job = await api.produceGame(get().workspace, game.id, body)
    remember(get().workspace, game.id, job.id)
    set({ produceJob: job, error: null })
    if (!TERMINAL.has(job.status)) armProducePoll(job.id)
  },

  cancelProduce: async () => {
    const job = get().produceJob
    if (!job) return
    const next = await api.cancelProduceJob(get().workspace, job.id)
    set({ produceJob: next })
  },

  resumeProduce: async () => {
    const job = get().produceJob
    if (!job) return
    const next = await api.resumeProduceJob(get().workspace, job.id)
    set({ produceJob: next, error: null })
    if (!TERMINAL.has(next.status)) armProducePoll(next.id)
  },

  approveAttempt: async (assetId, attemptId) => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    await api.approveGameAttempt(get().workspace, game.id, assetId, attemptId, get().serverRevision)
    await get().openGame(game.id)
  },

  rejectAttempt: async (assetId, attemptId, note) => {
    const game = get().game
    if (!game || !note.trim()) return
    await get().saveNow()
    await api.rejectGameAttempt(get().workspace, game.id, assetId, attemptId, note.trim(), get().serverRevision)
    await get().openGame(game.id)
  },

  setLock: async (assetId, locked) => {
    const game = get().game
    if (!game) return
    await get().saveNow()
    await api.lockGameAsset(get().workspace, game.id, assetId, locked, get().serverRevision)
    await get().openGame(game.id)
  },

  approveClean: async () => {
    const game = get().game
    if (!game) return
    const picks = approvableClean(game.assets)
    await get().saveNow()
    for (const pick of picks) {
      await api.approveGameAttempt(get().workspace, game.id, pick.assetId, pick.attemptId, get().serverRevision)
      await get().openGame(game.id)
    }
  },

  regenerateAsset: async assetId => {
    await get().startProduce({ assetIds: [assetId], rerender: true })
    get().setSection('produce')
  },
}))

export type { PaletteMode }
