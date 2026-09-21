/** Opt-in 30s H3 pass. Off by default; catalog frames_maximum stays 345. */

export const H3_EXPERIMENTAL_MAX_FRAMES = 719
export const H3_EXPERIMENTAL_MAX_SECONDS = 30

export function supportsH3ExtendedDuration(options?: {
  architecture?: string
  audio_only?: boolean
  model_type?: string
  minimax_h3_viggle?: boolean
} | null): boolean {
  return !!options
    && !options.audio_only
    && options.model_type !== 'viggle_animate'
    && !options.minimax_h3_viggle
    && String(options.architecture || options.model_type || '').startsWith('minimax_h3')
}

type H3DurationOptions = {
  architecture?: string
  audio_only?: boolean
  model_type?: string
  minimax_h3_viggle?: boolean
  frames_maximum?: number | null
  sliding_window_defaults?: { window_max?: number } | null
} | null | undefined

export function h3MaximumFrames(options?: H3DurationOptions, extended?: unknown): number | null {
  return extended === true && supportsH3ExtendedDuration(options)
    ? H3_EXPERIMENTAL_MAX_FRAMES
    : options?.frames_maximum ?? null
}

export function h3WindowMaximumFrames(options?: H3DurationOptions, extended?: unknown): number | null {
  if (extended === true && supportsH3ExtendedDuration(options)) return H3_EXPERIMENTAL_MAX_FRAMES
  return options?.sliding_window_defaults?.window_max ?? options?.frames_maximum ?? null
}
