import { adoptAudio, cancelJob, fetchJobStatus, submitGeneration } from '../api/client'
import type { CustomCharacterVoice } from './characterVoice'

const AUDIO_FILE = /\.(wav|mp3|m4a|aac|flac|ogg)$/i
const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

export type SceneSpeechClip = {
  filename: string
  jobId: string
  model: string
  prompt: string
}

export type SceneSpeechDependencies = {
  submitGeneration: typeof submitGeneration
  fetchJobStatus: typeof fetchJobStatus
  cancelJob?: typeof cancelJob
  adoptAudio?: typeof adoptAudio
  now?: () => number
  wait?: (ms: number) => Promise<void>
}

type SceneSpeechOptions = {
    prompt: string
    model: string
    durationSeconds: number
    pollMs?: number
    timeoutMs?: number
    workspace?: string
    voice?: import('./characterVoice').CharacterVoice
    signal?: AbortSignal
  }

/** Generate one speech clip with the currently selected HocusPocus audio model. */
export async function generateSceneSpeechClip(
  options: SceneSpeechOptions,
  deps: SceneSpeechDependencies = { submitGeneration, fetchJobStatus, cancelJob, adoptAudio },
): Promise<SceneSpeechClip> {
  const submitted = await submitSpeech(options, deps)
  return awaitSpeechOutput(options, deps, submitted)
}

async function submitSpeech(options: SceneSpeechOptions, deps: SceneSpeechDependencies) {
  const prompt = options.prompt.trim()
  if (!prompt) throw new Error('Write a line of dialogue first.')
  const model = options.model.trim()
  if (!model) throw new Error('Select a speech model first.')
  options.signal?.throwIfAborted()
  const voices = options.voice ? await import('./characterVoice') : undefined
  const voice = voices?.parseCharacterVoice(options.voice)
  const reference = voice && voices?.isReferenceVoice(voice) ? voice : undefined
  if (voice && voice.model !== model) throw new Error('The selected voice belongs to a different speech model.')
  const referencePath = reference ? await adoptedReferencePath(reference, options, deps) : undefined
  const submitted = await deps.submitGeneration({
    model_type: model,
    generation_mode: 'audio',
    prompt,
    video_length: 0,
    image_mode: 0,
    multi_prompts_gen_type: 2,
    duration_seconds: Math.max(1, options.durationSeconds),
    _audio_sub_mode: 'speech',
    ...(options.workspace ? { workspace: options.workspace } : {}),
    ...(reference && voices ? voices.referenceVoiceParams(reference, referencePath)
      : voice ? { model_mode: voice.voiceId, alt_prompt: voice.instructions ?? '' } : {}),
  })
  return { prompt, model, jobId: submitted.job_id }
}

/** The cloned voice's recording, adopted from its source workspace. */
async function adoptedReferencePath(reference: CustomCharacterVoice, options: SceneSpeechOptions, deps: SceneSpeechDependencies) {
  const sourceWorkspace = new URLSearchParams(reference.referenceAudio.split('?')[1]).get('workspace') ?? options.workspace
  const adopted = await (deps.adoptAudio ?? adoptAudio)({ audio_path: reference.referenceAudio,
    ...(sourceWorkspace ? { workspace: sourceWorkspace } : {}) })
  if (!adopted.path) throw new Error('The reference recording is no longer available.')
  // Only the owned generation is cancellable; adopting a stored file never creates a job.
  options.signal?.throwIfAborted()
  return adopted.path
}

/** Wait for an audio job this caller submitted; aborting cancels that job only. */
export async function awaitSpeechOutput(options: SceneSpeechOptions, deps: SceneSpeechDependencies, submitted: Omit<SceneSpeechClip, 'filename'>): Promise<SceneSpeechClip> {
  const timeoutMs = options.timeoutMs ?? 15 * 60_000
  const pollMs = options.pollMs ?? 1000
  const now = deps.now ?? Date.now
  const wait = deps.wait ?? (ms => new Promise(resolve => { globalThis.setTimeout(resolve, ms) }))
  const deadline = now() + timeoutMs
  // Only cancel the job created by this call; never another editor's queue.
  let cancelRequested = false
  const cancelOwned = () => {
    if (!cancelRequested) { cancelRequested = true; void deps.cancelJob?.(submitted.jobId).catch(() => {}) }
  }
  options.signal?.addEventListener('abort', cancelOwned, { once: true })
  try {
  if (options.signal?.aborted) { cancelOwned(); options.signal.throwIfAborted() }
  let status = await deps.fetchJobStatus(submitted.jobId)
  while (!TERMINAL.has(status.status) && now() < deadline) {
    options.signal?.throwIfAborted()
    await wait(pollMs)
    status = await deps.fetchJobStatus(submitted.jobId)
  }
  if (status.status !== 'completed') {
    if (!TERMINAL.has(status.status)) cancelOwned()
    throw new Error(status.error || (now() >= deadline ? 'Audio generation timed out.' : 'Audio generation did not complete.'))
  }
  options.signal?.throwIfAborted()
  const filename = status.output_files.find(file => AUDIO_FILE.test(file))
  if (!filename) throw new Error('The audio model completed without an output file.')
  return { filename, ...submitted }
  } finally { options.signal?.removeEventListener('abort', cancelOwned) }
}
