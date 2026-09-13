import type { Scene, SceneLayer } from '../../types'
import { createDefaultScene3DDocument } from '../scene3d/document'
import type { SeriesEpisode, SeriesProject, SeriesShot, SeriesAsset } from './types'
import { seriesAssetUrl } from './referenceImages'
import { allowedSeriesMethods, seriesShotMethod } from './productionMethods'
import { seriesShotReferences } from './shotReferences'

export function buildSeriesShotScene(workspace: string, series: SeriesProject, episode: SeriesEpisode, shot: SeriesShot) {
  const method = seriesShotMethod(series, shot)
  if (!allowedSeriesMethods(series).includes(method) || !['animation_2d', 'animation_3d'].includes(method)) throw new Error('This shot does not permit animation preparation')
  const { people, background, location, ready, locationState } = seriesShotReferences(series, episode, shot)
  if (!ready) {
    const missing = [...(locationState !== 'ready' ? [`Location: ${location?.name || shot.locationId || 'not assigned'}`] : []),
      ...people.filter(person => person.state !== 'ready').map(person => `Character: ${person.name}`)]
    throw new Error(`Prepare approved reference images for ${missing.join(', ')} and update this episode's references before opening the editor.`)
  }
  const title = `${series.title} · ${episode.title} · ${shot.order}`
  const duration = shot.durationSeconds
  const portrait = series.provider.videoSettings.orientation === 'portrait'
  const width = portrait ? 720 : 1280, height = portrait ? 1280 : 720
  if (method === 'animation_2d') {
    const imageLayer = (id: string, name: string, asset: SeriesAsset, index: number, back = false): SceneLayer => {
      const transform = { x: back ? 50 : (index + 1) * 100 / (people.length + 1), y: back ? 50 : 60, scale: back ? 1 : .55, opacity: 1 }
      return { id, name, type: 'image', source: seriesAssetUrl(asset), visible: true, z: back ? 0 : index + 1,
        fill: back, transform, animation: { start: transform, end: transform, duration, curve: 'linear' } }
    }
    const document: Scene = { version: 1, name: title, width, height, duration, fps: 30, generationPolicy: 'provided_only',
      layers: [...(background ? [imageLayer(location!.id, location!.name, background, 0, true)] : []),
        ...people.map((person, index) => imageLayer(person.id, person.name, person.asset!, index))],
      dialogueBeats: shot.dialogueBeats.map((line, index) => ({ id: line.id, text: line.text, start: index * duration / shot.dialogueBeats.length, end: (index + 1) * duration / shot.dialogueBeats.length, mouthLayerIds: [], confidence: 'known-text' })),
      narrative: { templateId: 'series-shot', controls: { seriesId: series.id, episodeId: episode.id, shotId: shot.id }, visualIntent: shot.action || shot.prompt },
    }
    return { dimension: '2d' as const, document }
  }
  const document = createDefaultScene3DDocument()
  Object.assign(document, { width, height, duration,
    production: { kind: 'episode', title, sourceId: `${series.id}/${episode.id}/${shot.id}`, workspace } })
  document.slots = people.map((person, index) => ({ id: person.id, slot: index === 0 ? 'subject_1' : 'subject_2',
    position: [(index - (people.length - 1) / 2) * 1.6, 0, 0], rotationY: 0, scale: 1,
    sourceUrl: seriesAssetUrl(person.asset!), media: 'image', clip: null,
    sourceRef: { workspaceId: workspace, filename: person.asset!.uri, url: seriesAssetUrl(person.asset!), assetId: person.asset!.id },
    character: { id: person.id, name: person.name },
  }))
  if (background) document.slots.push({ id: location!.id, slot: 'background', position: [0, 0, -2], rotationY: 0, scale: 4,
    sourceUrl: seriesAssetUrl(background), media: 'image', clip: null })
  return { dimension: '3d' as const, document }
}
