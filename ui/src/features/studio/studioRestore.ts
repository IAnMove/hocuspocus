export const CLIP_BOUNDARY = '\n---CLIP_BOUNDARY---\n'

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
