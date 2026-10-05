import catalog from '../../../../app/shared/scene_effects.json' with { type: 'json' }

/** `size`, `x`, `y` or `rotation` on an entry are that effect's defaults for a cue that gives none
 * (code rain: glyph height in %; light rays: where they come from and where they point). */
export type FxPreset = { id: string; color: string; sound: string; collection: string; size?: number; x?: number; y?: number; rotation?: number }
export const FX_CATALOG: ReadonlyArray<FxPreset> = catalog
/** A cue's size when it gives none. */
export const DEFAULT_FX_SIZE = 65
/** The shared defaults of the fields a catalog entry can set for its own effect. */
export const FX_FIELD_DEFAULTS = { size: DEFAULT_FX_SIZE, x: 50, y: 50, rotation: 0 } as const
const PRESET_FIELDS = Object.keys(FX_FIELD_DEFAULTS) as Array<keyof typeof FX_FIELD_DEFAULTS>
export type SceneFx = {
  id: string; kind: string; label?: string; start: number; end: number
  x: number; y: number; size: number; intensity: number; color: string
  seed: number; sound: boolean; volume: number
  rotation?: number
}
const number = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback

/** Absolute-time, seeded cues: scrubbing and export never advance a random simulation. */
export function parseSceneFx(raw: unknown): SceneFx[] {
  if (!Array.isArray(raw)) return []
  const ids = new Set<string>()
  return raw.slice(0, 64).flatMap((value: Partial<SceneFx> | null, index) => {
    const preset = FX_CATALOG.find(item => item.id === value?.kind)
    if (!value || !preset) return []
    const start = number(value.start, 0, 0, 600), end = number(value.end, start + 2, 0, 600)
    const id = typeof value.id === 'string' && value.id ? value.id.slice(0, 160) : `fx-${index}`
    if (end <= start || ids.has(id)) return []
    ids.add(id)
    return [{ id, kind: preset.id, ...(typeof value.label === 'string' ? { label: value.label.slice(0, 80) } : {}), start, end, x: number(value.x, preset.x ?? FX_FIELD_DEFAULTS.x, 0, 100), y: number(value.y, preset.y ?? FX_FIELD_DEFAULTS.y, 0, 100),
      size: number(value.size, preset.size ?? DEFAULT_FX_SIZE, 1, 200), intensity: number(value.intensity, 1, .1, 2),
      rotation: number(value.rotation, preset.rotation ?? FX_FIELD_DEFAULTS.rotation, -180, 180),
      color: typeof value.color === 'string' && /^#[\da-f]{6}$/i.test(value.color) ? value.color : preset.color,
      seed: Math.round(number(value.seed, index + 1, 1, 1000000)), sound: value.sound === true,
      volume: number(value.volume, .25, 0, 1) }]
  })
}
/** A cue switched to another effect takes that effect's colour, and its default size, x, y and
 * rotation where either effect has one of its own (a code-rain glyph height is not a burst size). */
export function switchFxKind(cue: Pick<SceneFx, 'kind'>, kind: string): Partial<SceneFx> {
  const next = FX_CATALOG.find(item => item.id === kind)
  if (!next) return {}
  const previous = FX_CATALOG.find(item => item.id === cue.kind)
  const reset = PRESET_FIELDS.filter(key => next[key] !== undefined || previous?.[key] !== undefined)
  return { kind, color: next.color, ...Object.fromEntries(reset.map(key => [key, next[key] ?? FX_FIELD_DEFAULTS[key]])) }
}
export function sceneFxFields(raw: unknown): { sfx?: SceneFx[] } {
  const sfx = parseSceneFx(raw)
  return sfx.length ? { sfx } : {}
}
export function fxRandom(seed: number, index: number) {
  let value = Math.imul(seed ^ (index + 1), 0x45d9f3b)
  value = Math.imul(value ^ (value >>> 16), 0x45d9f3b)
  return ((value ^ (value >>> 16)) >>> 0) / 4294967296
}

export const SCENE_FX_SCHEMA = {
  type: 'array', maxItems: 64, items: { type: 'object', additionalProperties: false,
    properties: { id: { type: 'string', maxLength: 160 }, kind: { enum: FX_CATALOG.map(item => item.id) },
      label: { type: 'string', maxLength: 80 }, start: { type: 'number', minimum: 0, maximum: 600 },
      end: { type: 'number', minimum: 0, maximum: 600 }, x: { type: 'number', minimum: 0, maximum: 100 },
      y: { type: 'number', minimum: 0, maximum: 100 }, size: { type: 'number', minimum: 1, maximum: 200 },
      intensity: { type: 'number', minimum: .1, maximum: 2 }, color: { type: 'string', pattern: '^#[0-9a-fA-F]{6}$' },
      rotation: { type: 'number', minimum: -180, maximum: 180 },
      seed: { type: 'integer', minimum: 1, maximum: 1000000 }, sound: { type: 'boolean' }, volume: { type: 'number', minimum: 0, maximum: 1 } },
    required: ['id', 'kind', 'start', 'end'] },
} as const
