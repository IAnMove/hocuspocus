import {
  VIDEOJS_LIMITS,
  newVideoJsId,
  normalizeTheme,
  normalizeVideoJsScene,
  touchVideoJsDocument,
  videoJsFormatOf,
} from './document.ts'
import { VIDEOJS_SYSTEM_PROMPT } from './promptGuide.ts'
import type { VideoJsDocument, VideoJsScene, VideoJsSceneError } from './types.ts'

export interface ParsedVideoJsScene {
  id?: string
  title?: string
  kind?: string
  duration?: string
  transition?: string
  transitionDuration?: string
  code: string
}

export interface ParsedVideoJs {
  title?: string
  theme?: Record<string, string>
  scenes: ParsedVideoJsScene[]
  /** False when the closing </video> is missing (usually a truncated answer). */
  complete: boolean
}

export type VideoJsLlmRequest =
  | { mode: 'create'; request: string }
  | { mode: 'adjust-video'; instruction: string }
  | { mode: 'adjust-scene'; sceneId: string; instruction: string }
  | { mode: 'fix-scene'; sceneId: string; error: VideoJsSceneError }

export class VideoJsLlmError extends Error {
  readonly code: 'empty' | 'truncated' | 'missing-scene'

  constructor(code: VideoJsLlmError['code'], message: string) {
    super(message)
    this.name = 'VideoJsLlmError'
    this.code = code
  }
}

function attributes(source: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const match of source.matchAll(/([A-Za-z][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) {
    result[match[1]] = match[2] ?? match[3] ?? ''
  }
  return result
}

function cleanCode(source: string): string {
  return source
    .replace(/^\s*```[a-z]*\s*\n/i, '')
    .replace(/\n?\s*```\s*$/i, '')
    .replace(/^\n+|\s+$/g, '')
}

/** Tolerant parser for the tag format described in VIDEOJS_SYSTEM_PROMPT. */
export function parseVideoJsResponse(text: string): ParsedVideoJs {
  const source = String(text || '').replace(/<think>[\s\S]*?<\/think>/gi, '')
  const video = source.match(/<video\b([^>]*)>/i)
  const theme = source.match(/<theme\b([^>]*?)\/?>/i)
  const scenes = [...source.matchAll(/<scene\b([^>]*)>([\s\S]*?)<\/scene>/gi)].map(match => {
    const attrs = attributes(match[1])
    return {
      ...(attrs.id ? { id: attrs.id } : {}),
      title: attrs.title,
      kind: attrs.kind,
      duration: attrs.duration,
      transition: attrs.transition,
      transitionDuration: attrs.transitionDuration ?? attrs['transition-duration'],
      code: cleanCode(match[2]),
    }
  }).filter(scene => scene.code)
  return {
    ...(video && attributes(video[1]).title ? { title: attributes(video[1]).title } : {}),
    ...(theme ? { theme: attributes(theme[1]) } : {}),
    scenes,
    complete: /<\/video>/i.test(source),
  }
}

const THEME_COLORS = ['background', 'surface', 'primary', 'secondary', 'accent', 'text', 'muted'] as const

function sceneTag(scene: VideoJsScene): string {
  const attrs = `id="${scene.id}" title="${scene.title.replace(/"/g, "'")}" kind="${scene.kind}" duration="${scene.duration}" transition="${scene.transition}"`
  return `<scene ${attrs}>\n${scene.code}\n</scene>`
}

function themeTag(document: VideoJsDocument): string {
  const colors = THEME_COLORS.map(key => `${key}="${document.theme[key]}"`)
  return `<theme ${colors.join(' ')} />`
}

export function serializeVideoJsForLlm(document: VideoJsDocument): string {
  return `<video title="${document.title.replace(/"/g, "'")}">\n${themeTag(document)}\n${document.scenes.map(sceneTag).join('\n')}\n</video>`
}

function formatLine(document: VideoJsDocument): string {
  return `FORMAT: ${document.width}x${document.height} pixels (${videoJsFormatOf(document)}), ${document.fps} fps.`
}

function sceneIndex(document: VideoJsDocument): string {
  return document.scenes.map((scene, index) => `${index + 1}. id=${scene.id} "${scene.title}" ${scene.kind} ${scene.duration}s`).join('\n')
}

function targetScene(document: VideoJsDocument, sceneId: string): VideoJsScene {
  const scene = document.scenes.find(item => item.id === sceneId)
  if (!scene) throw new VideoJsLlmError('missing-scene', 'The selected scene no longer exists')
  return scene
}

export function buildVideoJsPrompt(document: VideoJsDocument, request: VideoJsLlmRequest): string {
  if (request.mode === 'create') {
    return `${formatLine(document)}\n\nREQUEST:\n${request.request.trim()}\n\nCreate the complete video now.`
  }
  if (request.mode === 'adjust-video') {
    return `${formatLine(document)}\n\nCURRENT VIDEO:\n${serializeVideoJsForLlm(document)}\n\nCHANGE REQUEST:\n${request.instruction.trim()}\n\nReturn the complete <video> with every scene in the final order. Keep the id of every scene you keep, copy unchanged scenes exactly, omit id only for new scenes.`
  }
  const scene = targetScene(document, request.sceneId)
  const change = request.mode === 'fix-scene'
    ? `FIX THIS ERROR (${request.error.phase}${request.error.line ? `, line ${request.error.line}` : ''}):\n${request.error.message}\nKeep the design, text and timing; change only what is needed.`
    : `CHANGE REQUEST:\n${request.instruction.trim()}`
  return `${formatLine(document)}\n\nVIDEO: "${document.title}"\n${themeTag(document)}\nSCENES:\n${sceneIndex(document)}\n\nSCENE TO EDIT:\n${sceneTag(scene)}\n\n${change}\n\nReturn a <video> that contains exactly one <scene> with id="${scene.id}".`
}

function sceneFrom(parsed: ParsedVideoJsScene, index: number, base?: VideoJsScene): VideoJsScene {
  return normalizeVideoJsScene({
    ...base,
    id: base?.id ?? newVideoJsId(),
    title: parsed.title ?? base?.title,
    kind: parsed.kind ?? base?.kind,
    duration: parsed.duration ?? base?.duration,
    transition: parsed.transition ?? base?.transition,
    transitionDuration: parsed.transitionDuration ?? base?.transitionDuration,
    code: parsed.code,
  }, index)
}

function withHeader(document: VideoJsDocument, parsed: ParsedVideoJs): VideoJsDocument {
  return {
    ...document,
    title: parsed.title?.trim().slice(0, 160) || document.title,
    theme: parsed.theme ? normalizeTheme({ ...document.theme, ...parsed.theme }) : document.theme,
  }
}

/** Merge an LLM answer into the document. Returns a new document; never mutates. */
export function applyVideoJsResponse(document: VideoJsDocument, request: VideoJsLlmRequest, text: string): VideoJsDocument {
  const parsed = parseVideoJsResponse(text)
  if (!parsed.scenes.length) throw new VideoJsLlmError('empty', 'The LLM answer did not contain any <scene>')
  if (request.mode === 'create' || request.mode === 'adjust-video') {
    if (!parsed.complete) throw new VideoJsLlmError('truncated', 'The LLM answer was cut before </video>; nothing was applied')
    const existing = new Map(request.mode === 'adjust-video' ? document.scenes.map(scene => [scene.id, scene]) : [])
    const used = new Set<string>()
    const scenes = parsed.scenes.slice(0, VIDEOJS_LIMITS.scenes).map((item, index) => {
      const base = item.id && !used.has(item.id) ? existing.get(item.id) : undefined
      if (base) used.add(base.id)
      return sceneFrom(item, index, base)
    })
    return touchVideoJsDocument({
      ...withHeader(document, parsed),
      scenes,
      ...(request.mode === 'create' ? { prompt: request.request.trim().slice(0, 20_000) } : {}),
    })
  }
  const target = targetScene(document, request.sceneId)
  const item = parsed.scenes.find(scene => scene.id === target.id) ?? parsed.scenes[0]
  return touchVideoJsDocument({
    ...document,
    scenes: document.scenes.map((scene, index) => scene.id === target.id ? sceneFrom(item, index, scene) : scene),
  })
}

export function videoJsLlmBudget(request: VideoJsLlmRequest): number {
  return request.mode === 'create' || request.mode === 'adjust-video' ? 16_000 : 6_000
}

export async function runVideoJsLlm(
  document: VideoJsDocument,
  request: VideoJsLlmRequest,
  generate: (params: { prompt: string; system_prompt: string; max_new_tokens: number; temperature: number; top_p: number }) => Promise<string>,
): Promise<VideoJsDocument> {
  const text = await generate({
    prompt: buildVideoJsPrompt(document, request),
    system_prompt: VIDEOJS_SYSTEM_PROMPT,
    max_new_tokens: videoJsLlmBudget(request),
    temperature: request.mode === 'fix-scene' ? 0.2 : 0.6,
    top_p: 0.95,
  })
  return applyVideoJsResponse(document, request, text)
}
