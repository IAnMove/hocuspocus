import { createDefaultScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { parseScreenBackdrop } from './screenBackdrop.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import type {
  Scene3DCamera,
  Scene3DCameraFamily,
  Scene3DDocument,
  Scene3DFraming,
  Scene3DLight,
  Scene3DSlot,
  Scene3DSlotId,
  Scene3DTemplateId,
  Vec3,
} from './types.ts'

/** What the dialogue, reaction and group packs share: a spec authored for models with a `background`
 * plate so a world or a painted set can take over, bound by slot id, alias, id family or role. */
export type CastPackCardCopy = { title: string; description: string; requirements: string[] }
export type CastPackApplyOptions = {
  orientation?: 'horizontal' | 'vertical'
  /** Source URLs by slot id, alias, id family (`person` binds every `person_N`) or role. */
  roles?: Partial<Record<string, string>>
}
export type CastPackSpec = {
  category: 'cinema' | 'music'
  duration: number
  dressing?: Scene3DDocument['dressing']
  environment?: Scene3DDocument['environment']
  look?: Scene3DDocument['look']
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  /** A flat colour behind the set; only the plain-colour cards paint one. */
  backdrop?: { color: string; sfx: Array<Record<string, unknown>> }
  sfx?: Array<Record<string, unknown>>
  copy: { en: CastPackCardCopy; es: CastPackCardCopy }
}
export type CastPackRow<Id extends Scene3DTemplateId> = { id: Id; camera: Scene3DCameraFamily; duration: number; slots: Scene3DSlotId[] }

/** Impact frames are counted at the document's default rate. */
export const CAST_PACK_FPS = createDefaultScene3DDocument().fps
/** A full-body cutout this size is about 1.9 m tall; a GLB in the same slot is fitted to 1.6 m. */
export const CAST_FIGURE = 0.95

export const model = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'model3d', sourceUrl: '', clip: null, position, rotationY: 0, scale: 1, ...patch,
})
/** A prop slot that stands for a person, so a production can bind a GLB to it. */
export const person = (id: string, position: Vec3, rotationY = 0): Scene3DSlot => model(id, 'prop', position, { rotationY, grounded: true })
export const cutout = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'image', surface: 'cutout', imageLook: { unlit: true }, sourceUrl: '', clip: null,
  position, rotationY: 0, scale: CAST_FIGURE, ...patch,
})
/** Optional painted background: an environment plate drawn under the backdrop. */
export const plate = (): Scene3DSlot => ({
  id: 'background', slot: 'background', media: 'image', surface: 'environment', sourceUrl: '', clip: null,
  position: [0, 0, -12], rotationY: 0, scale: 1,
})
export const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
/** A camera on a figure's head, in world axes, that follows where the slot stands and never a clip's pose. */
export const headFraming = (targetSlot: string, from: Vec3, to: Vec3, patch: Partial<Scene3DFraming> = {}): Scene3DFraming => (
  { targetSlot, anchor: 'head', relativeToFacing: false, track: 'rest', from, to, ...patch }
)
export const light = (direction: Vec3, intensity: number, color: string): Scene3DLight => (
  { kind: 'directional', direction, intensity, color }
)
export const KEY = light([-0.35, -0.85, -0.4], 1.6, '#fff4e5')
export const copy = (en: CastPackCardCopy, es: CastPackCardCopy) => ({ en, es })
export const PLATE_EN = 'Optional background image (environment plate)'
export const PLATE_ES = 'Imagen de fondo opcional (plano de entorno)'
export const CAST_EN = 'GLB or image cutout'
export const CAST_ES = 'GLB o recorte de imagen'

export function castPackRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  return [...new Set(slots.map(slot => slot.slot))]
}

export function castPackRows<Id extends Scene3DTemplateId>(ids: readonly Id[], specs: Record<Id, CastPackSpec>): CastPackRow<Id>[] {
  return ids.map(id => ({ id, camera: specs[id].camera.family, duration: specs[id].duration, slots: castPackRoles(specs[id].slots) }))
}

export function castPackCategories<Id extends Scene3DTemplateId>(ids: readonly Id[], specs: Record<Id, CastPackSpec>): Record<Id, 'cinema' | 'music'> {
  return Object.fromEntries(ids.map(id => [id, specs[id].category])) as Record<Id, 'cinema' | 'music'>
}

function bindSlot(slot: Scene3DSlot, roles: CastPackApplyOptions['roles'], aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const alias = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const family = slot.id.replace(/_\d+$/, '')
  const url = roles[slot.id] ?? (alias ? roles[alias] : undefined) ?? roles[family] ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

export function buildCastPackDocument(spec: CastPackSpec, id: Scene3DTemplateId, options: CastPackApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.width = vertical ? 720 : 1280
  doc.height = vertical ? 1280 : 720
  doc.dressing = spec.dressing
  if (spec.environment) doc.environment = structuredClone(spec.environment)
  if (spec.look) doc.look = { ...spec.look }
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = adaptAuthoredCameraToFrame(structuredClone(spec.camera), doc.width, doc.height)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  if (spec.backdrop) doc.screenBackdrop = parseScreenBackdrop(spec.backdrop)
  doc.sfx = parseSceneFx(spec.sfx ?? [])
  return doc
}
