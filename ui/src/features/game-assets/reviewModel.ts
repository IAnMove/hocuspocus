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

export function attemptWarnings(attempt: GameAttempt | null | undefined): string[] {
  return Array.isArray(attempt?.warnings) ? attempt.warnings.map(item => String(item)) : []
}

export function chosenAttempt(asset: GameAsset): GameAttempt | null {
  const approved = asset.attempts.find(item => item.id === asset.approvedAttemptId)
  if (approved) return approved
  const open = [...asset.attempts].reverse().find(item => item.status === 'ok' && item.decision !== 'rejected')
  return open || asset.attempts[asset.attempts.length - 1] || null
}

export function reviewAssets(assets: GameAsset[], kind: string): GameAsset[] {
  return assets.filter(asset => asset.status === 'review' && (!kind || asset.kind === kind))
}

export function approvableClean(assets: GameAsset[]): { assetId: string; attemptId: string }[] {
  const picks: { assetId: string; attemptId: string }[] = []
  for (const asset of assets) {
    if (asset.status !== 'review') continue
    const attempt = chosenAttempt(asset)
    if (!attempt || attemptWarnings(attempt).length) continue
    picks.push({ assetId: asset.id, attemptId: attempt.id })
  }
  return picks
}

export function metricLines(metrics: Record<string, unknown> | undefined): string[] {
  if (!metrics) return []
  return Object.entries(metrics)
    .filter(([, value]) => typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
    .slice(0, 8)
    .map(([key, value]) => `${key}: ${value}`)
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

export function loopRange(metrics: Record<string, unknown> | undefined, sampleRate = 48000): { start: number; end: number } {
  const duration = num(metrics?.duration)
  let start = num(metrics?.loopStart)
  let end = num(metrics?.loopEnd)
  if (sampleRate > 0 && end > duration + 1) {
    start /= sampleRate
    end /= sampleRate
  }
  if (end <= start) end = duration > start ? duration : start
  return { start, end }
}

export function seamTime(end: number): number {
  return Math.max(0, end - 2)
}

export function countLoop(previous: number, current: number, end: number, turns: number): number {
  if (current + 0.05 < previous && previous > end - 0.25) return turns + 1
  return turns
}

export function clipNames(metrics: Record<string, unknown> | undefined): string[] {
  const clips = metrics?.clips
  return Array.isArray(clips) ? clips.map(item => String(item)) : []
}

export function modelFile(files: Record<string, string>): string {
  return files.rig || files.model || ''
}
