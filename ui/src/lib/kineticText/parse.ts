import { KINETIC_PRESETS, TEXT_ALIGNS, TEXT_BOX_KINDS, TEXT_ENTERS, TEXT_EXITS, TEXT_FONTS, TEXT_LOOPS, TEXT_WEIGHTS, type KineticText, type TextAlign, type TextBox, type TextCounter, type TextEnter, type TextExit, type TextFill, type TextLoop, type TextShadow, type TextStroke, type TextWeight } from './types'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const numeric = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const hex = (value: unknown) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : undefined
const oneOf = <T extends string>(value: unknown, allowed: readonly T[]) => typeof value === 'string' && (allowed as readonly string[]).includes(value) ? value as T : undefined
const bounded = (value: unknown, min: number, max: number) => typeof value === 'number' && Number.isFinite(value) ? clamp(value, min, max) : undefined

function parseSpan<T extends string>(value: unknown, allowed: readonly T[]) {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { preset?: unknown; duration?: unknown }
  const preset = oneOf(raw.preset, allowed)
  const duration = bounded(raw.duration, 0.05, 3)
  return preset && duration != null ? { preset, duration } : undefined
}

function parseStroke(value: unknown): TextStroke | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { color?: unknown; width?: unknown }
  const color = hex(raw.color)
  const width = bounded(raw.width, 0, 0.3)
  return color && width != null ? { color, width } : undefined
}

function parseShadow(value: unknown): TextShadow | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { color?: unknown; blur?: unknown; x?: unknown; y?: unknown }
  const color = hex(raw.color)
  const blur = bounded(raw.blur, 0, 2)
  const x = bounded(raw.x, -1, 1)
  const y = bounded(raw.y, -1, 1)
  return color && blur != null && x != null && y != null ? { color, blur, x, y } : undefined
}

function parseFill(value: unknown): TextFill | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { kind?: unknown; from?: unknown; to?: unknown; angle?: unknown }
  if (raw.kind === 'solid') return { kind: 'solid' }
  const from = hex(raw.from)
  const to = hex(raw.to)
  if (raw.kind !== 'gradient' || !from || !to) return undefined
  return { kind: 'gradient', from, to, angle: bounded(raw.angle, -180, 180) ?? 90 }
}

function parseBox(value: unknown): TextBox | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { kind?: unknown; color?: unknown; opacity?: unknown; padding?: unknown; radius?: unknown }
  const kind = oneOf(raw.kind, TEXT_BOX_KINDS)
  const color = hex(raw.color)
  const opacity = bounded(raw.opacity, 0, 1)
  const padding = bounded(raw.padding, 0, 4)
  if (!kind || !color || opacity == null || padding == null) return undefined
  const radius = bounded(raw.radius, 0, 2)
  return { kind, color, opacity, padding, ...(radius != null ? { radius } : {}) }
}

function parseCounter(value: unknown): TextCounter | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { from?: unknown; to?: unknown; decimals?: unknown; ease?: unknown }
  if (typeof raw.from !== 'number' || !Number.isFinite(raw.from) || typeof raw.to !== 'number' || !Number.isFinite(raw.to)) return undefined
  const decimals = bounded(raw.decimals, 0, 4)
  const ease = raw.ease === 'ease' ? 'ease' : raw.ease === 'linear' ? 'linear' : undefined
  return decimals != null && ease ? { from: raw.from, to: raw.to, decimals: Math.round(decimals), ease } : undefined
}

function parseCue(value: Partial<KineticText> | null, ids: Set<string>): KineticText | undefined {
  if (!value || typeof value.id !== 'string' || !value.id || ids.has(value.id)) return undefined
  if (typeof value.text !== 'string' || value.text.length > 240) return undefined
  const start = Math.max(0, numeric(value.start, 0))
  const end = numeric(value.end, start + 3)
  if (end <= start) return undefined
  ids.add(value.id)
  const font = oneOf(value.font, TEXT_FONTS)
  const weight = TEXT_WEIGHTS.find(item => item === value.weight)
  const enter = parseSpan(value.enter, TEXT_ENTERS)
  const exit = parseSpan(value.exit, TEXT_EXITS)
  const loop = oneOf(value.loop, TEXT_LOOPS)
  const align = oneOf(value.align, TEXT_ALIGNS)
  const stroke = parseStroke(value.stroke)
  const shadow = parseShadow(value.shadow)
  const fill = parseFill(value.fill)
  const box = parseBox(value.box)
  const counter = parseCounter(value.counter)
  const template = typeof value.template === 'string' && value.template.trim() ? value.template.trim().slice(0, 80) : undefined
  return {
    id: value.id, text: value.text, start, end,
    preset: KINETIC_PRESETS.includes(value.preset!) ? value.preset! : 'impact',
    x: clamp(numeric(value.x, 50), 0, 100), y: clamp(numeric(value.y, 82), 0, 100),
    size: clamp(numeric(value.size, 9), 2, 25),
    color: hex(value.color) ?? '#ffe3a0',
    rotation: clamp(numeric(value.rotation, 0), -45, 45),
    ...(font ? { font } : {}),
    ...(enter ? { enter: enter as { preset: TextEnter; duration: number } } : {}),
    ...(exit ? { exit: exit as { preset: TextExit; duration: number } } : {}),
    ...(loop ? { loop: loop as TextLoop } : {}),
    ...(weight ? { weight: weight as TextWeight } : {}),
    ...(align ? { align: align as TextAlign } : {}),
    ...(bounded(value.maxWidth, 10, 100) != null ? { maxWidth: bounded(value.maxWidth, 10, 100) } : {}),
    ...(bounded(value.lineHeight, 0.8, 2) != null ? { lineHeight: bounded(value.lineHeight, 0.8, 2) } : {}),
    ...(bounded(value.letterSpacing, -0.1, 0.5) != null ? { letterSpacing: bounded(value.letterSpacing, -0.1, 0.5) } : {}),
    ...(value.uppercase === true ? { uppercase: true } : {}),
    ...(value.italic === true ? { italic: true } : {}),
    ...(stroke ? { stroke } : {}),
    ...(shadow ? { shadow } : {}),
    ...(fill ? { fill } : {}),
    ...(box ? { box } : {}),
    ...(counter ? { counter } : {}),
    ...(template ? { template } : {}),
  }
}

/** Shared, bounded text contract for the 2D compositor and world-space editor. */
export function parseKineticTexts(raw: unknown): KineticText[] {
  if (!Array.isArray(raw)) return []
  const ids = new Set<string>()
  return raw.slice(0, 48).flatMap((value: Partial<KineticText> | null) => {
    const cue = parseCue(value, ids)
    return cue ? [cue] : []
  })
}

export function kineticTextFields(raw: unknown): { texts?: KineticText[] } {
  const texts = parseKineticTexts(raw)
  return texts.length ? { texts } : {}
}

export function isLegacyKineticText(cue: KineticText) {
  const modernFont = cue.font != null && cue.font !== 'sans' && cue.font !== 'mono'
  return !modernFont && cue.enter == null && cue.exit == null && cue.loop == null && cue.weight == null
    && cue.align == null && cue.maxWidth == null && cue.lineHeight == null && cue.letterSpacing == null
    && cue.uppercase == null && cue.italic == null && cue.stroke == null && cue.shadow == null
    && cue.fill == null && cue.box == null && cue.counter == null
}

/** What a v1 preset means once enter, exit and loop are written down. Short cues still cap the fade the way they always have. */
export function derivedTextMotion(preset: KineticText['preset']): { enter: TextEnter; loop: TextLoop; exit: TextExit; exitSeconds: number } {
  if (preset === 'wave') return { enter: 'none', loop: 'wave', exit: 'fade', exitSeconds: 0.3 }
  if (preset === 'rise') return { enter: 'rise', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
  if (preset === 'typewriter') return { enter: 'typewriter', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
  return { enter: 'impact', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
}
