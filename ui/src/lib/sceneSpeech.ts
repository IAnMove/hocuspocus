import { fetchJobStatus, submitGeneration } from '../api/client'

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
  now?: () => number
  wait?: (ms: number) => Promise<void>
}

/** Generate one speech clip with the currently selected HocusPocus audio model. */
export async function generateSceneSpeechClip(
  options: {
    prompt: string
    model: string
    durationSeconds: number
    pollMs?: number
    timeoutMs?: number
  },
  deps: SceneSpeechDependencies = { submitGeneration, fetchJobStatus },
): Promise<SceneSpeechClip> {
  const prompt = options.prompt.trim()
  if (!prompt) throw new Error('Write a line of dialogue first.')
  const model = options.model.trim()
  if (!model) throw new Error('Select a speech model first.')
  const submitted = await deps.submitGeneration({
    model_type: model,
    generation_mode: 'audio',
    prompt,
    video_length: 0,
    image_mode: 0,
    multi_prompts_gen_type: 2,
    duration_seconds: Math.max(1, options.durationSeconds),
    _audio_sub_mode: 'speech',
  })
  const timeoutMs = options.timeoutMs ?? 15 * 60_000
  const pollMs = options.pollMs ?? 1000
  const now = deps.now ?? Date.now
  const wait = deps.wait ?? (ms => new Promise(resolve => { globalThis.setTimeout(resolve, ms) }))
  const deadline = now() + timeoutMs
  let status = await deps.fetchJobStatus(submitted.job_id)
  while (!TERMINAL.has(status.status) && now() < deadline) {
    await wait(pollMs)
    status = await deps.fetchJobStatus(submitted.job_id)
  }
  if (status.status !== 'completed') {
    throw new Error(status.error || (now() >= deadline ? 'Audio generation timed out.' : 'Audio generation did not complete.'))
  }
  const filename = status.output_files.find(file => AUDIO_FILE.test(file)) ?? status.output_files[0]
  if (!filename) throw new Error('The audio model completed without an output file.')
  return { filename, jobId: submitted.job_id, model, prompt }
}
