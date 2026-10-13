import type { SeriesProject, SeriesShot, SeriesVideoResolution } from './types'

/** The H3 sizes a Series offers, as series_render.SERIES_RESOLUTIONS lists them. */
export const SERIES_VIDEO_RESOLUTIONS: readonly SeriesVideoResolution[] = ['480p', '540p', '720p', '768p']
export const DEFAULT_SERIES_VIDEO_RESOLUTION: SeriesVideoResolution = '480p'
/** Each size's label in the seriesLab catalog (its canvas in both orientations). */
export const SERIES_VIDEO_RESOLUTION_LABELS = {
  '480p': 'providers.res480', '540p': 'providers.res540', '720p': 'providers.res720', '768p': 'providers.res768',
} as const satisfies Record<SeriesVideoResolution, string>

export function seriesVideoResolution(value: unknown): SeriesVideoResolution | undefined {
  return SERIES_VIDEO_RESOLUTIONS.find(item => item === value)
}

/** A shot whose take is an H3 clip it can size: a Series Lab render, or a video shot the script asks H3 for. */
export function shotHasVideoSize(shot: SeriesShot): boolean {
  const method = shot.productionMethod || 'generated_video'
  return method === 'generated_video' || (method === 'imported_video' && Boolean(shot.video))
}

/** The size a shot gets without its own `resolution`: a Series Lab render follows the provider settings, a script
 * video shot the series' `videoShotResolution`; both are 480p when nothing is set. */
export function inheritedShotResolution(series: SeriesProject, shot: SeriesShot): SeriesVideoResolution {
  const value = (shot.productionMethod || 'generated_video') === 'generated_video'
    ? series.provider.videoSettings.resolution : series.videoShotResolution
  return seriesVideoResolution(value) || DEFAULT_SERIES_VIDEO_RESOLUTION
}
