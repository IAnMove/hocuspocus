import type { SeriesEpisode, SeriesProject } from './types'
import { seriesEntityImage, seriesShotReferences } from './shotReferences'
import { generateSeriesReferenceImage, seriesReferencePrompt, type SeriesReferenceImport } from './referenceImages'

export function episodeReferenceTargets(series: SeriesProject, episode: SeriesEpisode) {
  const characterIds = new Set(episode.shots.flatMap(shot => [...shot.visibleCharacterIds, ...shot.speakingCharacterIds]))
  const locationIds = new Set(episode.shots.map(shot => shot.locationId))
  return [
    ...series.characters.filter(item => characterIds.has(item.id)).map(item => ({ kind: 'character' as const, ...item })),
    ...series.locations.filter(item => locationIds.has(item.id)).map(item => ({ kind: 'location' as const, ...item })),
  ].map(entity => ({ kind: entity.kind, id: entity.id, name: entity.name, asset: seriesEntityImage(entity, series.assets) }))
}

export function episodeNeedsReferences(series: SeriesProject, episode: SeriesEpisode) {
  return episode.shots.some(shot => !seriesShotReferences(series, episode, shot).ready)
}

/** Read current edits between jobs; a retry skips every image already imported. */
export async function generateMissingEpisodeReferences(options: {
  workspace: string; episodeId: string
  current: () => Promise<SeriesProject>
  accept: (result: SeriesReferenceImport) => void
  progress: (name: string, current: number, total: number) => void
  generate?: typeof generateSeriesReferenceImage
}) {
  const initial = await options.current()
  const targets = episodeReferenceTargets(initial, initial.episodesById[options.episodeId]).filter(item => !item.asset)
  for (const [index, target] of targets.entries()) {
    const series = await options.current()
    const pending = episodeReferenceTargets(series, series.episodesById[options.episodeId]).find(item => item.id === target.id && !item.asset)
    if (!pending) continue
    options.progress(target.name, index + 1, targets.length)
    const result = await (options.generate ?? generateSeriesReferenceImage)(options.workspace, series, target, {
      prompt: seriesReferencePrompt(series, target), beforeImport: options.current,
    })
    options.accept(result)
  }
}
