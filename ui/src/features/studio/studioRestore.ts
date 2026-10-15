export const CLIP_BOUNDARY = '\n---CLIP_BOUNDARY---\n'

/** Only call after the output has been identified as SFX, never on tab entry. */
export function restoredSfxSettings(params: Record<string, unknown>) {
  return {
    MMAudio_prompt: typeof params.MMAudio_prompt === 'string' ? params.MMAudio_prompt
      : typeof params.prompt === 'string' ? params.prompt : '',
    MMAudio_neg_prompt: typeof params.MMAudio_neg_prompt === 'string' ? params.MMAudio_neg_prompt : '',
    sfx_text_weight: typeof params.sfx_text_weight === 'number' ? params.sfx_text_weight : 1,
    guidance_scale: typeof params.guidance_scale === 'number' ? params.guidance_scale : 4.5,
    video_length: 0,
  }
}

/**
 * Extend and Blend outputs. The submit rewrites their `image_mode` to 0 and the
 * sidecar keeps the source clip as `video_source` (with a `V` flag) or as `_blend_*`.
 * Load Settings does not restore that working set yet, so it lands on Frames with
 * no source video and a reroll would run a plain text-to-video. Edit sidecars
 * (`edit_sub_mode`) have their own restore and are not affected.
 */
export function isExtendOrBlendOutput(params: Record<string, unknown> | null | undefined): boolean {
  if (!params || params.edit_sub_mode) return false
  if (typeof params._blend_mode === 'string' && params._blend_mode) return true
  const flags = typeof params.image_prompt_type === 'string' ? params.image_prompt_type : ''
  return flags.includes('V') && typeof params.video_source === 'string' && params.video_source.length > 0
}

const JOINED_SEQUENCE_NAME = /(?:^|[._-])multiclip\.(?:mp4|webm|mkv|mov)$/i

export function isJoinedSequenceOutput(name: string | null | undefined): boolean {
  return JOINED_SEQUENCE_NAME.test(String(name || ''))
}

export function splitStudioClipPrompts(prompt: string): string[] {
  const text = String(prompt || '').trim()
  if (!text) return []
  if (text.includes(CLIP_BOUNDARY)) {
    return text.split(CLIP_BOUNDARY).map(part => part.trim()).filter(Boolean)
  }
  const h3Blocks = text.split(/(?=integrated_multimodal_description:)/i)
    .map(part => part.trim())
    .filter(Boolean)
  if (h3Blocks.length > 1) return h3Blocks
  if (/integrated_multimodal_description:|subject_definitions:/.test(text)) {
    return [text]
  }
  return text.split('\n').map(part => part.trim()).filter(Boolean)
}

function indexedValue<T>(value: T | T[] | undefined, index: number): T | undefined {
  if (Array.isArray(value)) return value[index] ?? value[0]
  return value
}

export function clipIndexFromOutputParams(
  params: Record<string, unknown>,
): number {
  const info = params.multi_clip_info
  if (info && typeof info === 'object' && Number.isInteger((info as { index?: unknown }).index)) {
    return Math.max(0, Number((info as { index: number }).index))
  }
  return 0
}

export function extractSingleClipStudioParams(
  params: Record<string, unknown>,
): {
  prompt: string
  imageStart: string
  imageEnd: string
  videoLength: number | undefined
  imagePromptType: string
} {
  const index = clipIndexFromOutputParams(params)
  const prompts = splitStudioClipPrompts(String(params.prompt || ''))
  const prompt = prompts[index] || prompts[0] || String(params.prompt || '')
  const imageStart = String(indexedValue(params.image_start, index) || '')
  const imageEnd = String(indexedValue(params.image_end, index) || '')
  const perClipFrames = Array.isArray(params.per_clip_frames)
    ? params.per_clip_frames
    : []
  const frameValue = perClipFrames[index] ?? params.video_length
  const videoLength = typeof frameValue === 'number' && frameValue > 0 ? frameValue : undefined
  return {
    prompt,
    imageStart,
    imageEnd,
    videoLength,
    imagePromptType: imageStart ? (imageEnd ? 'SE' : 'S') : '',
  }
}
