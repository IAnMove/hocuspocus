import type { GameAsset, GameAttempt } from './types'

export interface AtlasFrame {
  name: string
  x: number
  y: number
  w: number
  h: number
  duration: number
}

export interface AudioSource {
  key: string
  file: string
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function fileUrl(file: string, workspace: string): string {
  if (!file) return ''
  const path = file.split('/').map(encodeURIComponent).join('/')
  return `/api/v1/file/${path}?workspace=${encodeURIComponent(workspace)}`
}

export function atlasFrames(atlas: unknown): AtlasFrame[] {
  const frames = record(record(atlas).frames)
  const list = Object.entries(frames).map(([name, value]) => {
    const entry = record(value)
    const frame = record(entry.frame)
    return {
      name,
      x: num(frame.x),
      y: num(frame.y),
      w: num(frame.w),
      h: num(frame.h),
      duration: num(entry.duration) || 100,
    }
  })
  list.sort((left, right) => left.y - right.y || left.x - right.x || left.name.localeCompare(right.name))
  return list
}

export function atlasLoops(atlas: unknown): boolean {
  const loop = record(record(atlas).meta).loop
  if (typeof loop === 'boolean') return loop
  if (loop && typeof loop === 'object') return Object.values(loop as Record<string, unknown>).some(Boolean)
  return true
}

export function frameDelayMs(duration: number | undefined): number {
  return duration && duration > 0 ? duration : 100
}

export function stepFrame(index: number, count: number, loop: boolean): number {
  if (count <= 1) return 0
  const next = index + 1
  if (next < count) return next
  return loop ? 0 : index
}

/** One warning with a stable key. ``code`` picks the translation; ``message`` is the server text. */
export interface ReviewWarning {
  key: string
  code: string
  message: string
  file: string
  /** ``duplicate_of:<id>`` keeps the id here. */
  ref: string
}

function readWarning(item: unknown, index: number): ReviewWarning {
  if (typeof item === 'string') {
    const [code, ref = ''] = item.split(':', 2)
    return { key: `${item}-${index}`, code, message: item, file: '', ref }
  }
  const entry = record(item)
  const code = typeof entry.code === 'string' ? entry.code : ''
  const file = typeof entry.file === 'string' ? entry.file : ''
  const message = typeof entry.message === 'string' ? entry.message : ''
  return { key: `${code || 'warning'}-${file}-${index}`, code, message, file, ref: '' }
}

export function attemptWarnings(attempt: GameAttempt | null | undefined): ReviewWarning[] {
  return Array.isArray(attempt?.warnings) ? attempt.warnings.map(readWarning) : []
}

/** Candidates that succeeded and still wait for a decision. */
export function undecidedAttempts(asset: GameAsset): GameAttempt[] {
  return asset.attempts.filter(item => item.status === 'ok' && !item.decision)
}

/** Assets in review, and rejected assets whose other candidates are still undecided. */
export function reviewAssets(assets: GameAsset[], kind: string): GameAsset[] {
  return assets.filter(asset => {
    if (kind && asset.kind !== kind) return false
    if (asset.status === 'review') return true
    return asset.status === 'rejected' && undecidedAttempts(asset).length > 0
  })
}

/** One pick per listed asset that has exactly one undecided candidate and no warning on it. */
export function approvableClean(assets: GameAsset[]): { assetId: string; attemptId: string }[] {
  const picks: { assetId: string; attemptId: string }[] = []
  for (const asset of reviewAssets(assets, '')) {
    const open = undecidedAttempts(asset)
    if (open.length !== 1 || attemptWarnings(open[0]).length) continue
    picks.push({ assetId: asset.id, attemptId: open[0].id })
  }
  return picks
}

const HIDDEN_METRICS = new Set(['candidates', 'attemptIds'])
const FIRST_METRICS = ['loopStart', 'loopEnd', 'missingClips']

function metricValue(value: unknown): string | null {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value) && value.every(item => typeof item === 'string' || typeof item === 'number')) return value.join(', ')
  return null
}

/** ``key: value`` lines; loop points and missing clips come first and are never cut. */
export function metricLines(metrics: Record<string, unknown> | undefined): string[] {
  if (!metrics) return []
  const keys = Object.keys(metrics).filter(key => !HIDDEN_METRICS.has(key))
  const ordered = [...FIRST_METRICS.filter(key => keys.includes(key)), ...keys.filter(key => !FIRST_METRICS.includes(key))]
  const lines: string[] = []
  for (const key of ordered) {
    const value = metricValue(metrics[key])
    if (value === null || (key === 'missingClips' && !value)) continue
    lines.push(`${key}: ${value}`)
  }
  return lines.slice(0, 10) // the first metrics lead, so the cut never drops them
}

export function stillFile(files: Record<string, string>): string {
  return files.preview || files.main || files.sheet || ''
}

export function sheetFile(files: Record<string, string>): string {
  return files.sheet || files.main || files.preview || ''
}

export function layerFiles(files: Record<string, string>): string[] {
  return Object.entries(files).filter(([key]) => key.startsWith('layer')).map(([, file]) => file)
}

export function playbackSources(files: Record<string, string>): AudioSource[] {
  const numbered = Object.entries(files)
    .filter(([key]) => /^\d+$/.test(key))
    .sort((left, right) => Number(left[0]) - Number(right[0]))
  if (numbered.length) return numbered.map(([key, file]) => ({ key, file }))
  if (files.ogg || files.wav) return [{ key: files.ogg ? 'ogg' : 'wav', file: files.ogg || files.wav }]
  return []
}

/** The music file for the Web Audio loop: the WAV keeps sample-exact loop points. */
export function musicFile(files: Record<string, string>): string {
  return files.wav || files.ogg || files.main || ''
}

/** Loop points in samples, ``loopEnd`` inclusive; ``null`` when the take has none. */
export function loopSamples(metrics: Record<string, unknown> | undefined): { start: number; end: number } | null {
  const end = metrics?.loopEnd
  if (typeof end !== 'number' || !Number.isFinite(end)) return null
  return { start: num(metrics?.loopStart), end }
}

export function clipNames(metrics: Record<string, unknown> | undefined): string[] {
  const clips = metrics?.clips
  return Array.isArray(clips) ? clips.map(item => String(item)) : []
}

export function modelFile(files: Record<string, string>): string {
  return files.rig || files.model || ''
}
