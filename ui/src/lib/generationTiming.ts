import type { OutputGenerationTimings } from '../types'

export function formatGenerationDuration(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return ''
  const totalSeconds = Math.round(seconds)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const remainder = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m ${remainder}s`
  if (minutes > 0) return `${minutes}m ${remainder}s`
  return `${remainder}s`
}

export function formatGenerationBreakdown(
  timings?: OutputGenerationTimings,
): string {
  if (!timings) return ''
  const entries: Array<[string, number | null | undefined]> = [
    ['Prompts', timings.prompt_generation_time_sec],
    ['Images', timings.image_generation_time_sec],
    ['Video + assembly', timings.video_generation_time_sec],
    ['Latest re-join', timings.assembly_time_sec],
  ]
  return entries
    .filter((entry): entry is [string, number] => (
      entry[1] != null && Number.isFinite(entry[1]) && entry[1] >= 0
    ))
    .map(([label, seconds]) => `${label} ${formatGenerationDuration(seconds)}`)
    .join(' · ')
}
