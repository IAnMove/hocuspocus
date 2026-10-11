import { createDefaultScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { parseScreenBackdrop } from './screenBackdrop.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import { parseWorldSfx } from '../sceneFx/world.ts'
import { SPEED_TEMPLATE_IDS, type SpeedTemplateId } from './speedTemplateIds.ts'
import type {
  Scene3DCamera,
  Scene3DCameraFamily,
  Scene3DDocument,
  Scene3DLight,
  Scene3DSlot,
  Scene3DSlotId,
  Vec3,
} from './types.ts'

export { SPEED_TEMPLATE_IDS, type SpeedTemplateId }

export type SpeedOrientation = 'horizontal' | 'vertical'
export type SpeedApplyOptions = {
  orientation?: SpeedOrientation
  /** Source URLs by slot id, alias or role. */
  roles?: Partial<Record<string, string>>
}
export type SpeedCardCopy = { title: string; description: string; requirements: string[] }

type SpeedSpec = {
  duration: number
  dressing?: Scene3DDocument['dressing']
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  backdrop: { color: string; sfx: Array<Record<string, unknown>> }
  worldSfx: Array<Record<string, unknown>>
  sfx: Array<Record<string, unknown>>
  copy: { en: SpeedCardCopy; es: SpeedCardCopy }
}

const PI = Math.PI
const FPS = 24

const model = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'model3d', sourceUrl: '', clip: null, position, rotationY: 0, scale: 1, ...patch,
})
/** The painted set: an environment plate under the backdrop effects, so a `world` or a Qwen set can take over. */
const plate = (): Scene3DSlot => ({
  id: 'background', slot: 'background', media: 'image', surface: 'environment', sourceUrl: '', clip: null,
  position: [0, 0, -12], rotationY: 0, scale: 1,
})
const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
const light = (direction: Vec3, intensity: number, color: string): Scene3DLight => (
  { kind: 'directional', direction, intensity, color }
)
const KEY = light([-0.35, -0.85, -0.4], 1.6, '#fff4e5')
const copy = (en: SpeedCardCopy, es: SpeedCardCopy) => ({ en, es })
const lines = (id: string, start: number, end: number, color: string, patch: Record<string, unknown> = {}) => (
  { id, kind: 'speedlines', start, end, x: 50, y: 46, size: 150, intensity: 1.4, color, ...patch }
)
const footDust = (id: string, slotId: string, end: number) => (
  { id, kind: 'dust', start: 0, end, position: { x: 0, y: 0.05, z: 0 }, scale: 1.1, color: '#b9a98c', anchor: { slotId } }
)

const PLATE_EN = 'Optional background image (environment plate under the effects)'
const PLATE_ES = 'Imagen de fondo opcional (plano de entorno bajo los efectos)'

const SPECS: Record<SpeedTemplateId, SpeedSpec> = {
  'speed-run-toward': {
    duration: 6, dressing: 'treadmill', light: KEY,
    // Head anchor minus one metre: the lens sits at knee height and creeps in while the clip runs on the spot.
    camera: cam('establishment', [0, 0.5, 4.8], [0, 0.9, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -1, 4.8], to: [0, -0.94, 3.6], lookFrom: [0, -0.7, 0], lookTo: [0, -0.6, 0], ease: 'smooth',
      },
    }),
    slots: [model('subject', 'subject_1', [0, 0, 0]), plate()],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#1d2230', sfx: [lines('run-lines', 0, 6, '#aab4c8', { intensity: 0.6, y: 48, seed: 5 })] },
    worldSfx: [footDust('run-dust', 'subject', 6)],
    sfx: [],
    copy: copy(
      { title: 'Run toward camera', description: 'A low lens creeps in on a figure running on the spot over faint radial speed lines. The template brings no clip: bind a GLB with a run clip (clip: run).', requirements: ['GLB with a run clip (subject; the cast brings clip: run)', PLATE_EN] },
      { title: 'Carrera hacia cámara', description: 'Un objetivo bajo avanza despacio hacia una figura que corre sin desplazarse sobre líneas de velocidad tenues. La plantilla no trae clip: asigna un GLB con clip de carrera (clip: run).', requirements: ['GLB con clip de carrera (protagonista; el reparto trae clip: run)', PLATE_ES] },
    ),
  },
  'speed-foot-chase': {
    duration: 7, dressing: 'chase-street', light: light([-0.15, -0.65, 0.55], 1.9, '#ffe6c8'),
    camera: cam('follow', [0, 1.5, 4.5], [0, 1.1, 0], 40, {
      eyeOffset: [0.9, 0.45, 4.6], targetOffset: [0.5, -0.15, 0],
      shake: [{ start: 4.2, end: 5.6, amplitude: 0.03, frequency: 9, seed: 11, decay: 1.5 }],
    }),
    slots: [
      model('runner', 'subject_1', [-7, 0, 0.6], { rotationY: PI / 2, motion: { to: [7, 0, 0.6], faceTravel: true, easing: 'linear' } }),
      model('chaser', 'subject_2', [-10.5, 0, -1], { rotationY: PI / 2, scale: 0.98, motion: { to: [3.8, 0, -1], faceTravel: true, easing: 'linear' } }),
      plate(),
    ],
    aliases: { runner: 'runner', chaser: 'chaser', background: 'background' },
    backdrop: { color: '#2b2f3a', sfx: [] },
    worldSfx: [footDust('runner-dust', 'runner', 7), footDust('chaser-dust', 'chaser', 7)],
    sfx: [],
    copy: copy(
      { title: 'Foot chase', description: 'Two figures sprint down the street on parallel lanes; the camera tracks the runner from ahead and shakes lightly as the chaser closes in.', requirements: ['GLB with a run clip (runner)', 'GLB with a run clip (chaser)', PLATE_EN] },
      { title: 'Persecución a pie', description: 'Dos figuras esprintan por la calle en carriles paralelos; la cámara sigue al que huye desde delante y tiembla un poco cuando el perseguidor se acerca.', requirements: ['GLB con clip de carrera (runner)', 'GLB con clip de carrera (chaser)', PLATE_ES] },
    ),
  },
  'speed-flyby': {
    duration: 6, light: light([-0.45, -0.7, -0.35], 2.1, '#fff1d6'),
    // The look sweeps across the sky above a watcher's head while the eye trucks 0.8 m: a pan that reads as one.
    camera: cam('establishment', [0, 1.6, 7], [0, 2.5, -4], 42, {
      framing: {
        targetSlot: 'watcher', anchor: 'head', relativeToFacing: false,
        from: [-0.4, 0.3, 7], to: [0.4, 0.3, 7], lookFrom: [-4, 2.4, -6], lookTo: [4, 2.6, -6], ease: 'smooth',
      },
    }),
    slots: [
      model('watcher', 'subject_1', [0, 0, 0]),
      model('craft', 'prop', [-16, 4.2, -6], { rotationY: PI / 2, scale: 1.6, motion: { to: [16, 4.6, -6], faceTravel: true, easing: 'linear' } }),
      plate(),
    ],
    aliases: { watcher: 'watcher', craft: 'craft', background: 'background' },
    backdrop: { color: '#78aee0', sfx: [] },
    worldSfx: [
      { id: 'contrail', kind: 'smoke', start: 0.2, end: 6, position: { x: -16, y: 4, z: -6 }, scale: 0.8, color: '#ffffff', anchor: { slotId: 'craft', offset: { x: 0, y: -0.2, z: 0 } } },
    ],
    sfx: [],
    copy: copy(
      { title: 'Fly-by', description: 'A craft crosses the sky from left to right, 32 m in six seconds, trailing smoke; the camera pans with it over the head of a figure on the ground.', requirements: ['GLB craft or vehicle (craft, role prop)', 'GLB figure that watches (watcher, optional)', PLATE_EN] },
      { title: 'Pasada en vuelo', description: 'Una nave cruza el cielo de izquierda a derecha, 32 m en seis segundos, dejando humo; la cámara panea con ella por encima de una figura en el suelo.', requirements: ['GLB de nave o vehículo (craft, papel prop)', 'GLB que mira (watcher, opcional)', PLATE_ES] },
    ),
  },
  'speed-rush-lines': {
    duration: 5, light: KEY,
    camera: cam('establishment', [0, 1.5, 2.5], [0, 1.4, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.16, 2.5], to: [0, -0.1, 0.95], lookFrom: [0, -0.2, 0], lookTo: [0, -0.12, 0],
        moveStart: 0.25, moveEnd: 0.55, ease: 'snap',
      },
      shake: [{ start: 2.75, end: 3.5, amplitude: 0.05, frequency: 18, seed: 9, decay: 4 }],
    }),
    slots: [model('subject', 'subject_1', [0, 0, 0]), plate()],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#1a1d26', sfx: [lines('rush-lines', 0, 5, '#d9dde8', { intensity: 1.6, size: 160, y: 44, seed: 9 })] },
    worldSfx: [],
    sfx: [],
    copy: copy(
      { title: 'Rush lines', description: 'A hard push from a medium shot to the face over radial speed lines; the camera shakes where the push lands.', requirements: ['GLB figure (subject)', PLATE_EN] },
      { title: 'Líneas de embestida', description: 'Empuje duro de plano medio a la cara sobre líneas de velocidad radiales; la cámara tiembla donde aterriza el empuje.', requirements: ['GLB de figura (protagonista)', PLATE_ES] },
    ),
  },
  'speed-side-dash': {
    duration: 5, light: KEY,
    // The frame is tied to the figure and slides from its left to its right, so the dash crosses the picture.
    camera: cam('side', [0, 1.2, 3.8], [0, 1, 0], 40, {
      eyeOffset: [0, -0.2, 3.9],
      framing: {
        targetSlot: 'subject', anchor: 'center', relativeToFacing: false,
        from: [-1.6, 0.05, 3.9], to: [1.6, 0.05, 3.9], lookFrom: [-1, 0, 0], lookTo: [1, 0, 0],
        moveStart: 0.2, moveEnd: 0.65, ease: 'snap',
      },
    }),
    slots: [
      model('subject', 'subject_1', [-5, 0, 0], { rotationY: PI / 2, motion: { to: [5, 0, 0], faceTravel: true, easing: 'linear' } }),
      plate(),
    ],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#232733', sfx: [] },
    worldSfx: [footDust('dash-dust', 'subject', 5)],
    sfx: [lines('dash-lines', 1, 3.5, '#ffffff', { intensity: 0.7, size: 130 })],
    copy: copy(
      { title: 'Side dash', description: 'Seen from the side, the figure dashes ten metres across the set while the frame slides fast from one side of it to the other.', requirements: ['GLB with a run clip (subject)', PLATE_EN] },
      { title: 'Carrera lateral', description: 'Visto de lado, la figura cruza diez metros del decorado a la carrera mientras el encuadre se desliza rápido de un lado a otro de ella.', requirements: ['GLB con clip de carrera (protagonista)', PLATE_ES] },
    ),
  },
}

export function isSpeedTemplateId(id: string): id is SpeedTemplateId {
  return (SPEED_TEMPLATE_IDS as readonly string[]).includes(id)
}

function uniqueRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  return [...new Set(slots.map(slot => slot.slot))]
}

export const SPEED_TEMPLATES = SPEED_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
}))

export const SPEED_CATEGORIES = Object.fromEntries(
  SPEED_TEMPLATE_IDS.map(id => [id, 'action']),
) as Record<SpeedTemplateId, 'action'>

function bindSlot(slot: Scene3DSlot, roles: SpeedApplyOptions['roles'], aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const alias = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const url = roles[slot.id] ?? (alias ? roles[alias] : undefined) ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

function buildDocument(spec: SpeedSpec, id: SpeedTemplateId, options: SpeedApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.fps = FPS
  doc.width = vertical ? 1080 : 1920
  doc.height = vertical ? 1920 : 1080
  doc.dressing = spec.dressing
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = adaptAuthoredCameraToFrame(structuredClone(spec.camera), doc.width, doc.height)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  doc.screenBackdrop = parseScreenBackdrop(spec.backdrop)
  const worldSfx = parseWorldSfx(spec.worldSfx)
  if (worldSfx.length) doc.worldSfx = worldSfx
  doc.sfx = parseSceneFx(spec.sfx)
  return doc
}

export function applySpeedTemplate(id: string, options: SpeedApplyOptions = {}): Scene3DDocument | null {
  if (!isSpeedTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function speedTemplateDocument(id: string): Scene3DDocument | null {
  return applySpeedTemplate(id)
}

export function speedCard(id: string, locale: 'en' | 'es' = 'en'): SpeedCardCopy | undefined {
  if (!isSpeedTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

/** The authored cue kinds before parsing, so a check can prove none was dropped as unknown. */
export function speedAuthoredCueKinds(id: string): { sfx: string[]; worldSfx: string[]; backdrop: string[] } {
  if (!isSpeedTemplateId(id)) return { sfx: [], worldSfx: [], backdrop: [] }
  const kinds = (cues: Array<Record<string, unknown>>) => cues.map(cue => String(cue.kind))
  return { sfx: kinds(SPECS[id].sfx), worldSfx: kinds(SPECS[id].worldSfx), backdrop: kinds(SPECS[id].backdrop.sfx) }
}

export function speedAliases(id: string): Record<string, string> {
  return isSpeedTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
