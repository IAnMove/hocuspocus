import * as api from '../../api/client'
import type {
  SeriesAsset, SeriesEpisode, SeriesEpisodeReview, SeriesProductionMode, SeriesProject, SeriesRenderAttempt,
  SeriesReviewStage, SeriesReviewStatus, SeriesShot, SeriesShotReview,
} from './types'

/**
 * Staged review of an episode, the same rules as the server (services/series_review.py): what each shot waits for,
 * the counts, the production steps and the next one. Only the review state is read; whether a take is out of date
 * with its inputs is the server render's business.
 */
export const PRODUCTION_MODES: readonly SeriesProductionMode[] = ['direct', 'plan', 'preview']
export type ShotStep = 'changes' | 'approve_plan' | 'render' | 'render_previews' | 'approve_previews' | 'render_final' | 'ready'
export type EpisodeStep = Exclude<ShotStep, 'ready'> | 'assemble'
/** all; pending (still waiting for a decision); changes (a change was requested); approved (passed every review the mode asks for). */
export type ReviewFilter = 'all' | 'pending' | 'changes' | 'approved'
export const REVIEW_FILTERS: readonly ReviewFilter[] = ['all', 'pending', 'changes', 'approved']
const STEP_ORDER: readonly Exclude<EpisodeStep, 'assemble'>[] = ['changes', 'approve_plan', 'render', 'render_previews', 'approve_previews', 'render_final']
const USER_STEPS = new Set<EpisodeStep>(['approve_plan', 'render', 'render_previews', 'approve_previews', 'render_final'])
const STATUSES = new Set<SeriesReviewStatus>(['pending', 'approved', 'changes'])

export function episodeReview(episode: SeriesEpisode): SeriesEpisodeReview {
  const review = episode.review
  const mode = review && PRODUCTION_MODES.includes(review.mode) ? review.mode : 'direct'
  return { mode, updatedAt: review?.updatedAt, shots: review?.shots && typeof review.shots === 'object' ? review.shots : {} }
}

export function shotReview(episode: SeriesEpisode, shotId: string): SeriesShotReview {
  const entry = episodeReview(episode).shots[shotId]
  return {
    ...entry,
    plan: entry && STATUSES.has(entry.plan) ? entry.plan : 'pending',
    preview: entry && STATUSES.has(entry.preview) ? entry.preview : 'pending',
    notes: Array.isArray(entry?.notes) ? entry.notes : [],
  }
}

export function latestTake(shot: SeriesShot): SeriesRenderAttempt | undefined {
  return [...shot.attempts].reverse().find(item => item.status === 'completed' && item.reviewDecision !== 'rejected')
}

function approvedTake(shot: SeriesShot): SeriesRenderAttempt | undefined {
  return shot.attempts.find(item => item.id === shot.approvedAttemptId && item.status === 'completed')
}

/** A preview of this shot looks like its final: anything but a 3D shot rendered at a better quality than draft. */
export function finalEquivalent(shot: SeriesShot): boolean {
  if (shot.productionMethod !== 'animation_3d') return true
  return !shot.scene3d?.quality || shot.scene3d.quality === 'draft'
}

function readyForAssembly(shot: SeriesShot, entry: SeriesShotReview, mode: SeriesProductionMode): boolean {
  const approved = approvedTake(shot)
  if (!approved) return false
  if (mode !== 'preview') return true
  if (approved.id === entry.previewAttemptId) return approved.reviewStage !== 'preview' || finalEquivalent(shot)
  const reviewed = shot.attempts.findIndex(item => item.id === entry.previewAttemptId)
  return approved.reviewStage === 'final' && reviewed >= 0 && shot.attempts.indexOf(approved) > reviewed
}

function previewStep(shot: SeriesShot, entry: SeriesShotReview): ShotStep {
  if (entry.preview === 'approved') return readyForAssembly(shot, entry, 'preview') ? 'ready' : 'render_final'
  if (entry.preview === 'changes') return 'changes'
  return latestTake(shot) ? 'approve_previews' : 'render_previews'
}

/** What a shot waits for in this mode (the contract's classification). */
export function classifyShot(shot: SeriesShot, entry: SeriesShotReview, mode: SeriesProductionMode): ShotStep {
  if (mode === 'direct') return approvedTake(shot) ? 'ready' : 'render'
  if (entry.plan === 'changes') return 'changes'
  if (entry.plan === 'pending') return 'approve_plan'
  if (mode === 'plan') return approvedTake(shot) ? 'ready' : 'render'
  return previewStep(shot, entry)
}

/** The stage the Approve / Request change buttons act on: the plan until it is approved, then the preview (take). */
export function reviewStage(mode: SeriesProductionMode, entry: SeriesShotReview, shot: SeriesShot): 'plan' | 'preview' {
  if (mode === 'plan') return 'plan'
  if (mode === 'preview') return entry.plan === 'approved' ? 'preview' : 'plan'
  return latestTake(shot) ? 'preview' : 'plan'
}

/** Stage a new note is filed under (same default as the server). */
export function noteStage(mode: SeriesProductionMode, entry: SeriesShotReview): SeriesReviewStage {
  if (mode === 'direct') return 'final'
  if (mode === 'plan') return 'plan'
  return entry.plan === 'approved' ? 'preview' : 'plan'
}

export function filterStatus(shot: SeriesShot, entry: SeriesShotReview, mode: SeriesProductionMode): Exclude<ReviewFilter, 'all'> {
  if (entry.plan === 'changes' || entry.preview === 'changes') return 'changes'
  if (mode === 'plan') return entry.plan === 'approved' ? 'approved' : 'pending'
  if (mode === 'preview') return entry.preview === 'approved' ? 'approved' : 'pending'
  return entry[reviewStage(mode, entry, shot)] === 'approved' ? 'approved' : 'pending'
}

export function matchesFilter(filter: ReviewFilter, shot: SeriesShot, entry: SeriesShotReview, mode: SeriesProductionMode): boolean {
  return filter === 'all' || filterStatus(shot, entry, mode) === filter
}

export interface ReviewSummary {
  mode: SeriesProductionMode
  total: number
  plan: Record<SeriesReviewStatus, number>
  preview: Record<SeriesReviewStatus, number>
  ready: number
  filters: Record<ReviewFilter, number>
  steps: Array<{ kind: Exclude<EpisodeStep, 'assemble'>; count: number }>
  nextStep: { kind: EpisodeStep; count: number }
}

const zero = (): Record<SeriesReviewStatus, number> => ({ pending: 0, approved: 0, changes: 0 })

export function reviewSummary(episode: SeriesEpisode): ReviewSummary {
  const { mode } = episodeReview(episode)
  const plan = zero(), preview = zero()
  const filters: Record<ReviewFilter, number> = { all: episode.shots.length, pending: 0, changes: 0, approved: 0 }
  const byStep = new Map<ShotStep, number>()
  for (const shot of episode.shots) {
    const entry = shotReview(episode, shot.id)
    plan[entry.plan] += 1; preview[entry.preview] += 1
    filters[filterStatus(shot, entry, mode)] += 1
    const step = classifyShot(shot, entry, mode)
    byStep.set(step, (byStep.get(step) || 0) + 1)
  }
  const steps: ReviewSummary['steps'] = STEP_ORDER.filter(kind => byStep.get(kind)).map(kind => ({ kind, count: byStep.get(kind) || 0 }))
  const nextStep = steps.find(step => USER_STEPS.has(step.kind)) || steps[0] || { kind: 'assemble' as const, count: episode.shots.length }
  return { mode, total: episode.shots.length, plan, preview, ready: byStep.get('ready') || 0, filters, steps, nextStep }
}

export interface SceneGroup {
  sceneId: string
  number: number
  title: string
  locationId?: string
  time: string
  shots: SeriesShot[]
}

/** Shots in episode order, grouped by their scene in script order (a shot of an unknown scene closes the list). */
export function groupShotsByScene(episode: SeriesEpisode): SceneGroup[] {
  const scenes = [...episode.script].sort((a, b) => a.order - b.order)
  const groups = new Map<string, SceneGroup>()
  scenes.forEach((scene, index) => groups.set(scene.id, {
    sceneId: scene.id, number: index + 1, title: scene.purpose, locationId: scene.locationId, time: scene.time, shots: [],
  }))
  for (const shot of [...episode.shots].sort((a, b) => a.order - b.order)) {
    if (!groups.has(shot.sceneId)) groups.set(shot.sceneId, { sceneId: shot.sceneId, number: groups.size + 1, title: '', time: '', shots: [] })
    groups.get(shot.sceneId)!.shots.push(shot)
  }
  return [...groups.values()].filter(group => group.shots.length)
}

export interface CastMember { characterId: string; name: string; poseId?: string; x?: number }

export function shotCast(series: SeriesProject, shot: SeriesShot): CastMember[] {
  const names = new Map(series.characters.map(item => [item.id, item.name]))
  const cast = Array.isArray(shot.layout2d?.cast) ? shot.layout2d.cast : []
  const scene3d = Array.isArray(shot.scene3d?.cast) ? shot.scene3d.cast : []
  const entries: CastMember[] = cast.length
    ? cast.map(entry => ({ characterId: entry.characterId, poseId: entry.poseId, x: entry.x, name: '' }))
    : scene3d.length ? scene3d.map(entry => ({ characterId: entry.characterId, poseId: entry.poseId, name: '' }))
      : shot.visibleCharacterIds.map(characterId => ({ characterId, name: '' }))
  return entries.map(entry => ({ ...entry, name: names.get(entry.characterId) || entry.characterId }))
}

export function shotLines(series: SeriesProject, shot: SeriesShot) {
  const names = new Map(series.characters.map(item => [item.id, item.name]))
  return shot.dialogueBeats.filter(beat => beat.text.trim())
    .map(beat => ({ id: beat.id, speaker: names.get(beat.characterId) || beat.characterId, text: beat.text }))
}

const listLength = (value: unknown) => Array.isArray(value) ? value.length : 0

/** A short account of what dresses the shot: effects, sounds, props, set layers, card, music and the 3D source. */
export function shotExtras(shot: SeriesShot) {
  const layout = shot.layout2d || {}
  const fx = Array.isArray(layout.fx) ? layout.fx as Array<{ kind?: unknown }> : []
  const card = layout.card && typeof layout.card === 'object' ? (layout.card as { kind?: string }).kind : undefined
  const music = layout.music && typeof layout.music === 'object' ? (layout.music as { file?: string }).file : undefined
  const scene3d = shot.scene3d
  return {
    fxKinds: [...new Set(fx.map(item => String(item.kind || '')).filter(Boolean))],
    sfx: listLength(layout.sfx), props: listLength(layout.props), layers: listLength(layout.layers),
    card, music,
    scene3d: scene3d ? { source: scene3d.template || scene3d.scene || '', objects: listLength(scene3d.objects),
      quality: scene3d.quality || 'draft', look: scene3d.renderLook } : undefined,
  }
}

export type DressingKey = 'fx' | 'sfx' | 'props' | 'layers' | 'cardKind' | 'music' | 'scene3d'

/** The dressing of a shot as message keys and values (approval.card.*), in a fixed order. */
export function shotDressing(shot: SeriesShot): Array<{ key: DressingKey; values: Record<string, string | number> }> {
  const extras = shotExtras(shot)
  const items: Array<{ key: DressingKey; values: Record<string, string | number> } | false> = [
    extras.fxKinds.length > 0 && { key: 'fx', values: { list: extras.fxKinds.join(', ') } },
    extras.sfx > 0 && { key: 'sfx', values: { count: extras.sfx } },
    extras.props > 0 && { key: 'props', values: { count: extras.props } },
    extras.layers > 0 && { key: 'layers', values: { count: extras.layers } },
    Boolean(extras.card) && { key: 'cardKind', values: { kind: extras.card! } },
    Boolean(extras.music) && { key: 'music', values: { file: extras.music! } },
    Boolean(extras.scene3d) && { key: 'scene3d', values: { source: extras.scene3d!.source, objects: extras.scene3d!.objects, quality: extras.scene3d!.quality } },
  ]
  return items.filter((item): item is Exclude<typeof item, false> => Boolean(item))
}

export interface TakeMedia { attempt: SeriesRenderAttempt; asset: SeriesAsset; url: string; thumbnail: string; sceneFilename?: string }

/** The latest take's video, thumbnail and editable scene file. */
export function latestTakeMedia(series: SeriesProject, shot: SeriesShot): TakeMedia | undefined {
  const attempt = latestTake(shot)
  const asset = attempt?.outputAssetIds.map(id => series.assets[id]).find(item => item?.kind === 'video')
  if (!attempt || !asset) return undefined
  const filename = asset.uri.replace(/^outputs\//, '')
  const scene = asset.metadata?.sceneFilename
  return {
    attempt, asset, url: api.getFileUrl(filename, asset.workspaceId), thumbnail: api.getOutputThumbnailUrl(filename, asset.workspaceId),
    sceneFilename: typeof scene === 'string' && scene ? scene : undefined,
  }
}

/** The note the notes box keeps editing: the stage's last note when the user wrote it (an agent reply starts a new one). */
export function draftNote(entry: SeriesShotReview, stage: SeriesReviewStage) {
  const last = [...entry.notes].reverse().find(note => note.stage === stage)
  return last?.by === 'user' ? last : undefined
}

export function canRenderOnServer(shot: SeriesShot): boolean {
  return shot.productionMethod === 'animation_2d' || shot.productionMethod === 'animation_3d'
}
