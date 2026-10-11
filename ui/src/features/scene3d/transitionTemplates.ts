import { createDefaultScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { parseScreenBackdrop } from './screenBackdrop.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import { parseWorldSfx } from '../sceneFx/world.ts'
import { TRANSITION_TEMPLATE_IDS, type TransitionTemplateId } from './transitionTemplateIds.ts'
import type { KineticText } from '../../lib/kineticText.ts'
import type {
  Scene3DCamera,
  Scene3DCameraFamily,
  Scene3DDocument,
  Scene3DLight,
  Scene3DSlot,
  Scene3DSlotId,
  Vec3,
} from './types.ts'

export { TRANSITION_TEMPLATE_IDS, type TransitionTemplateId }

export type TransitionOrientation = 'horizontal' | 'vertical'
export type TransitionApplyOptions = {
  orientation?: TransitionOrientation
  /** Source URLs by slot id, alias or role. */
  roles?: Partial<Record<string, string>>
  /** A title over the shot; only the eyecatch draws one, and only when this is given. */
  text?: string
}
export type TransitionCardCopy = { title: string; description: string; requirements: string[] }

type TransitionSpec = {
  duration: number
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  backdrop: { color: string; sfx: Array<Record<string, unknown>> }
  worldSfx: Array<Record<string, unknown>>
  sfx: Array<Record<string, unknown>>
  title?: Omit<KineticText, 'text'>
  copy: { en: TransitionCardCopy; es: TransitionCardCopy }
}

const PI = Math.PI
/** Flash frames are counted at 24 fps, like the anime shots. */
const FPS = 24
const frames = (count: number) => count / FPS
/** A full-body cutout this size is about 1.9 m tall; a GLB in the same slot is fitted to 1.6 m. */
const FIGURE = 0.95

const cutout = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'image', surface: 'cutout', imageLook: { unlit: true }, sourceUrl: '', clip: null,
  position, rotationY: 0, scale: FIGURE, ...patch,
})
const model = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'model3d', sourceUrl: '', clip: null, position, rotationY: 0, scale: 1, ...patch,
})
const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
const KEY: Scene3DLight = { kind: 'directional', direction: [-0.35, -0.85, -0.4], intensity: 1.5, color: '#fff6ea' }
const copy = (en: TransitionCardCopy, es: TransitionCardCopy) => ({ en, es })
const lines = (id: string, start: number, end: number, color: string, patch: Record<string, unknown> = {}) => (
  { id, kind: 'speedlines', start, end, x: 50, y: 46, size: 150, intensity: 1.4, color, ...patch }
)
/** The iris closes in steps: each window darkens further in than the one before (size 100 reaches the centre). */
const iris = (id: string, start: number, end: number, size: number, intensity: number) => (
  { id, kind: 'vignette', start, end, x: 50, y: 50, size, intensity, color: '#000000' }
)

const CUTOUT_EN = 'Image cutout or GLB (subject, optional)'
const CUTOUT_ES = 'Recorte de imagen o GLB (protagonista, opcional)'
const PLAIN_EN = 'No background slot: a flat colour backdrop'
const PLAIN_ES = 'Sin hueco de fondo: un fondo de color plano'

const SPECS: Record<TransitionTemplateId, TransitionSpec> = {
  'transition-whip-pan': {
    duration: 0.7, light: KEY,
    // Equal eye distances at both ends, so the move reads as a slide with a roll and not as a push.
    camera: cam('establishment', [0, 1.5, 2.5], [0, 1.4, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [-2, -0.25, 1.42], to: [0, -0.25, 2.45], lookFrom: [-1.3, -0.3, 0], lookTo: [0, -0.3, 0],
        rollFrom: -9, rollTo: 0, moveStart: 0, moveEnd: 0.75, ease: 'snap',
      },
      shake: [{ start: 0.5, end: 0.7, amplitude: 0.02, frequency: 22, seed: 5, decay: 9 }],
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#2a2f3a', sfx: [lines('whip-lines', 0, 0.7, '#dfe4ee', { intensity: 1.6, size: 160, seed: 3 })] },
    worldSfx: [],
    sfx: [],
    copy: copy(
      { title: 'Whip pan', description: 'A very fast slide with a roll over radial speed lines; the camera lands centred on the figure with a short settle.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Barrido (whip pan)', description: 'Deslizamiento muy rápido con balanceo sobre líneas de velocidad radiales; la cámara aterriza centrada en la figura con un pequeño asentamiento.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-iris-in': {
    duration: 1.2, light: KEY,
    camera: cam('establishment', [0, 1.5, 3.2], [0, 1.4, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.12, 3.2], to: [0, -0.06, 1.2], lookFrom: [0, -0.3, 0], lookTo: [0, -0.12, 0],
        moveStart: 0.05, moveEnd: 0.7, ease: 'snap',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#07080c', sfx: [] },
    worldSfx: [],
    sfx: [iris('iris-1', 0, 0.35, 45, 1.4), iris('iris-2', 0.35, 0.65, 70, 1.6), iris('iris-3', 0.65, 0.9, 90, 1.8), iris('iris-4', 0.9, 1.2, 100, 2)],
    copy: copy(
      { title: 'Iris in', description: 'A fast push to the centre while a vignette closes in four steps over a dark backdrop.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Iris de entrada', description: 'Empuje rápido hacia el centro mientras una viñeta se cierra en cuatro pasos sobre un fondo oscuro.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-flash-white': {
    duration: 0.6, light: KEY,
    camera: cam('establishment', [0, 1.5, 1.7], [0, 1.45, 0], 36, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.08, 1.7], to: [0, -0.04, 1.15], lookFrom: [0, -0.12, 0], lookTo: [0, -0.08, 0],
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#efece6', sfx: [] },
    worldSfx: [],
    sfx: [
      { id: 'flash-1', kind: 'impact_flash', start: 0.2, end: 0.2 + frames(3), x: 50, y: 45, size: 90, color: '#ffffff' },
      { id: 'flash-2', kind: 'impact_flash', start: 0.45, end: 0.45 + frames(2), x: 50, y: 45, size: 90, color: '#ffffff' },
    ],
    copy: copy(
      { title: 'Flash to white', description: 'Three white frames, then two more, over a tight push on the face; plain colours, no ink lines.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Destello a blanco', description: 'Tres fotogramas blancos y luego dos más sobre un empuje corto a la cara; colores planos, sin líneas de tinta.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-wipe-prop': {
    duration: 1.5, light: KEY,
    camera: cam('fixed', [0, 1.25, 4.2], [0, 1.05, 0], 40),
    // 0.8 m in front of the lens the frame is 0.58 × 1.03 m, so a prop fitted to 2.55 m covers it at x = 0.
    slots: [
      cutout('subject', 'subject_1', [0, 0, 0]),
      model('wipe', 'prop', [-3.6, 0, 3.4], { scale: 1.5, motion: { to: [3.6, 0, 3.4], easing: 'linear' } }),
    ],
    aliases: { subject: 'subject', wipe: 'wipe' },
    backdrop: { color: '#1b1e26', sfx: [] },
    worldSfx: [
      { id: 'wake', kind: 'dust', start: 0, end: 1.5, position: { x: 0, y: 0.1, z: 3.4 }, scale: 0.8, color: '#8a8f9c', anchor: { slotId: 'wipe', offset: { x: -0.6, y: 0.2, z: 0 } } },
    ],
    sfx: [],
    copy: copy(
      { title: 'Prop wipe', description: 'A prop crosses the frame left to right close to the lens and covers it at mid-shot: a door, a bus, a cloud. It keeps facing the camera; turn it if its wide side is elsewhere.', requirements: ['GLB prop that crosses (wipe, role prop)', CUTOUT_EN, PLAIN_EN] },
      { title: 'Cortinilla con objeto', description: 'Un objeto cruza el encuadre de izquierda a derecha pegado al objetivo y lo cubre a mitad del plano: una puerta, un autobús, una nube. Mira a cámara; gíralo si su lado ancho está en otro eje.', requirements: ['GLB que cruza (wipe, papel prop)', CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-match-shape': {
    duration: 2, light: KEY,
    camera: cam('establishment', [0, 1.5, 1.1], [0, 1.45, 0], 36, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.05, 1.1], to: [0, -0.05, 3.4], lookFrom: [0, -0.05, 0], lookTo: [0, -0.3, 0],
        moveStart: 0.55, moveEnd: 0.8, ease: 'snap',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#dcd6c8', sfx: [] },
    worldSfx: [],
    sfx: [
      { id: 'hold-vignette', kind: 'vignette', start: 0, end: 1.1, x: 50, y: 50, size: 60, intensity: 1.2, color: '#000000' },
      lines('snap-lines', 1.1, 1.6, '#ffffff', { intensity: 0.8, size: 120 }),
    ],
    copy: copy(
      { title: 'Match on shape', description: 'A centred close frame holds for a second, then snaps out to the whole figure: the shape a match cut lands on.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Raccord de forma', description: 'Un primer plano centrado aguanta un segundo y luego se abre de golpe hasta la figura entera: la forma en la que aterriza un raccord.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-eyecatch': {
    duration: 2.5, light: KEY,
    camera: cam('fixed', [0, 1.15, 4.4], [0, 1, 0], 40),
    // The card is read at the start position: from 4.2 m back the figure is still a whole figure, not a far one.
    slots: [cutout('subject', 'subject_1', [0, 0, -4.2], { motion: { to: [0, 0, 0.8], turnTo: PI * 3, easing: 'smooth' } })],
    aliases: { subject: 'subject' },
    backdrop: { color: '#22262e', sfx: [lines('card-lines', 0, 2.5, '#e9ebf0', { intensity: 2, size: 170, y: 50, seed: 7 })] },
    worldSfx: [],
    sfx: [],
    title: { id: 'eyecatch-title', start: 1.5, end: 2.5, preset: 'impact', x: 50, y: 86, size: 9, color: '#f4f5f7', rotation: 0, font: 'condensed', weight: 700, uppercase: true, letterSpacing: 0.08 },
    copy: copy(
      { title: 'Eyecatch (plain)', description: 'A scene-change card in two plain tones: the figure spins in from the distance over focus lines, and an optional title lands under it.', requirements: [CUTOUT_EN, 'Optional title text', PLAIN_EN] },
      { title: 'Cortinilla (plana)', description: 'Cortinilla de cambio de escena en dos tonos planos: la figura llega girando desde el fondo sobre líneas de concentración y un título opcional aterriza debajo.', requirements: [CUTOUT_ES, 'Texto de título opcional', PLAIN_ES] },
    ),
  },
  'transition-smash-in': {
    duration: 0.6, light: KEY,
    camera: cam('establishment', [0, 1.5, 4.4], [0, 1.4, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.1, 4.4], to: [0, -0.04, 1], lookFrom: [0, -0.5, 0], lookTo: [0, -0.06, 0],
        moveStart: 0.3, moveEnd: 0.5, ease: 'snap',
      },
      shake: [{ start: 0.3, end: 0.6, amplitude: 0.06, frequency: 20, seed: 3, decay: 6 }],
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#101218', sfx: [] },
    worldSfx: [],
    sfx: [lines('smash-lines', 0.3, 0.5, '#ffffff', { size: 140 })],
    copy: copy(
      { title: 'Smash in', description: 'An abrupt snap from the whole figure to the face in a fifth of a second, with a burst of lines and a shake that dies away.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Entrada a golpe', description: 'Salto brusco de la figura entera a la cara en una quinta parte de segundo, con una ráfaga de líneas y una sacudida que se apaga.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
  'transition-rise-off': {
    duration: 2, light: KEY,
    camera: cam('establishment', [0, 1.5, 2.8], [0, 1.4, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.1, 2.8], to: [0, 2.2, 2.8], lookFrom: [0, -0.2, 0], lookTo: [0, 2.6, 0],
        moveStart: 0.1, moveEnd: 1, ease: 'smooth',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#9fb4c8', sfx: [] },
    worldSfx: [],
    sfx: [{ id: 'top-light', kind: 'light_rays', start: 0, end: 2, x: 50, y: 0, size: 140, rotation: 90, intensity: 0.7, color: '#ffffff' }],
    copy: copy(
      { title: 'Rise off', description: 'The camera lifts off the figure into a blank backdrop with soft light from above; the next shot can start on anything.', requirements: [CUTOUT_EN, PLAIN_EN] },
      { title: 'Elevación de salida', description: 'La cámara se eleva desde la figura hacia un fondo vacío con luz suave desde arriba; el siguiente plano puede empezar en cualquier cosa.', requirements: [CUTOUT_ES, PLAIN_ES] },
    ),
  },
}

export function isTransitionTemplateId(id: string): id is TransitionTemplateId {
  return (TRANSITION_TEMPLATE_IDS as readonly string[]).includes(id)
}

function uniqueRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  return [...new Set(slots.map(slot => slot.slot))]
}

export const TRANSITION_TEMPLATES = TRANSITION_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
  tags: ['transition'] as const,
}))

export const TRANSITION_CATEGORIES = Object.fromEntries(
  TRANSITION_TEMPLATE_IDS.map(id => [id, 'cinema']),
) as Record<TransitionTemplateId, 'cinema'>

function bindSlot(slot: Scene3DSlot, roles: TransitionApplyOptions['roles'], aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const alias = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const url = roles[slot.id] ?? (alias ? roles[alias] : undefined) ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

function buildDocument(spec: TransitionSpec, id: TransitionTemplateId, options: TransitionApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.fps = FPS
  doc.width = vertical ? 1080 : 1920
  doc.height = vertical ? 1920 : 1080
  doc.environment = { reflectiveFloor: false, platform: false, bloom: 0.12, floorStyle: 'none' }
  // Flat colours: a neutral curve at 0 EV keeps backdrop and cutout colours as authored.
  doc.look = { toneMapping: 'neutral', exposure: 0 }
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = adaptAuthoredCameraToFrame(structuredClone(spec.camera), doc.width, doc.height)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  doc.screenBackdrop = parseScreenBackdrop(spec.backdrop)
  const worldSfx = parseWorldSfx(spec.worldSfx)
  if (worldSfx.length) doc.worldSfx = worldSfx
  doc.sfx = parseSceneFx(spec.sfx)
  if (spec.title && options.text) doc.texts = [{ ...spec.title, text: options.text }]
  return doc
}

export function applyTransitionTemplate(id: string, options: TransitionApplyOptions = {}): Scene3DDocument | null {
  if (!isTransitionTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function transitionTemplateDocument(id: string): Scene3DDocument | null {
  return applyTransitionTemplate(id)
}

export function transitionCard(id: string, locale: 'en' | 'es' = 'en'): TransitionCardCopy | undefined {
  if (!isTransitionTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

/** The authored cue kinds before parsing, so a check can prove none was dropped as unknown. */
export function transitionAuthoredCueKinds(id: string): { sfx: string[]; worldSfx: string[]; backdrop: string[] } {
  if (!isTransitionTemplateId(id)) return { sfx: [], worldSfx: [], backdrop: [] }
  const kinds = (cues: Array<Record<string, unknown>>) => cues.map(cue => String(cue.kind))
  return { sfx: kinds(SPECS[id].sfx), worldSfx: kinds(SPECS[id].worldSfx), backdrop: kinds(SPECS[id].backdrop.sfx) }
}

export function transitionAliases(id: string): Record<string, string> {
  return isTransitionTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
