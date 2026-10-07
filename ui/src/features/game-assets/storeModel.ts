import type { Game, GamePatch, GameStyle, ProduceJob, StylePatch } from './types'

/** Jobs the server still works on; ``start`` and ``resume`` answer 409 already_running meanwhile. */
export const ACTIVE_JOB = new Set(['queued', 'running', 'cancelling'])
export const RESUMABLE_JOB = new Set(['cancelled', 'interrupted', 'failed'])

export function isActiveJob(job: ProduceJob | null | undefined): boolean {
  return Boolean(job && ACTIVE_JOB.has(job.status))
}

/** Steps skipped until a dependency is approved; ``resume`` queues them again. */
export function hasWaitingSteps(job: ProduceJob | null | undefined): boolean {
  return Boolean(job?.steps?.some(step => step.status === 'skipped' && step.reason === 'waiting_dependency'))
}

export function canResumeJob(job: ProduceJob | null | undefined): boolean {
  if (!job || isActiveJob(job)) return false
  return RESUMABLE_JOB.has(job.status) || hasWaitingSteps(job)
}

/** Finished steps, used to refresh the game while a job writes attempts. */
export function finishedSteps(job: ProduceJob | null | undefined): number {
  return (job?.steps || []).filter(step => step.status === 'done' || step.status === 'failed').length
}

/** Exponential poll delay after ``failures`` errors in a row, capped at 30 s. */
export function pollDelay(failures: number): number {
  return failures <= 0 ? 1000 : Math.min(30000, 1000 * 2 ** failures)
}

export function mergeStylePatch(base: StylePatch | undefined, next: StylePatch | undefined): StylePatch | undefined {
  if (!next) return base
  if (!base) return next
  return {
    ...base, ...next,
    ...(base.pixel || next.pixel ? { pixel: { ...base.pixel, ...next.pixel } } : {}),
    ...(base.audio || next.audio ? { audio: { ...base.audio, ...next.audio } } : {}),
    ...(base.model3d || next.model3d ? { model3d: { ...base.model3d, ...next.model3d } } : {}),
  }
}

/** ``next`` wins; nested pixel, audio and model3d keys merge. */
export function mergeGamePatch(base: GamePatch | null, next: GamePatch | null): GamePatch | null {
  if (!next) return base
  if (!base) return next
  const style = mergeStylePatch(base.style, next.style)
  return { ...base, ...next, ...(style ? { style } : {}) }
}

export function applyStyle(style: GameStyle, patch: StylePatch | undefined): GameStyle {
  if (!patch) return style
  return {
    ...style, ...patch,
    pixel: { ...style.pixel, ...patch.pixel },
    audio: { ...style.audio, ...patch.audio },
    model3d: { ...style.model3d, ...patch.model3d },
  }
}

export function applyGamePatch(game: Game, patch: GamePatch | null): Game {
  if (!patch) return game
  return { ...game, ...patch, style: applyStyle(game.style, patch.style) }
}

export function upsertGame(games: Game[], game: Game): Game[] {
  return games.some(item => item.id === game.id) ? games.map(item => item.id === game.id ? game : item) : [...games, game]
}

const SELECTION = 'hocuspocus.gameAssets.'

/** The open game and the last produce job of each game, per workspace. */
export interface GameSelection {
  gameId: string
  jobs: Record<string, string>
}

export function readSelection(workspace: string): GameSelection {
  try {
    const raw = JSON.parse(window.localStorage.getItem(SELECTION + workspace) || '{}') as Partial<GameSelection>
    const jobs = raw.jobs && typeof raw.jobs === 'object' ? raw.jobs : {}
    return { gameId: typeof raw.gameId === 'string' ? raw.gameId : '', jobs }
  } catch {
    return { gameId: '', jobs: {} }
  }
}

function writeSelection(workspace: string, selection: GameSelection): void {
  try { window.localStorage.setItem(SELECTION + workspace, JSON.stringify(selection)) } catch { /* selection is optional */ }
}

export function rememberGame(workspace: string, gameId: string): void {
  writeSelection(workspace, { ...readSelection(workspace), gameId })
}

/** ``jobId`` '' forgets the job of ``gameId``. */
export function rememberJob(workspace: string, gameId: string, jobId: string): void {
  const selection = readSelection(workspace)
  const jobs = { ...selection.jobs }
  if (jobId) jobs[gameId] = jobId
  else delete jobs[gameId]
  writeSelection(workspace, { ...selection, jobs })
}

export function forgetGame(workspace: string, gameId: string): void {
  const selection = readSelection(workspace)
  const jobs = { ...selection.jobs }
  delete jobs[gameId]
  writeSelection(workspace, { gameId: selection.gameId === gameId ? '' : selection.gameId, jobs })
}
