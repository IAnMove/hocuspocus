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

type AlignableDurationOptions = H3DurationOptions & {
  fps?: number | null
  frames_minimum?: number | null
  sliding_window?: boolean
  frame_alignment_modulus?: number
  frame_alignment_remainder?: number
  frame_alignment_mode?: string
}

/** Catalog `frames_maximum` is the 15s pass. A 30s experiment must align against 719. */
export function h3AlignmentOptions<T extends H3DurationOptions>(
  options: T | null | undefined,
  extended?: unknown,
): T | null | undefined {
  if (!options) return options
  return { ...options, frames_maximum: h3MaximumFrames(options, extended) }
}

/** Restore the opt-in 30s pass from a sidecar. Infer it when frames exceed the catalog 15s ceiling. */
export function restoredH3ExtendedDuration(
  params: { minimax_h3_extended_duration?: unknown; video_length?: unknown; model_type?: unknown },
  options?: H3DurationOptions,
): boolean {
  const modelType = String(options?.model_type || params.model_type || '')
  if (!supportsH3ExtendedDuration({
    architecture: options?.architecture || modelType,
    model_type: modelType,
    audio_only: options?.audio_only,
    minimax_h3_viggle: options?.minimax_h3_viggle,
  })) return false
  if (params.minimax_h3_extended_duration === true) return true
  const frames = Number(params.video_length)
  const catalogMax = options?.frames_maximum
  return Number.isFinite(frames) && catalogMax != null && frames > catalogMax
}

export function requestedVideoFrames(
  durationSeconds: number,
  options: AlignableDurationOptions | null | undefined,
  extended: unknown,
  alignFrameCount: (
    frames: number,
    options: AlignableDurationOptions | null | undefined,
  ) => number,
): number {
  const fps = options?.fps ?? 16
  const supportsSlidingWindows = options?.sliding_window === true
  const minimumFrames = options?.frames_minimum ?? 1
  const maximumFrames = h3MaximumFrames(options, extended)
  let requestedFrames = Math.max(minimumFrames, Math.round(durationSeconds * fps))
  requestedFrames = alignFrameCount(
    requestedFrames,
    h3AlignmentOptions(options, extended) ?? options,
  )
  if (!supportsSlidingWindows && maximumFrames != null) {
    return Math.min(maximumFrames, requestedFrames)
  }
  if (
    supportsSlidingWindows
    && maximumFrames != null
    && requestedFrames <= maximumFrames + 1
  ) {
    return Math.min(maximumFrames, requestedFrames)
  }
  return requestedFrames
}
