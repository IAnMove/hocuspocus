import type { AspectRatio, ResolutionPreset } from '../../types'

export const STORY_VIDEO_RESOLUTIONS: ResolutionPreset[] = ['480p', '540p', '720p', '1080p']
export const STORY_VIDEO_SAVED_RESOLUTIONS: ResolutionPreset[] = [...STORY_VIDEO_RESOLUTIONS, '768p']
export const STORY_VIDEO_ASPECTS: Array<{ value: AspectRatio; label: string; detail: string }> = [
  { value: '16:9', label: 'Landscape', detail: '16:9 · standard video' },
  { value: '9:16', label: 'Portrait / Shorts', detail: '9:16 · vertical video' },
]

export function savedStoryVideoResolution(value: unknown, fallback: ResolutionPreset): ResolutionPreset {
  return STORY_VIDEO_SAVED_RESOLUTIONS.includes(value as ResolutionPreset)
    ? value as ResolutionPreset
    : fallback
}

export function savedStoryVideoAspect(value: unknown, fallback: AspectRatio): AspectRatio {
  return STORY_VIDEO_ASPECTS.some(option => option.value === value)
    ? value as AspectRatio
    : fallback
}
