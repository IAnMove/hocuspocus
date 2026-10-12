import { BASE } from './http'
import { SeriesRequestError } from './series'
import type { SeriesEpisodeReview, SeriesLanguageVersion, SeriesShot, SeriesShotScene3D } from '../features/series/types'

/** One line of a shot in the script vocabulary of series.episode.from_script: the speaker and its text in every language
 * (keyed by language name: `spanish`, `english`...), with its delivery, pause and room. */
export interface SeriesScriptLine {
  who: string
  emotion?: string
  delivery?: string
  pauseBefore?: number
  voiceRoom?: string
  [language: string]: unknown
}

/** A stored shot as series.shot.get returns it: the keys series.shot.update changes. */
export interface SeriesShotScript {
  scene?: string
  location?: string
  variant?: string
  framing?: string
  camera?: string
  cast?: Array<Record<string, unknown>>
  lines?: SeriesScriptLine[]
  card?: Record<string, unknown>
  music?: Record<string, unknown>
  sfx?: Array<Record<string, unknown>>
  fx?: Array<Record<string, unknown>>
  props?: Array<Record<string, unknown>>
  layers?: Array<Record<string, unknown>>
  timing?: { intro?: number; gap?: number; tail?: number }
  voiceRoom?: string
  castDepth?: number
  clipAudio?: 'keep' | 'drop'
  clipVolume?: number
  clipFit?: 'cover' | 'contain'
  kind?: string
  scene3d?: SeriesShotScene3D
  foley?: { prompt: string; volume?: number }
  duration?: number
  [key: string]: unknown
}

export interface SeriesShotView {
  shotId: string
  number: number
  productionMethod?: string
  approvedAttemptId?: string
  takes: Array<{ id: string; status: string; approved: boolean }>
  script: SeriesShotScript
}

export interface SeriesShotEditBody {
  shot: string | number
  changes?: Record<string, unknown>
  append?: Record<string, unknown>
  render?: boolean
  approve?: boolean
}

export interface SeriesShotEditReply {
  shotId: string
  number: number
  changed: string[]
  approvalReset: boolean
  missingLines: Record<string, string[]>
  revision: number
  shot: SeriesShotView
  note?: string
  render?: { jobId?: string }
  /** The stored shot and what the edit changed around it, to merge into Series Lab's open copy. */
  stored?: {
    episodeId: string
    episodeUpdatedAt?: string
    shot: SeriesShot
    review?: SeriesEpisodeReview
    languageVersions?: Record<string, SeriesLanguageVersion>
  }
}

export interface SeriesLineVoice {
  beatId: string
  number: number
  characterId: string
  text: string
  recorded: boolean
  voice?: boolean
  problem?: string
  key?: string
  filename?: string
  url?: string
  recordedAt?: number
  newerThanTake?: boolean
  room?: string
  roomUrl?: string
}

export interface SeriesLineVoiceJob {
  jobId: string
  shotId: string
  beatId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
  retake?: boolean
  result?: { filename: string; url: string; duration?: number; wer?: number | null; reused?: boolean; retake?: boolean }
  error?: string
  errorCode?: string
}

export interface SeriesShotScene3DEditor {
  shotId: string
  sceneId: string
  revision: number
  document: unknown
  source: { template?: string; scene?: string }
  duration: number
}

export interface SeriesShotScene3DSaved {
  shotId: string
  scene3d: SeriesShotScene3D
  file: string
  removedObjects: string[]
}

async function reply<T>(request: Promise<Response>, fallback: string): Promise<T> {
  const response = await request
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: fallback }))
    const detail = body.detail
    const message = typeof detail === 'object' && detail ? detail.message : detail
    const problems = typeof detail === 'object' && Array.isArray(detail?.problems) ? detail.problems as string[] : []
    const shown = problems.length > 1 || (problems[0] && problems[0] !== message) ? `${message}: ${problems.slice(0, 6).join('; ')}` : message
    throw new SeriesRequestError(shown || fallback, response.status, typeof detail?.code === 'string' ? detail.code : undefined, detail)
  }
  return response.json() as Promise<T>
}

const shotsPath = (seriesId: string, episodeId: string) =>
  `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/shots`
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

/** series.shot.get: the shot in the script vocabulary its edit uses. */
export function fetchSeriesShotView(workspace: string, seriesId: string, episodeId: string, shot: string): Promise<SeriesShotView> {
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/${encodeURIComponent(shot)}?workspace=${encodeURIComponent(workspace)}`,
    { cache: 'no-store' }), 'Could not read the shot')
}

/** series.shot.update: only what changes, checked like a script shot; the reply carries the stored shot to merge. */
export function editSeriesShot(workspace: string, seriesId: string, episodeId: string, body: SeriesShotEditBody): Promise<SeriesShotEditReply> {
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/edit`, json({ workspace, ...body, stored: true })), 'The shot could not be saved')
}

export function fetchShotVoices(workspace: string, seriesId: string, episodeId: string, shot: string, language?: string):
Promise<{ shotId: string; language: string; lines: SeriesLineVoice[]; recording: SeriesLineVoiceJob[] }> {
  const query = new URLSearchParams({ workspace, ...(language ? { language } : {}) })
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/${encodeURIComponent(shot)}/voices?${query}`, { cache: 'no-store' }),
    'Could not read the shot lines')
}

/** Record one line now (a retake: another take that replaces it once it is good). */
export function startShotVoice(workspace: string, seriesId: string, episodeId: string, shot: string, line: string | number,
  retake = false): Promise<SeriesLineVoiceJob> {
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/${encodeURIComponent(shot)}/voices`, json({ workspace, line, retake })),
    'Could not record the line')
}

export function fetchShotVoiceJob(workspace: string, jobId: string): Promise<SeriesLineVoiceJob> {
  return reply(fetch(`${BASE}/api/v1/series/voice-jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`,
    { cache: 'no-store' }), 'Could not read the recording')
}

/** The 3D shot's scene (template or saved scene, its objects, length and look) to open in the Video 3D editor. */
export function openShotScene3D(workspace: string, seriesId: string, episodeId: string, shot: string): Promise<SeriesShotScene3DEditor> {
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/${encodeURIComponent(shot)}/scene3d/editor`, json({ workspace })),
    'Could not open the 3D scene of the shot')
}

/** Save the scene edited in the Video 3D editor; returns the shot's new scene3d (write it with editSeriesShot). */
export function saveShotScene3D(workspace: string, seriesId: string, episodeId: string, shot: string, document: unknown):
Promise<SeriesShotScene3DSaved> {
  return reply(fetch(`${shotsPath(seriesId, episodeId)}/${encodeURIComponent(shot)}/scene3d/from-editor`, json({ workspace, document })),
    'Could not save the 3D scene to the shot')
}

export type SeriesShotFileKind = 'audio' | 'image' | 'video' | 'model'

/** Workspace files a shot can name (sounds, music, prop and layer images, layer videos, 3D models). */
export function fetchShotFiles(workspace: string, seriesId: string, kind: SeriesShotFileKind): Promise<{ files: string[] }> {
  return reply(fetch(`${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/shot-files?workspace=${encodeURIComponent(workspace)}&kind=${kind}`, { cache: 'no-store' }),
    'Could not list the workspace files')
}
