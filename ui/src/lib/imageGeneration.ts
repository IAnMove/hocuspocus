import * as api from '../api/client'
import { getModelMode, useStore } from '../stores/useStore'
import { comicId } from '../features/comics/model'
import type { ComicAsset } from '../features/comics/types'

export type LocalImageOptions = {
  panelId?: string
  existingJobId?: string
  onJobSubmitted?: (jobId: string) => void
  onPollRetry?: (attempt: number, error: string) => void
  onProviderRetry?: (attempt: number, error: string) => void
  strictReference?: boolean
  /** Identity references may influence a new composition; edit references are the source canvas itself. */
  referenceMode?: 'identity' | 'edit'
  /** Freeze an explicit local output canvas instead of inheriting another image model's saved value. */
  resolution?: string
  aspectRatio?: '1:1' | '16:9' | '4:3' | '3:2' | '2:3' | '3:4' | '9:16' | '21:9'
}

const wait = (milliseconds: number) =>
  new Promise(resolve => window.setTimeout(resolve, milliseconds))
const fileName = (path: string) => path.split(/[\\/]/).pop() || path
const compactProviderPrompt = (value: string, limit = 1450): string => {
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  const prefix = normalized.slice(0, limit)
  const lastBoundary = Math.max(prefix.lastIndexOf('. '), prefix.lastIndexOf('; '), prefix.lastIndexOf(' '))
  return `${prefix.slice(0, lastBoundary > limit * 0.65 ? lastBoundary : limit).replace(/[\s,;:-]+$/, '')}.`
}

function localAsset(
  name: string,
  prompt: string,
  model: string,
  jobId?: string,
): ComicAsset {
  return {
    id: comicId('asset'),
    name,
    kind: 'local',
    source: `/api/v1/file/${encodeURIComponent(name)}`,
    prompt,
    provider: 'maestro',
    model,
    createdAt: new Date().toISOString(),
    metadata: jobId ? { jobId } : undefined,
  }
}

export async function findCompletedLocalImage(
  prompt: string,
  model: string,
  excludedNames: Set<string>,
): Promise<ComicAsset | null> {
  const { outputs } = await api.fetchOutputs(50, 0)
  const candidates = outputs.filter(output =>
    output.type === 'image' && !excludedNames.has(output.name))
  for (const output of candidates) {
    try {
      const metadata = await api.fetchOutputMetadata(output.name)
      if (
        metadata.params?.prompt === prompt &&
        metadata.params?.model_type === model
      ) {
        return localAsset(output.name, prompt, model, metadata.job_id)
      }
    } catch {
      // One unreadable gallery sidecar must not prevent recovery from the rest.
    }
  }
  return null
}

async function runLocalImage(
  prompt: string,
  modelType?: string,
  reference?: string,
  negativePrompt = '',
  options: LocalImageOptions = {},
): Promise<ComicAsset> {
  const maestro = useStore.getState()
  const selected = modelType || maestro.selectedModelPerMode.image || maestro.params.model_type
  if (!selected) throw new Error('Select an image model in Maestro first')
  const model = maestro.models.find(item => item.model_type === selected)
  if (model && getModelMode(model.model_type, model.family) !== 'image') {
    throw new Error(`"${selected}" is a video model. Select a Maestro image model or MiniMax`)
  }
  const imageParams = maestro.savedParamsPerMode.image || {}
  const referenceParams: Record<string, unknown> = {}
  if (reference) {
    const supportsReferences = Boolean(
      model?.supports_ref_images
      || (selected === maestro.params.model_type && maestro.modelOptions?.image_ref_choices),
    )
    if (!supportsReferences) {
      if (options.strictReference) {
        throw new Error(
          options.referenceMode === 'edit'
            ? 'This Maestro model cannot edit a source image. Choose Qwen Image Edit or another reference-capable image editor.'
            : 'This Maestro model does not support identity references. Choose a reference-capable local model or MiniMax Image.',
        )
      }
    } else {
      const response = await fetch(reference)
      if (!response.ok) throw new Error('The selected identity reference is no longer available')
      const blob = await response.blob()
      const uploaded = await api.uploadImage(new File(
        [blob],
        fileName(decodeURIComponent(reference)) || 'story-reference.png',
        { type: blob.type || 'image/png' },
      ))
      const currentType = typeof imageParams.video_prompt_type === 'string'
        ? imageParams.video_prompt_type : ''
      referenceParams.image_refs = [uploaded.path]
      // Qwen's KI contract makes the first conditional image the main
      // subject/landscape. Plain I treats it as a supplemental person/object
      // reference and is exactly the wrong semantic for scene style transfer.
      referenceParams.video_prompt_type = options.referenceMode === 'edit'
        ? 'KI'
        : currentType.includes('I') ? currentType : `${currentType}I`
      referenceParams.remove_background_images_ref = 0
      if (options.referenceMode === 'edit' && selected.startsWith('qwen_image_edit')) {
        // Do not inherit inpainting/denoise state from whatever image model
        // happened to be selected in Studio. This is a full-canvas Qwen edit.
        referenceParams.model_mode = 0
        referenceParams.denoising_strength = 1
        referenceParams.masking_strength = 1
        referenceParams.sample_solver = 'default'
      }
      if (options.referenceMode === 'edit' && selected === 'flux2_klein_9b') {
        // Flux 2 Klein is a distilled four-step image editor. Freeze its own
        // recipe so this dedicated edit cannot inherit Qwen/Studio settings.
        referenceParams.num_inference_steps = 4
        referenceParams.guidance_scale = 1
        referenceParams.embedded_guidance_scale = 1
        referenceParams.flow_shift = 5
        referenceParams.model_mode = 0
        referenceParams.denoising_strength = 1
        referenceParams.masking_strength = 0.25
        referenceParams.image_prompt_type = ''
      }
    }
  }
  const jobId = options.existingJobId || (await api.submitGeneration({
    ...maestro.params,
    ...imageParams,
    ...referenceParams,
    ...(options.resolution ? { resolution: options.resolution } : {}),
    prompt,
    negative_prompt: negativePrompt,
    model_type: selected,
    image_mode: 1,
    generation_mode: 'image',
    comic_panel: true,
    comic_panel_id: options.panelId,
    provider: 'maestro',
    repeat_generation: 1,
    workspace: maestro.activeWorkspace,
  })).job_id
  if (!options.existingJobId) options.onJobSubmitted?.(jobId)
  let consecutivePollFailures = 0
  for (;;) {
    await wait(consecutivePollFailures ? Math.min(10000, 1500 * consecutivePollFailures) : 1500)
    let status: api.ApiJobStatus
    try {
      status = await api.fetchJobStatus(jobId)
      consecutivePollFailures = 0
    } catch (error) {
      consecutivePollFailures += 1
      options.onPollRetry?.(consecutivePollFailures, (error as Error).message)
      if (consecutivePollFailures >= 20) {
        throw new Error(`Could not reconnect to Maestro job ${jobId}; the job ID was preserved`)
      }
      continue
    }
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error || status.message || 'Local image generation failed')
    }
    if (status.status === 'completed') {
      const path = status.output_files.find(value => /\.(png|jpe?g|webp)$/i.test(value))
      if (!path) throw new Error('Image job completed without an image')
      const name = fileName(path)
      maestro.loadOutputs()
      return localAsset(name, prompt, selected, jobId)
    }
  }
}

export async function generateImageAsset(
  provider: 'maestro' | 'minimax',
  prompt: string,
  model?: string,
  reference?: string,
  negativePrompt = '',
  options?: LocalImageOptions,
): Promise<ComicAsset> {
  if (provider === 'minimax') {
    const providerPrompt = compactProviderPrompt(prompt)
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const result = await api.generateComicWithMiniMax({
          prompt: providerPrompt,
          aspect_ratio: options?.aspectRatio || '1:1',
          subject_reference: reference,
        })
        return result.asset
      } catch (error) {
        const message = (error as Error).message
        const permanent = /invalid param|prompt length|unauthorized|forbidden|insufficient|quota/i.test(message)
        const transient = /\bHTTP 50[234]\b|bad gateway|temporar|timed? ?out|connection/i.test(message)
        if (attempt >= 3 || permanent || !transient) throw error
        options?.onProviderRetry?.(attempt, message)
        await wait(attempt * 2500)
      }
    }
  }
  return runLocalImage(prompt, model, reference, negativePrompt, options)
}
