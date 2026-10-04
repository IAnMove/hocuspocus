import rawCatalog from './cinematicTechniques.json' with { type: 'json' }
import { createDefaultScene3DDocument } from './document'
import { toPortraitCamera } from './frameFormat'
import { TECHNIQUE_TEMPLATE_IDS, type TechniqueTemplateId } from './techniqueTemplateIds'
import type { Scene3DDocument, Scene3DDressing, Scene3DFraming, Scene3DSlot, Scene3DSlotId, Vec3 } from './types'
import { parseWorldSfx, type WorldSfxKind } from '../sceneFx/world'

type TechniqueEntry = {
  id: TechniqueTemplateId
  fov: number
  duration: number
  anchor: Scene3DFraming['anchor']
  from: Vec3
  to: Vec3
  light: { direction: Vec3; intensity: number; color: string }
  dressing: Scene3DDressing
  slots: Scene3DSlotId[]
  fovTo?: number
  orbitTurns?: number
  rollFrom?: number
  rollTo?: number
  lookFrom?: Vec3
  lookTo?: Vec3
  layout?: Partial<Record<Scene3DSlotId, Vec3>>
  scales?: Partial<Record<Scene3DSlotId, number>>
  yaw?: Partial<Record<Scene3DSlotId, number>>
  motion?: { to: Vec3; faceTravel: boolean }
  world?: { kind: WorldSfxKind; color: string; scale: number; intensity: number }
  playbackSpeed?: number
  portrait?: boolean
  n64?: boolean
  mirror?: boolean
}

const CATALOG = rawCatalog as unknown as readonly TechniqueEntry[]
const BY_ID = new Map(CATALOG.map(entry => [entry.id, entry]))

function entryOf(id: TechniqueTemplateId): TechniqueEntry {
  const entry = BY_ID.get(id)
  if (!entry) throw new Error(`missing technique ${id}`)
  return entry
}

export const TECHNIQUE_TEMPLATES = TECHNIQUE_TEMPLATE_IDS.map(id => {
  const entry = entryOf(id)
  return {
    id,
    camera: 'follow' as const,
    duration: entry.duration,
    slots: entry.slots,
    ...(entry.portrait ? { frameFormat: 'portrait' as const } : {}),
  }
})

export const TECHNIQUE_CATEGORIES = Object.fromEntries(
  TECHNIQUE_TEMPLATE_IDS.map(id => [id, 'cinema']),
) as Record<TechniqueTemplateId, 'cinema'>

function place(entry: TechniqueEntry, id: Scene3DSlotId, index: number): Vec3 {
  const laid = entry.layout?.[id]
  if (laid) return laid
  if (id === 'background') return [0, 1, -7]
  return [index * 1.15, 0, 0]
}

function moved(entry: TechniqueEntry, id: Scene3DSlotId, position: Vec3): Scene3DSlot['motion'] {
  const motion = entry.motion
  if (!motion || id === 'background') return undefined
  const origin = entry.layout?.subject_1 ?? [0, 0, 0]
  const to = position.map((value, index) => value + motion.to[index] - origin[index]) as unknown as Vec3
  return { to, faceTravel: motion.faceTravel }
}

function modelSlot(entry: TechniqueEntry, id: Scene3DSlotId, index: number): Scene3DSlot {
  const position = place(entry, id, index)
  const motion = moved(entry, id, position)
  return {
    id,
    slot: id,
    media: id === 'background' ? 'image' : 'model3d',
    sourceUrl: '',
    clip: null,
    position,
    rotationY: entry.yaw?.[id] ?? 0,
    scale: entry.scales?.[id] ?? 1,
    ...(id === 'background' ? { loop: { cylinder: true, speed: 0 } } : {}),
    ...(motion ? { motion } : {}),
  }
}

function framingOf(entry: TechniqueEntry): Scene3DFraming {
  const framing: Scene3DFraming = {
    targetSlot: 'subject_1',
    anchor: entry.anchor,
    from: entry.from,
    to: entry.to,
  }
  if (entry.fovTo != null) {
    framing.fovFrom = entry.fov
    framing.fovTo = entry.fovTo
  }
  if (entry.orbitTurns != null) framing.orbitTurns = entry.orbitTurns
  if (entry.rollFrom != null) framing.rollFrom = entry.rollFrom
  if (entry.rollTo != null) framing.rollTo = entry.rollTo
  if (entry.lookFrom) framing.lookFrom = entry.lookFrom
  if (entry.lookTo) framing.lookTo = entry.lookTo
  return framing
}

function cameraOf(entry: TechniqueEntry): Scene3DDocument['camera'] {
  const camera = {
    family: 'follow' as const,
    eye: [0, 2, 5] as Vec3,
    look: [0, 1, 0] as Vec3,
    fov: entry.fov,
    framing: framingOf(entry),
  }
  return entry.portrait ? toPortraitCamera(camera) : camera
}

function applyExtras(doc: Scene3DDocument, entry: TechniqueEntry) {
  if (entry.playbackSpeed != null) doc.playbackSpeed = entry.playbackSpeed
  if (entry.n64) doc.renderLook = 'n64'
  if (entry.mirror) doc.environment = { reflectiveFloor: true, platform: false, bloom: 0.48, floorStyle: 'mirror' }
  if (entry.portrait) {
    doc.width = 720
    doc.height = 1280
  }
  if (!entry.world) return
  doc.worldSfx = parseWorldSfx([{
    id: `${entry.id}-world`,
    kind: entry.world.kind,
    color: entry.world.color,
    scale: entry.world.scale,
    intensity: entry.world.intensity,
    start: 0,
    end: entry.duration,
  }])
}

export function techniqueDocument(id: string): Scene3DDocument | null {
  const entry = BY_ID.get(id as TechniqueTemplateId)
  if (!entry) return null
  const doc = createDefaultScene3DDocument()
  doc.templateId = entry.id
  doc.duration = entry.duration
  doc.dressing = entry.dressing
  doc.slots = entry.slots.map((slot, index) => modelSlot(entry, slot, index))
  doc.camera = cameraOf(entry)
  doc.light = { kind: 'directional', direction: entry.light.direction, intensity: entry.light.intensity, color: entry.light.color }
  applyExtras(doc, entry)
  return doc
}
