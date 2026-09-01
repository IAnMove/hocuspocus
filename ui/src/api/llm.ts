import type { H3WindowPlan } from '../types'
import { BASE } from './http'

export async function planH3Windows(params: {
  prompt: string
  model_type: string
  resolution: string
  total_frames: number
  window_frames: number
  overlap_frames: number
  discard_frames: number
  sliding_window_memory_override?: boolean
  has_start_image?: boolean
  has_end_image?: boolean
  image_paths?: string[]
}): Promise<H3WindowPlan> {
  const res = await fetch(`${BASE}/api/v1/llm/plan-h3-windows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'H3 window planning failed' }))
    throw new Error(err.detail || 'H3 window planning failed')
  }
  return res.json()
}

// --- Music: LLM song writer (Music mode Simple) ---

export async function writeSong(params: {
  description: string
  instrumental?: boolean
  target?: 'ace-step' | 'minimax'
  model?: 'music-3.0' | 'music-2.6' | 'music-cover' | 'ace_step_v1_5_xl_sft_lm_4b'
  reference_song?: string
  style_direction?: string
  lyrics_direction?: string
  story_context?: string
  language?: string
  duration_seconds?: number
  seed?: number
  reference_image_path?: string
  include_lyria?: boolean
  max_new_tokens?: number
  writingProvider?: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ style: string; lyrics: string; lyria_prompt: string; warnings?: string[]; raw: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/write-song`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Song writing failed' }))
    throw new Error(err.detail || 'Song writing failed')
  }
  return res.json()
}

// --- LLM Service ---

export async function generateLlmText(params: {
  prompt: string
  system_prompt?: string
  max_new_tokens?: number
  temperature?: number
  top_p?: number
  frequency_penalty?: number
  presence_penalty?: number
  json_schema?: Record<string, unknown>
}): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/llm/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: params.prompt,
      system_prompt: params.system_prompt || '',
      max_new_tokens: params.max_new_tokens ?? 1536,
      temperature: params.temperature ?? 0.3,
      top_p: params.top_p ?? 0.9,
      frequency_penalty: params.frequency_penalty ?? 0,
      presence_penalty: params.presence_penalty ?? 0,
      json_schema: params.json_schema,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'LLM generate failed' }))
    throw new Error(err.detail || err.error || 'LLM generate failed')
  }
  const body = await res.json()
  return String(body.text || '')
}

export async function fetchLlmStatus(): Promise<import('../types').LlmStatus> {
  const res = await fetch(`${BASE}/api/v1/llm/status`)
  if (!res.ok) throw new Error('Failed to fetch LLM status')
  return res.json()
}

export async function loadLlm(
  params?: { model_id?: string; device?: string }
): Promise<import('../types').LlmStatus & { status: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/load`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Load failed' }))
    throw new Error(err.detail || 'Load failed')
  }
  return res.json()
}

export async function unloadLlm(): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/llm/unload`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to unload LLM')
}

export async function fetchLlmModels(provider?: string): Promise<{ models: import('../types').LlmModelOption[] }> {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : ''
  const res = await fetch(`${BASE}/api/v1/llm/models${query}`)
  if (!res.ok) throw new Error('Failed to fetch LLM models')
  return res.json()
}

export async function testLlmConnection(): Promise<{ ok: boolean; response: string; status: import('../types').LlmStatus }> {
  let res: Response
  try {
    res = await fetch(`${BASE}/api/v1/llm/test`, { method: 'POST' })
  } catch {
    throw new Error('HocusPocus backend is unreachable. Reopen the current WebUI from Pinokio and try again')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'LLM test failed' }))
    throw new Error(err.detail || 'LLM test failed')
  }
  return res.json()
}

export async function llmEnhancePrompt(params: {
  prompt: string
  mode?: string
  model_type?: string
  temperature?: number
  image_path?: string
  image_paths?: string[]
  duration_seconds?: number
  window_count?: number
  window_size_seconds?: number
  activated_loras?: string[]
  tts_enhance_mode?: string
  tts_voice_count?: number
  max_new_tokens?: number
  reference_context?: string
}): Promise<{ original: string; enhanced: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/enhance-prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Enhancement failed' }))
    throw new Error(err.detail || 'Enhancement failed')
  }
  return res.json()
}

export async function getLlmStreamStatus(): Promise<{ text: string; done: boolean }> {
  const res = await fetch(`${BASE}/api/v1/llm/stream-status`)
  if (!res.ok) return { text: '', done: true }
  return res.json()
}
