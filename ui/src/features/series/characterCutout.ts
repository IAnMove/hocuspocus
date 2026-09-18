import * as api from '../../api/client'
import { seriesAssetUrl } from './referenceImages'
import type { SeriesAsset, SeriesProject } from './types'

export function characterCutout(series: SeriesProject, source: SeriesAsset, sourceKey?: string) {
  return Object.values(series.assets).find(asset => asset.metadata?.backgroundRemoved === true
    && asset.metadata?.sourceAssetId === source.id && asset.metadata?.sourceKey === sourceKey && asset.kind === 'image')
}

const flights = new Map<string, Promise<{ asset: SeriesAsset; series: SeriesProject }>>()
export function prepareCharacterCutout(workspace: string, series: SeriesProject, source: SeriesAsset,
  variant?: { sourceKey: string; sourceUrl: string }) {
  const key = `${workspace}/${series.id}/${source.id}${variant ? `/${variant.sourceKey}` : ''}`
  const existing = characterCutout(series, source, variant?.sourceKey)
  if (existing) return Promise.resolve({ asset: existing, series })
  const running = flights.get(key)
  if (running) return running
  const request = removeCutout(workspace, series, source, key, variant).finally(() => flights.delete(key))
  flights.set(key, request)
  return request
}

async function removeCutout(workspace: string, series: SeriesProject, source: SeriesAsset, key: string,
  variant?: { sourceKey: string; sourceUrl: string }) {
  const storageKey = `hocuspocus:series-cutout:${key}`
  let jobId = localStorage.getItem(storageKey)
  if (!jobId) {
    const response = await fetch(variant?.sourceUrl || seriesAssetUrl(source))
    if (!response.ok) throw new Error('Character image is unavailable')
    const upload = await api.uploadImage(new File([await response.blob()], `${source.id}.png`, { type: 'image/png' }))
    const job = await api.submitToolRemoveBackground({ source: upload.path, source_workspace: '__uploads__', workspace,
      provenance: { actor: 'user', capability: 'remove_background', workspace_id: workspace } })
    jobId = job.job_id
    localStorage.setItem(storageKey, jobId)
  }
  const deadline = Date.now() + 15 * 60_000
  let job = await api.fetchJobStatus(jobId)
  while (!['completed', 'failed', 'cancelled'].includes(job.status)) {
    if (Date.now() > deadline) throw new Error('Background removal is still running. Retry to recover its result.')
    await new Promise(resolve => setTimeout(resolve, 1000))
    job = await api.fetchJobStatus(jobId)
  }
  if (job.status !== 'completed') {
    localStorage.removeItem(storageKey)
    throw new Error(job.error || 'Background removal failed')
  }
  const filename = job.output_files.find(name => /\.png$/i.test(name))
  if (!filename) throw new Error('Background removal returned no PNG')
  const response = await fetch(api.getFileUrl(filename, workspace))
  if (!response.ok) throw new Error('The transparent character is unavailable')
  const upload = await api.uploadImage(new File([await response.blob()], `${source.id}-cutout.png`, { type: 'image/png' }))
  // A derived production asset preserves the approved identity and original image.
  const result = await api.importSeriesAsset(workspace, series.id, { uploadPath: upload.path,
    name: `${source.id}-cutout.png`, ownerType: 'series', ownerId: series.id, kind: 'image',
    metadata: { backgroundRemoved: true, sourceAssetId: source.id, characterId: source.ownerId, jobId,
      ...(variant ? { sourceKey: variant.sourceKey } : {}) } })
  localStorage.removeItem(storageKey)
  return result
}
