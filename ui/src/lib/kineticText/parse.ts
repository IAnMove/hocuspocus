import { parseGraphicCue } from '../scene2d/graphics'
import { KINETIC_PRESETS, TEXT_ALIGNS, TEXT_BOX_KINDS, TEXT_ENTERS, TEXT_EXITS, TEXT_FONTS, TEXT_LOOPS, TEXT_WEIGHTS, type KineticText, type TextBox, type TextCounter, type TextEnter, type TextExit, type TextFill, type TextLoop, type TextShadow, type TextStroke } from './types'

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

function defined(fields: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value != null))
}

function cueLook(value: Partial<KineticText>) {
  const template = typeof value.template === 'string' ? value.template.trim().slice(0, 80) : ''
  return defined({
    font: oneOf(value.font, TEXT_FONTS),
    weight: TEXT_WEIGHTS.find(item => item === value.weight),
    enter: parseSpan(value.enter, TEXT_ENTERS),
    exit: parseSpan(value.exit, TEXT_EXITS),
    loop: oneOf(value.loop, TEXT_LOOPS),
    align: oneOf(value.align, TEXT_ALIGNS),
    maxWidth: bounded(value.maxWidth, 10, 100),
    lineHeight: bounded(value.lineHeight, 0.8, 2),
    letterSpacing: bounded(value.letterSpacing, -0.1, 0.5),
    uppercase: value.uppercase === true ? true : undefined,
    italic: value.italic === true ? true : undefined,
    stroke: parseStroke(value.stroke),
    shadow: parseShadow(value.shadow),
    fill: parseFill(value.fill),
    box: parseBox(value.box),
    counter: parseCounter(value.counter),
    graphic: parseGraphicCue(value.graphic),
    template: template || undefined,
    beatPulse: bounded(value.beatPulse, 0, 1),
  })
}

function parseCue(value: Partial<KineticText> | null, ids: Set<string>): KineticText | undefined {
  if (!value || typeof value.id !== 'string' || !value.id || ids.has(value.id)) return undefined
  if (typeof value.text !== 'string' || value.text.length > 240) return undefined
  const start = Math.max(0, numeric(value.start, 0))
  const end = numeric(value.end, start + 3)
  if (end <= start) return undefined
  ids.add(value.id)
  return {
    id: value.id, text: value.text, start, end,
    preset: KINETIC_PRESETS.includes(value.preset!) ? value.preset! : 'impact',
    x: clamp(numeric(value.x, 50), 0, 100), y: clamp(numeric(value.y, 82), 0, 100),
    size: clamp(numeric(value.size, 9), 2, 25),
    color: hex(value.color) ?? '#ffe3a0',
    rotation: clamp(numeric(value.rotation, 0), -45, 45),
    ...cueLook(value),
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

const MODERN_FIELDS = ['enter', 'exit', 'loop', 'weight', 'align', 'maxWidth', 'lineHeight', 'letterSpacing', 'uppercase', 'italic', 'stroke', 'shadow', 'fill', 'box', 'counter', 'graphic'] as const

export function isLegacyKineticText(cue: KineticText) {
  if (cue.font != null && cue.font !== 'sans' && cue.font !== 'mono') return false
  return MODERN_FIELDS.every(key => cue[key] == null)
}

/** What a v1 preset means once enter, exit and loop are written down. Short cues still cap the fade the way they always have. */
export function derivedTextMotion(preset: KineticText['preset']): { enter: TextEnter; loop: TextLoop; exit: TextExit; exitSeconds: number } {
  if (preset === 'wave') return { enter: 'none', loop: 'wave', exit: 'fade', exitSeconds: 0.3 }
  if (preset === 'rise') return { enter: 'rise', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
  if (preset === 'typewriter') return { enter: 'typewriter', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
  return { enter: 'impact', loop: 'none', exit: 'fade', exitSeconds: 0.3 }
}
