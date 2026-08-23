import * as api from '../api/client'
import { generateImageAsset } from './imageGeneration'
import type { SceneRecipe, SceneRecipeAsset } from './sceneRecipe'
import { aspectRatioForScene, h3FramesForDuration, h3ResolutionForScene, recipeAssetDuration } from './sceneRecipe'

const wait = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

async function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer = 0
  const timeout = new Promise<T>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error(`${label} timed out after ${Math.round(ms / 1000)}s. Lab may have crashed — restart it and retry.`)), ms)
  })
  try {
    return await Promise.race([promise, timeout])
  } finally {
    window.clearTimeout(timer)
  }
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new Error('Recipe cancelled.')
}

export async function waitForGpuIdle(onStatus?: (message: string) => void, signal?: AbortSignal): Promise<void> {
  const started = Date.now()
  for (;;) {
    throwIfAborted(signal)
    let jobs: Awaited<ReturnType<typeof api.fetchActiveJobs>>['jobs'] = []
    let hunyuanBusy = false
    try {
      const [queue, hunyuan] = await withTimeout(Promise.all([
        api.fetchActiveJobs(),
        api.fetchHunyuan3DCapabilities().catch(() => ({ active_jobs: 0 })),
      ]), 8000, 'Checking GPU jobs')
      jobs = queue.jobs
      hunyuanBusy = hunyuan.active_jobs > 0
    } catch (error) {
      throw new Error(error instanceof Error ? error.message : 'Lab is not responding.')
    }
    const busy = jobs.filter(job => ['queued', 'waiting_resource', 'running', 'cancelling'].includes(job.status))
    if (!busy.length && !hunyuanBusy) return
    if (Date.now() - started > 20 * 60 * 1000) {
      throw new Error('Timed out waiting for the GPU to become idle.')
    }
    const elapsed = Math.round((Date.now() - started) / 1000)
    onStatus?.(
      hunyuanBusy
        ? `Waiting for Hunyuan3D (${elapsed}s)…`
        : `Waiting for ${busy.length} GPU job${busy.length === 1 ? '' : 's'} (${elapsed}s)…`,
    )
    await wait(2000)
  }
}

async function pollUntil<T extends { status: string; error?: string | null; message?: string; phase?: string }>(
  label: string,
  load: () => Promise<T>,
  isDone: (value: T) => string | null,
  onStatus?: (message: string) => void,
  signal?: AbortSignal,
  timeoutMs = 15 * 60 * 1000,
): Promise<T> {
  const started = Date.now()
  for (;;) {
    throwIfAborted(signal)
    const value = await withTimeout(load(), 12000, label)
    onStatus?.(`${label}: ${value.message || value.phase || value.status} (${Math.round((Date.now() - started) / 1000)}s)`)
    if (value.status === 'failed' || value.status === 'cancelled') {
      throw new Error(value.error || value.message || `${label} ${value.status}`)
    }
    const done = isDone(value)
    if (done) return value
    if (Date.now() - started > timeoutMs) throw new Error(`${label} timed out.`)
    await wait(2000)
  }
}

async function resolveImage(asset: SceneRecipeAsset, recipe: SceneRecipe, onStatus?: (message: string) => void, signal?: AbortSignal): Promise<string> {
  if (asset.source) return asset.source
  throwIfAborted(signal)
  onStatus?.(`Generating image plate “${asset.id}”…`)
  const width = recipe.scene.width || 1280
  const height = recipe.scene.height || 720
  const result = await withTimeout(generateImageAsset('minimax', asset.prompt || asset.id, asset.model, undefined, '', {
    aspectRatio: aspectRatioForScene(width, height),
  }), 8 * 60 * 1000, `Image “${asset.id}”`)
  return result.source || result.name
}

async function resolveVideo(asset: SceneRecipeAsset, recipe: SceneRecipe, onStatus?: (message: string) => void, signal?: AbortSignal): Promise<string> {
  if (asset.source) return asset.source
  await waitForGpuIdle(onStatus, signal)
  onStatus?.(`Generating H3 plate “${asset.id}”…`)
  const started = await api.submitGeneration({
    prompt: asset.prompt,
    model_type: asset.model || 'minimax_h3_legacy',
    resolution: h3ResolutionForScene(recipe.scene.width || 1280, recipe.scene.height || 720),
    video_length: h3FramesForDuration(recipeAssetDuration(recipe, asset.id)),
    generation_mode: 'video',
    spoken_language: 'Español de España',
  })
  const status = await pollUntil(
    `H3 “${asset.id}”`,
    () => api.fetchJobStatus(started.job_id),
    job => job.status === 'completed' ? (job.output_files?.[0] || 'missing') : null,
    onStatus,
    signal,
  )
  const file = status.output_files?.[0]
  if (!file) throw new Error(`H3 “${asset.id}” completed without a file.`)
  return file
}

async function resolveModel(asset: SceneRecipeAsset, workspace: string, onStatus?: (message: string) => void, signal?: AbortSignal): Promise<string> {
  let glb = asset.source
  if (!glb) {
    await waitForGpuIdle(onStatus, signal)
    onStatus?.(`Generating 3D mesh “${asset.id}”…`)
    const job = await api.startHunyuan3DJob({
      operation: 'generate',
      preset: asset.preset || 'balanced',
      model_id: asset.model_id,
      prompt: asset.prompt,
      workspace,
      output_format: 'glb',
      cpu_offload: true,
      flashvdm: true,
      remove_background: true,
    })
    const finished = await pollUntil(
      `Hunyuan “${asset.id}”`,
      () => api.fetchHunyuan3DJob(job.job_id),
      value => value.status === 'completed' ? (value.filename || 'missing') : null,
      onStatus,
      signal,
      20 * 60 * 1000,
    )
    glb = finished.filename || undefined
    if (!glb) throw new Error('Hunyuan3D completed without a GLB filename.')
  }
  if (asset.rig_profile) {
    await waitForGpuIdle(onStatus, signal)
    onStatus?.(`Rigging “${asset.id}” as ${asset.rig_profile}…`)
    const rig = await api.startRigJob({
      source: glb,
      engine: 'procedural',
      rig_profile: asset.rig_profile,
      animations: asset.animations?.length ? asset.animations : undefined,
    })
    const rigged = await pollUntil(
      `Rig “${asset.id}”`,
      () => api.fetchRigJob(rig.job_id),
      value => value.status === 'completed' ? (value.filename || 'missing') : null,
      onStatus,
      signal,
    )
    if (!rigged.filename) throw new Error('Rig completed without a GLB filename.')
    glb = rigged.filename
  }
  return glb
}

export async function resolveRecipeAssets(
  recipe: SceneRecipe,
  options: {
    workspace: string
    onStatus?: (message: string) => void
    signal?: AbortSignal
    generateMissing?: boolean
  },
): Promise<Record<string, string>> {
  const resolved: Record<string, string> = {}
  const byIdentity = new Map<string, string>()
  const generateMissing = options.generateMissing !== false

  for (const asset of recipe.assets) {
    throwIfAborted(options.signal)
    if (asset.identity && byIdentity.has(asset.identity)) {
      resolved[asset.id] = byIdentity.get(asset.identity) as string
      continue
    }
    if (!asset.source && !generateMissing) {
      throw new Error(`Asset “${asset.id}” has no source. Load it in Manual mode or generate it in Auto.`)
    }
    const value = asset.kind === 'image'
      ? await resolveImage(asset, recipe, options.onStatus, options.signal)
      : asset.kind === 'video'
        ? await resolveVideo(asset, recipe, options.onStatus, options.signal)
        : await resolveModel(asset, options.workspace, options.onStatus, options.signal)
    resolved[asset.id] = value
    if (asset.identity) byIdentity.set(asset.identity, value)
  }
  return resolved
}
