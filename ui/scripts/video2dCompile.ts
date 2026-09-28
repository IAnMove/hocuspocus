// Headless bridge: the MCP server validates catalog ids, then this module calls
// the existing UI builders. It does not save, export, or fetch the network.
import { getCandidateSceneTemplate } from '../src/features/sceneTemplates/catalog.ts'
import { compileCandidateScene, type TemplateBindings, type TemplateControls } from '../src/features/sceneTemplates/compile.ts'
import { compileVideo2dCandidate, VIDEO2D_CANDIDATE_IDS, type Video2dCandidateSize } from '../src/features/sceneTemplates/video2dCandidates.ts'
import { buildTextTemplate, TEXT_TEMPLATES } from '../src/lib/kineticText/templates.ts'
import { importLrc, importPlainLyrics, importSrt, importTimingBundle, parseSceneLyrics, type SceneLyrics } from '../src/lib/kineticText/lyrics.ts'
import type { KineticText } from '../src/lib/kineticText/types.ts'
import type { Scene } from '../src/types/index.ts'

const Y_MIN = 12
const Y_MAX = 80
const WIDTH_MAX = 90

export type BridgeFailure = { ok: false; code: string; message: string }
export type BridgeResult = { ok: true; result: { document: Scene; warnings: string[] } | { texts: KineticText[] } | { lyrics: SceneLyrics } } | BridgeFailure

class CodedError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

function asCoded(error: unknown): CodedError {
  if (error instanceof CodedError) return error
  const message = error instanceof Error ? error.message : 'Compile failed'
  return new CodedError(codeFor(message), message)
}

function codeFor(message: string): string {
  if (message.startsWith('Unknown candidate') || message.includes('no tiene compilador')) return 'template_unknown'
  if (message.startsWith('Falta el slot') || message.startsWith('Falta el recurso')) return 'template_missing_slot'
  if (message.includes('debe estar entre')) return 'template_bad_control'
  if (message.includes('slot') || message.includes('recurso') || message.includes('asset') || message.includes('MIME') || message.includes('GLB')) return 'template_bad_asset'
  return 'template_compile_failed'
}

function stringMap(value: unknown, code: string): Record<string, string> {
  if (value == null) return {}
  if (typeof value !== 'object' || Array.isArray(value)) throw new CodedError(code, 'map')
  const entries: Record<string, string> = {}
  for (const [key, item] of Object.entries(value)) {
    if (typeof item !== 'string') throw new CodedError(code, key)
    entries[key] = item
  }
  return entries
}

function slotType(source: string, kinds: readonly ('image' | 'model3d')[]): 'image' | 'model3d' {
  if (/^data:model\/gltf-binary;/i.test(source) || /\.glb(?:$|[?#])/i.test(source)) return 'model3d'
  if (kinds.length === 1 && kinds[0] === 'model3d') return 'model3d'
  return 'image'
}

function sceneBindings(id: string, assets: unknown): TemplateBindings {
  const template = getCandidateSceneTemplate(id)
  const map = stringMap(assets, 'template_bad_asset')
  const bindings: TemplateBindings = {}
  for (const slot of template.slots) {
    const source = map[slot.id]
    if (!source) continue
    const type = slotType(source, slot.kinds)
    if (!slot.kinds.includes(type)) throw new CodedError('template_bad_asset', slot.id)
    bindings[slot.id] = { source, type, name: slot.id }
  }
  return bindings
}

function sceneControls(value: unknown): Partial<TemplateControls> {
  if (value == null) return {}
  if (typeof value !== 'object' || Array.isArray(value)) throw new CodedError('template_bad_control', 'controls')
  const controls: Partial<TemplateControls> = {}
  for (const key of ['duration', 'bpm', 'intensity'] as const) {
    const item = (value as Record<string, unknown>)[key]
    if (item == null) continue
    if (typeof item !== 'number' || !Number.isFinite(item)) throw new CodedError('template_bad_control', key)
    controls[key] = item
  }
  return controls
}

function numericSize(input: Record<string, unknown>): Video2dCandidateSize {
  const controls = input.controls && typeof input.controls === 'object' && !Array.isArray(input.controls)
    ? input.controls as Record<string, unknown>
    : {}
  const duration = typeof input.duration === 'number' ? input.duration
    : typeof controls.duration === 'number' ? controls.duration
    : undefined
  const size: Video2dCandidateSize = {}
  if (typeof input.width === 'number') size.width = input.width
  if (typeof input.height === 'number') size.height = input.height
  if (typeof duration === 'number') size.duration = duration
  if (typeof input.fps === 'number') size.fps = input.fps
  return size
}

function frameRate(value: unknown): 24 | 30 | 60 | undefined {
  if (value === 24 || value === 30 || value === 60) return value
  return undefined
}

function applyFrame(scene: Scene, input: Record<string, unknown>): Scene {
  const width = typeof input.width === 'number' ? input.width : scene.width
  const height = typeof input.height === 'number' ? input.height : scene.height
  const fps = frameRate(input.fps) ?? scene.fps
  return { ...scene, width, height, ...(fps != null ? { fps } : {}) }
}

function safeCue(cue: KineticText): KineticText {
  const y = Math.min(Y_MAX, Math.max(Y_MIN, cue.y))
  if (cue.maxWidth == null) return y === cue.y ? cue : { ...cue, y }
  const maxWidth = Math.min(WIDTH_MAX, cue.maxWidth)
  if (y === cue.y && maxWidth === cue.maxWidth) return cue
  return { ...cue, y, maxWidth }
}

function safeLyrics(lyrics: SceneLyrics): SceneLyrics {
  const y = Math.min(Y_MAX, Math.max(Y_MIN, lyrics.style.y))
  const maxWidth = Math.min(WIDTH_MAX, lyrics.style.maxWidth)
  if (y === lyrics.style.y && maxWidth === lyrics.style.maxWidth) return lyrics
  return { ...lyrics, style: { ...lyrics.style, y, maxWidth } }
}

function fitPortrait(scene: Scene, warnings: string[]): Scene {
  if (!(scene.height > scene.width)) return scene
  const texts = scene.texts?.map(cue => {
    const next = safeCue(cue)
    if (next !== cue) warnings.push(`title ${cue.id} moved into the vertical safe area`)
    return next
  })
  const lyrics = scene.lyrics ? safeLyrics(scene.lyrics) : undefined
  if (lyrics && lyrics !== scene.lyrics) warnings.push('lyrics moved into the vertical safe area')
  return { ...scene, ...(texts ? { texts } : {}), ...(lyrics ? { lyrics } : {}) }
}

function compileScene(input: Record<string, unknown>): Scene {
  const id = input.templateId
  if (typeof id !== 'string' || !id) throw new CodedError('template_unknown', 'templateId')
  if ((VIDEO2D_CANDIDATE_IDS as readonly string[]).includes(id)) {
    const scene = compileVideo2dCandidate(id, numericSize(input), stringMap(input.assets, 'template_bad_asset'))
    if (!scene) throw new CodedError('template_unknown', id)
    return scene
  }
  return compileCandidateScene(id, sceneBindings(id, input.assets), sceneControls(input.controls))
}

function compileTemplate(input: Record<string, unknown>) {
  const warnings: string[] = []
  const document = fitPortrait(applyFrame(compileScene(input), input), warnings)
  return { document, warnings }
}

function compileText(input: Record<string, unknown>) {
  const id = input.templateId
  if (typeof id !== 'string' || !TEXT_TEMPLATES.some(item => item.id === id)) throw new CodedError('text_template_unknown', 'templateId')
  const frame = {
    start: typeof input.start === 'number' ? input.start : 0,
    duration: typeof input.duration === 'number' ? input.duration : 4,
    width: typeof input.width === 'number' ? input.width : 1920,
    height: typeof input.height === 'number' ? input.height : 1080,
  }
  const portrait = frame.height > frame.width
  return { texts: buildTextTemplate(id, stringMap(input.fields, 'text_template_bad_field'), frame).map(cue => safeCuePortrait(cue, portrait)) }
}

function safeCuePortrait(cue: KineticText, portrait: boolean) {
  return portrait ? safeCue(cue) : cue
}

function sourceKind(format: 'srt' | 'lrc' | 'plain' | 'timing-bundle'): NonNullable<SceneLyrics['source']>['kind'] {
  if (format === 'plain') return 'manual'
  return format
}

function readBundle(text: string): unknown {
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new CodedError('lyrics_bad_file', 'timing bundle is not JSON')
  }
}

function lyricLines(format: 'srt' | 'lrc' | 'plain' | 'timing-bundle', text: string, duration: number) {
  if (format === 'srt') return importSrt(text)
  if (format === 'lrc') return importLrc(text)
  if (format === 'plain') return importPlainLyrics(text, duration)
  return importTimingBundle(readBundle(text))
}

function compileLyrics(input: Record<string, unknown>) {
  const format = input.format
  const text = input.text
  if (format !== 'srt' && format !== 'lrc' && format !== 'plain' && format !== 'timing-bundle') {
    throw new CodedError('lyrics_bad_format', 'format')
  }
  if (typeof text !== 'string' || !text.trim()) throw new CodedError('lyrics_bad_file', 'text')
  const duration = typeof input.duration === 'number' ? input.duration : 8
  const lines = lyricLines(format, text, duration)
  const lyrics = parseSceneLyrics({ mode: 'karaoke', lines, source: { kind: sourceKind(format) } })
  if (!lyrics) throw new CodedError('lyrics_bad_file', 'unreadable lyrics')
  return { lyrics }
}

function dispatch(payload: unknown) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new CodedError('compile_bad_envelope', 'payload')
  const body = payload as { operation?: unknown; input?: unknown }
  if (!body.input || typeof body.input !== 'object' || Array.isArray(body.input)) throw new CodedError('compile_bad_envelope', 'input')
  const input = body.input as Record<string, unknown>
  if (body.operation === 'scenes.template.compile') return compileTemplate(input)
  if (body.operation === 'scenes.text.template') return compileText(input)
  if (body.operation === 'scenes.lyrics.import') return compileLyrics(input)
  throw new CodedError('compile_unknown_operation', 'operation')
}

export function compilePayload(payload: unknown): BridgeResult {
  try {
    return { ok: true, result: dispatch(payload) }
  } catch (error) {
    const coded = asCoded(error)
    return { ok: false, code: coded.code, message: coded.message }
  }
}
