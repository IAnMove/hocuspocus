import catalog from '../../../../app/shared/scene_effects.json' with { type: 'json' }
import { parseSceneFx, type SceneFx } from './types'
import { parseWorldMotion, parsePortalPlayback, type WorldSfxKeyframe, type PortalPlayback } from './worldMotion'

export const WORLD_SFX_KINDS = [
  'portal', 'magic_circle', 'summoning_gate',
  'lightning', 'energy_beam', 'laser',
  'energy_orb', 'anime_aura', 'arcane_missiles', 'shockwave',
  'smoke', 'sparks', 'explosion',
  'fire', 'rain', 'snow', 'fog', 'shield', 'tornado', 'splash', 'dust', 'ice_burst', 'black_hole',
  'media_portal',
] as const
export type WorldSfxKind = (typeof WORLD_SFX_KINDS)[number]
export const WORLD_BEAM_KINDS = new Set<WorldSfxKind>(['lightning', 'energy_beam', 'laser', 'arcane_missiles'])

export type WorldVec3 = { x: number; y: number; z: number }

export type WorldSfxAnchor = {
  slotId: string
  offset?: WorldVec3
}

export type WorldSfx = {
  id: string
  kind: WorldSfxKind
  label?: string
  start: number
  end: number
  position: WorldVec3
  rotation: WorldVec3
  scale: number
  intensity: number
  color: string
  seed: number
  sound: boolean
  volume: number
  anchor?: WorldSfxAnchor
  target?: WorldSfxAnchor
  targetPosition?: WorldVec3
  sourceUrl?: string
  motion?: WorldSfxKeyframe[]
  mediaProjection?: 'screen'
  mediaPlayback?: PortalPlayback
}

const PRESETS = Object.fromEntries(catalog.map(item => [item.id, item]))
const WORLD_DEFAULTS: Partial<Record<WorldSfxKind, { y: number; scale: number }>> = {
  magic_circle: { y: 0.02, scale: 1.4 },
  shockwave: { y: 0.02, scale: 1.4 },
  splash: { y: 0.02, scale: 1.4 },
  dust: { y: 0.02, scale: 1.4 },
  portal: { y: 1.15, scale: 1.4 },
  summoning_gate: { y: 1.15, scale: 1.4 },
  media_portal: { y: 1.15, scale: 1.7 },
  explosion: { y: 0.42, scale: 1.65 },
  ice_burst: { y: 0.42, scale: 1.4 },
  rain: { y: 0.05, scale: 2.1 },
  snow: { y: 0.05, scale: 2.1 },
  fog: { y: 0.05, scale: 2.1 },
  fire: { y: 0.15, scale: 1.4 },
  tornado: { y: 0.05, scale: 1.4 },
  laser: { y: 1, scale: 0.7 },
}
const number = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback

const TRANSIENT_MEDIA = /^(javascript|blob|file|filesystem):/i

/** Persistable portal media only. Blob/file URLs cannot be saved with the scene. */
export function worldMediaUrl(raw: unknown): string | undefined {
  if (typeof raw !== 'string') return undefined
  const url = raw.trim()
  return url && !TRANSIENT_MEDIA.test(url) ? url.slice(0, 2000) : undefined
}

export function worldAnchorOffsetFromWorldPoint(
  slot: { position: readonly [number, number, number]; rotationY: number },
  point: readonly [number, number, number],
): WorldVec3 {
  const dx = point[0] - slot.position[0]
  const dy = point[1] - slot.position[1]
  const dz = point[2] - slot.position[2]
  const cos = Math.cos(slot.rotationY)
  const sin = Math.sin(slot.rotationY)
  return { x: dx * cos - dz * sin, y: dy, z: dx * sin + dz * cos }
}

/** Persist a gizmo drag in the same frame the cue is drawn (live pose / GPU local). */
export function applyWorldSfxTranslate(
  cue: WorldSfx,
  worldPoint: readonly [number, number, number],
  posedAnchor?: { position: readonly [number, number, number]; rotationY: number },
  localOffset?: WorldVec3,
): WorldSfx {
  if (cue.anchor?.slotId && (localOffset || posedAnchor)) {
    return {
      ...cue,
      anchor: {
        slotId: cue.anchor.slotId,
        offset: localOffset ?? worldAnchorOffsetFromWorldPoint(posedAnchor!, worldPoint),
      },
    }
  }
  return { ...cue, position: { x: worldPoint[0], y: worldPoint[1], z: worldPoint[2] } }
}

export function worldVec3(raw: unknown, fallback: WorldVec3, min: number, max: number): WorldVec3 {
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return {
    x: number(value.x, fallback.x, min, max),
    y: number(value.y, fallback.y, min, max),
    z: number(value.z, fallback.z, min, max),
  }
}

export function isWorldSfxKind(value: unknown): value is WorldSfxKind {
  return typeof value === 'string' && (WORLD_SFX_KINDS as readonly string[]).includes(value)
}

function parseAnchor(raw: WorldSfxAnchor | undefined): WorldSfxAnchor | undefined {
  const slotId = typeof raw?.slotId === 'string' ? raw.slotId.slice(0, 160) : ''
  if (!slotId) return undefined
  const offset = raw?.offset ? worldVec3(raw.offset, { x: 0, y: 0, z: 0 }, -20, 20) : undefined
  return { slotId, ...(offset ? { offset } : {}) }
}

export function parseWorldSfx(raw: unknown): WorldSfx[] {
  if (!Array.isArray(raw)) return []
  const ids = new Set<string>()
  return raw.slice(0, 64).flatMap((value: Partial<WorldSfx> | null, index) => {
    if (!value || !isWorldSfxKind(value.kind) || !PRESETS[value.kind]) return []
    const start = number(value.start, 0, 0, 600)
    const end = number(value.end, start + 2, 0, 600)
    const id = typeof value.id === 'string' && value.id ? value.id.slice(0, 160) : `world-fx-${index}`
    if (end <= start || ids.has(id)) return []
    ids.add(id)
    const preset = PRESETS[value.kind]
    const layout = WORLD_DEFAULTS[value.kind] ?? { y: 1, scale: 1.4 }
    const sourceUrl = worldMediaUrl(value.sourceUrl)
    return [{
      id,
      kind: value.kind,
      ...(typeof value.label === 'string' ? { label: value.label.slice(0, 80) } : {}),
      start,
      end,
      position: worldVec3(value.position, { x: 0, y: layout.y, z: 0 }, -50, 50),
      rotation: worldVec3(value.rotation, { x: 0, y: 0, z: 0 }, -180, 180),
      scale: number(value.scale, layout.scale, 0.05, 20),
      intensity: number(value.intensity, 1, 0, 2),
      color: typeof value.color === 'string' && /^#[\da-f]{6}$/i.test(value.color) ? value.color : preset.color,
      seed: Math.round(number(value.seed, index + 21, 1, 1000000)),
      sound: value.sound === true,
      volume: number(value.volume, 0.25, 0, 1),
      ...(parseAnchor(value.anchor) ? { anchor: parseAnchor(value.anchor) } : {}),
      ...(parseAnchor(value.target) ? { target: parseAnchor(value.target) } : {}),
      ...(value.targetPosition ? { targetPosition: worldVec3(value.targetPosition, { x: 0, y: 1.2, z: 1.6 }, -50, 50) } : {}),
      ...(sourceUrl ? { sourceUrl } : {}),
      ...(parseWorldMotion(value.motion) ? { motion: parseWorldMotion(value.motion) } : {}),
      ...(value.mediaProjection === 'screen' ? { mediaProjection: 'screen' as const } : {}),
      ...(parsePortalPlayback(value.mediaPlayback) ? { mediaPlayback: parsePortalPlayback(value.mediaPlayback) } : {}),
    }]
  })
}

export function worldSfxAudioCues(cues: readonly WorldSfx[] | undefined): SceneFx[] {
  return parseSceneFx((cues ?? []).map(cue => ({
    id: cue.id,
    kind: cue.kind,
    start: cue.start,
    end: cue.end,
    intensity: cue.intensity,
    color: cue.color,
    seed: cue.seed,
    sound: cue.sound,
    volume: cue.volume,
  })))
}

export function createWorldSfx(kind: WorldSfxKind, duration: number, taken: Iterable<string> = []): WorldSfx {
  const used = new Set(taken)
  let id = `world-${kind}`
  let n = 1
  while (used.has(id)) { n += 1; id = `world-${kind}-${n}` }
  const beam = WORLD_BEAM_KINDS.has(kind)
  const blast = kind === 'explosion' || kind === 'ice_burst' || kind === 'splash'
  return parseWorldSfx([{
    id,
    kind,
    start: 0,
    end: Math.min(blast ? 2.6 : 8, Math.max(1, duration)),
    ...(beam ? { targetPosition: { x: 0, y: 1.2, z: 1.8 } } : {}),
    sound: true,
  }])[0]
}

export const WORLD_SFX_SCHEMA = {
  type: 'array', maxItems: 64, items: {
    type: 'object', additionalProperties: false,
    properties: {
      id: { type: 'string', maxLength: 160 },
      kind: { enum: [...WORLD_SFX_KINDS] },
      label: { type: 'string', maxLength: 80 },
      start: { type: 'number', minimum: 0, maximum: 600 },
      end: { type: 'number', minimum: 0, maximum: 600 },
      position: { type: 'object', additionalProperties: false, properties: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } }, required: ['x', 'y', 'z'] },
      rotation: { type: 'object', additionalProperties: false, properties: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } } },
      scale: { type: 'number', minimum: 0.05, maximum: 20 },
      intensity: { type: 'number', minimum: 0, maximum: 2 },
      color: { type: 'string', pattern: '^#[0-9a-fA-F]{6}$' },
      seed: { type: 'integer', minimum: 1, maximum: 1000000 },
      sound: { type: 'boolean' },
      volume: { type: 'number', minimum: 0, maximum: 1 },
      anchor: { type: 'object', additionalProperties: false, properties: {
        slotId: { type: 'string', maxLength: 160 },
        offset: { type: 'object', additionalProperties: false, properties: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } } },
      }, required: ['slotId'] },
      target: { type: 'object', additionalProperties: false, properties: {
        slotId: { type: 'string', maxLength: 160 },
        offset: { type: 'object', additionalProperties: false, properties: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } } },
      }, required: ['slotId'] },
      targetPosition: { type: 'object', additionalProperties: false, properties: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } }, required: ['x', 'y', 'z'] },
      sourceUrl: { type: 'string', maxLength: 2000 },
    },
    required: ['id', 'kind', 'start', 'end'],
  },
} as const
