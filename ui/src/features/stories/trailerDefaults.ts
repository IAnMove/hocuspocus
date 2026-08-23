import type { StoryProjectType } from './types'

export const DEFAULT_TRAILER_DURATION = 60

export function trailerDurationForProject(projectType: StoryProjectType, durationSeconds: number): number {
  if (projectType !== 'trailer' && projectType !== 'quick_video') return DEFAULT_TRAILER_DURATION
  const duration = Number.isFinite(durationSeconds) && durationSeconds > 0
    ? durationSeconds
    : DEFAULT_TRAILER_DURATION
  return Math.max(15, Math.min(180, duration))
}

export function syncTrailerDuration(
  currentDuration: number,
  projectType: StoryProjectType,
  projectDuration: number,
  trailerTouched: boolean,
): number {
  return trailerTouched
    ? currentDuration
    : trailerDurationForProject(projectType, projectDuration)
}
