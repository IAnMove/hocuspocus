import * as api from '../../api/client'
import { generateImageAsset } from '../../lib/imageGeneration'
import { seriesProviderFieldsFromProfile } from '../../lib/productionProfile'
import { useStore } from '../../stores/useStore'
import type { SeriesAsset, SeriesProject } from './types'
import { EMPTY_LOCATION_NEGATIVE, EMPTY_LOCATION_RULE, prepareLocationReferencePrompt } from './locationReferencePrompt'

export type SeriesReferenceTarget = { kind: 'character' | 'location'; id: string }
export type SeriesReferenceImport = { asset: SeriesAsset; series: SeriesProject }
export type PendingSeriesImage = { jobId: string; prompt: string; provider: string; model: string; reference?: string }

export function seriesAssetUrl(asset: SeriesAsset): string {
  return /^https?:\/\//i.test(asset.uri) ? asset.uri : api.getFileUrl(asset.uri.replace(/^outputs\//, ''), asset.workspaceId)
}

export function seriesReferencePrompt(series: SeriesProject, target: SeriesReferenceTarget): string {
  const entity = target.kind === 'character'
    ? series.characters.find(item => item.id === target.id)
    : series.locations.find(item => item.id === target.id)
  if (!entity) throw new Error('Series reference subject no longer exists')
  if (!('appearance' in entity)) return [EMPTY_LOCATION_RULE, `Location: ${entity.name}.`, entity.description,
    'One establishing view of this location. Retain only its physical environment and remove any described occupants.'].join(' ')
  return [series.visualStyle, series.characterVisualStyle, entity.appearance, entity.identityLock,
    `Character: ${entity.name}. ${entity.role}.`,
    'One full-body character design, clearly visible face and clothing, neutral background, consistent identity.',
    'Single concept image, no contact sheet, no grid, no text, no labels.'].filter(Boolean).join(' ')
}

export function prepareSeriesLocationPrompt(workspace: string, series: SeriesProject, locationId: string, draft: string) {
  const location = series.locations.find(item => item.id === locationId)
  if (!location) throw new Error('Series location no longer exists')
  const provider = series.provider.useGlobalProfile
    ? seriesProviderFieldsFromProfile(useStore.getState().productionProfile) : series.provider
  return prepareLocationReferencePrompt(workspace, series, location, draft, {
    writingProvider: provider.writingProvider, writingModel: provider.writingModel, writingBaseUrl: provider.writingBaseUrl,
  })
}

export function seriesImageJobKey(workspace: string, seriesId: string, target: SeriesReferenceTarget): string {
  return `hocuspocus:series-reference:${JSON.stringify([workspace, seriesId, target.kind, target.id])}`
}

export function pendingSeriesImage(key: string): PendingSeriesImage | undefined {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    if (value && ['jobId', 'prompt', 'provider', 'model'].every(field => typeof value[field] === 'string')) return value
  } catch { /* The queue remains available when browser storage is unavailable. */ }
}

const inFlight = new Map<string, Promise<SeriesReferenceImport>>()
type ReferenceImageOptions = { prompt: string; beforeImport: () => Promise<unknown>; onSubmitted?: () => void
  onPreparingPrompt?: () => void; onPromptPrepared?: (prompt: string) => void }
export function generateSeriesReferenceImage(workspace: string, series: SeriesProject, target: SeriesReferenceTarget,
  options: ReferenceImageOptions): Promise<SeriesReferenceImport> {
  const key = seriesImageJobKey(workspace, series.id, target)
  const existing = inFlight.get(key)
  if (existing) return existing
  const request = runSeriesReferenceImage(workspace, series, target, options).finally(() => inFlight.delete(key))
  inFlight.set(key, request)
  return request
}

async function runSeriesReferenceImage(workspace: string, series: SeriesProject, target: SeriesReferenceTarget,
  options: ReferenceImageOptions): Promise<SeriesReferenceImport> {
  const key = seriesImageJobKey(workspace, series.id, target)
  const pending = pendingSeriesImage(key)
  const provider = series.provider.useGlobalProfile
    ? seriesProviderFieldsFromProfile(useStore.getState().productionProfile) : series.provider
  const entity = target.kind === 'character' ? series.characters.find(item => item.id === target.id) : undefined
  const primary = entity?.primaryReferenceAssetId ? series.assets[entity.primaryReferenceAssetId] : undefined
  let prompt = options.prompt
  if (!pending && target.kind === 'location') {
    options.onPreparingPrompt?.()
    prompt = await prepareSeriesLocationPrompt(workspace, series, target.id, prompt)
    options.onPromptPrepared?.(prompt)
  }
  const request = pending || { jobId: '', prompt, provider: provider.imageProvider,
    model: provider.imageModel, reference: primary ? seriesAssetUrl(primary) : undefined }
  const generated = await generateImageAsset(request.provider === 'minimax' ? 'minimax' : 'maestro',
    request.prompt, request.model, request.reference, target.kind === 'location' ? EMPTY_LOCATION_NEGATIVE : '', {
      workspace, panelId: `series-${series.id}-${target.id}`, existingJobId: request.jobId || undefined,
      aspectRatio: target.kind === 'character' ? '2:3' : '16:9', strictReference: Boolean(request.reference),
      cleanModelDefaults: target.kind === 'location',
      onJobSubmitted: jobId => {
        try { localStorage.setItem(key, JSON.stringify({ ...request, jobId })) } catch { /* Optional reconnect aid. */ }
        options.onSubmitted?.()
      },
    }).catch(async reason => {
      const interrupted = pendingSeriesImage(key)
      if (interrupted) {
        try {
          const job = interrupted.provider === 'minimax' ? await api.fetchMiniMaxImageJob(interrupted.jobId) : await api.fetchJobStatus(interrupted.jobId)
          if (['failed', 'cancelled', 'error'].includes(job.status)) localStorage.removeItem(key)
        } catch { /* Preserve the job ID when its status cannot be verified. */ }
      }
      throw reason
    })
  await options.beforeImport()
  const response = await fetch(generated.source)
  if (!response.ok) throw new Error('Generated reference image is unavailable')
  const blob = await response.blob()
  const upload = await api.uploadImage(new File([blob], generated.name || `${target.id}.png`, { type: blob.type || 'image/png' }))
  const result = await api.importSeriesAsset(workspace, series.id, {
    uploadPath: upload.path, name: generated.name, ownerType: target.kind, ownerId: target.id, kind: target.kind,
    referenceRole: target.kind === 'character' ? 'primary_portrait' : 'location_reference',
    metadata: { ...generated.metadata, prompt: request.prompt, provider: request.provider, model: generated.model, createdAt: generated.createdAt },
  })
  try { localStorage.removeItem(key) } catch { /* Optional reconnect aid. */ }
  return result
}

/** Import only the reference change into current edits; a delayed image must not replace authored fields. */
export function mergeSeriesReferenceImport(current: SeriesProject, result: SeriesReferenceImport): SeriesProject {
  const { asset } = result
  if (asset.ownerType === 'attempt') {
    const episodes = { ...current.episodesById }
    for (const remote of Object.values(result.series.episodesById)) {
      const local = episodes[remote.id]
      if (!local) continue
      episodes[local.id] = { ...local, shots: local.shots.map(shot => {
        const attempt = remote.shots.find(item => item.id === shot.id)?.attempts.find(item => item.id === asset.ownerId)
        return attempt && !shot.attempts.some(item => item.id === attempt.id) ? { ...shot, attempts: [...shot.attempts, attempt] } : shot
      }) }
    }
    return { ...current, revision: Math.max(current.revision, result.series.revision), assets: { ...current.assets, [asset.id]: asset }, episodesById: episodes }
  }
  const collection = asset.ownerType === 'character' ? 'characters' : asset.ownerType === 'location' ? 'locations' : 'props'
  return { ...current, revision: Math.max(current.revision, result.series.revision),
    assets: { ...current.assets, [asset.id]: asset },
    [collection]: current[collection].map(entity => entity.id !== asset.ownerId ? entity : {
      ...entity, referenceAssetIds: [...new Set([...entity.referenceAssetIds, asset.id])], approval: 'draft',
      ...(collection === 'characters' && !('primaryReferenceAssetId' in entity && entity.primaryReferenceAssetId)
        ? { primaryReferenceAssetId: asset.id } : {}),
    }),
    canon: { ...current.canon, approval: 'draft', approvedAt: '' },
  }
}
