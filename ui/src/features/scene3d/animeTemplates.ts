import { createDefaultScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { parseScreenBackdrop } from './screenBackdrop.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import { parseWorldSfx } from '../sceneFx/world.ts'
import { ANIME_TEMPLATE_IDS, type AnimeTemplateId } from './animeTemplateIds.ts'
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

export { ANIME_TEMPLATE_IDS, type AnimeTemplateId }

export type AnimeOrientation = 'horizontal' | 'vertical'
export type AnimeApplyOptions = {
  orientation?: AnimeOrientation
  /** Source URLs by slot id, alias, id family (`vehicle` binds every `vehicle_N`) or role. */
  roles?: Partial<Record<string, string>>
  /** A title over the shot; only the eyecatch draws one, and only when this is given. */
  text?: string
}
export type AnimeCardCopy = { title: string; description: string; requirements: string[] }

type AnimeSpec = {
  category: 'action' | 'cinema'
  duration: number
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  backdrop: { color: string; sfx: Array<Record<string, unknown>> }
  worldSfx: Array<Record<string, unknown>>
  sfx: Array<Record<string, unknown>>
  title?: Omit<KineticText, 'text'>
  copy: { en: AnimeCardCopy; es: AnimeCardCopy }
}

const PI = Math.PI
/** Anime is shot on 24 fps; impact frames are counted in these frames. */
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
/** Optional painted background: an environment plate drawn under the backdrop effects. */
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
const copy = (en: AnimeCardCopy, es: AnimeCardCopy) => ({ en, es })
const focusLines = (id: string, start: number, end: number, color: string, patch: Record<string, unknown> = {}) => (
  { id, kind: 'speedlines', start, end, x: 50, y: 42, size: 150, intensity: 1.8, color, ...patch }
)
const cloud = (id: string, x: number, y: number, z: number, scale: number, end: number, intensity = 1) => (
  { id, kind: 'fog', start: 0, end, position: { x, y, z }, scale, intensity, color: '#ffffff' }
)

const IMPACT = 1.25
/** The rushes cover 6.1 m each with smoothstep easing and cross at x = 0 when 3p² − 2p³ = 4.2 / 6.1,
 * p ≈ 0.6285 of 4 s; frame 60 at 24 fps is within 3 cm of it. */
const CLASH = 2.5
const FACE_OFF_FLASH = 3.6

const PLATE_EN = 'Optional background image (environment plate under the speed lines)'
const PLATE_ES = 'Imagen de fondo opcional (plano de entorno bajo las líneas)'
const CUTOUT_EN = 'Image cutout or GLB'
const CUTOUT_ES = 'Recorte de imagen o GLB'

const SPECS: Record<AnimeTemplateId, AnimeSpec> = {
  'anime-speedline-charge': {
    category: 'action', duration: 4, light: KEY,
    camera: cam('establishment', [0, 1.5, 4.2], [0, 1.4, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.35, 3.6], to: [0, -0.06, 1.4], lookFrom: [0, -0.45, 0], lookTo: [0, -0.1, 0],
        fovFrom: 40, fovTo: 32, moveStart: 0.18, moveEnd: 0.55, ease: 'snap',
      },
      shake: [{ start: 2.2, end: 2.75, amplitude: 0.035, frequency: 16, seed: 3, decay: 5 }],
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0]), plate()],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#1c2f86', sfx: [focusLines('focus-lines', 0, 4, '#f2f6ff', { intensity: 2, seed: 11 })] },
    worldSfx: [
      { id: 'charge-aura', kind: 'anime_aura', start: 0.4, end: 4, position: { x: 0, y: 0.95, z: 0 }, scale: 1.1, color: '#9fd8ff', anchor: { slotId: 'subject' } },
    ],
    sfx: [],
    copy: copy(
      { title: 'Speed-line charge', description: 'One figure over animated focus lines; the camera snaps from a medium shot to the face and shakes as it lands.', requirements: [`${CUTOUT_EN} (subject)`, PLATE_EN] },
      { title: 'Carga con líneas de velocidad', description: 'Una figura sobre líneas de concentración animadas; la cámara salta de plano medio a la cara y tiembla al llegar.', requirements: [`${CUTOUT_ES} (protagonista)`, PLATE_ES] },
    ),
  },
  'anime-impact-frame': {
    category: 'action', duration: 3, light: KEY,
    camera: cam('establishment', [0, 1.2, 3], [0, 1.1, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.5, 2.5], to: [0, -0.42, 2.15], lookFrom: [0, -0.55, 0], lookTo: [0, -0.45, 0],
      },
      shake: [{ start: IMPACT, end: 2.6, amplitude: 0.09, frequency: 20, seed: 7, decay: 3.2 }],
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0]), plate()],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#251a3c', sfx: [focusLines('impact-lines', IMPACT, 2.6, '#ff9b6a', { intensity: 1.6, size: 140 })] },
    worldSfx: [],
    sfx: [
      { id: 'impact-negative', kind: 'impact_invert', start: IMPACT, end: IMPACT + frames(2), x: 50, y: 40, size: 70 },
      { id: 'impact-flash', kind: 'impact_flash', start: IMPACT + frames(2), end: IMPACT + frames(5), x: 50, y: 40, size: 70 },
      { id: 'impact-burst', kind: 'manga_impact', start: IMPACT + frames(5), end: 2.2, x: 50, y: 44, size: 85, color: '#ffe36c' },
    ],
    copy: copy(
      { title: 'Impact frame', description: 'A hit lands: two negative frames, three white frames with ink focus lines, a starburst and a camera shake that dies away.', requirements: [`${CUTOUT_EN} (subject)`, PLATE_EN] },
      { title: 'Fotograma de impacto', description: 'Llega el golpe: dos fotogramas en negativo, tres en blanco con líneas de tinta, un estallido y una sacudida que se apaga.', requirements: [`${CUTOUT_ES} (protagonista)`, PLATE_ES] },
    ),
  },
  'anime-snap-zoom': {
    category: 'action', duration: 2.5, light: KEY,
    camera: cam('establishment', [0, 1.1, 4.4], [0, 1, 0], 42, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.55, 3.9], to: [0, -0.04, 1], lookFrom: [0, -0.6, 0], lookTo: [0, -0.06, 0],
        fovFrom: 42, fovTo: 30, moveStart: 0.3, moveEnd: 0.42, ease: 'snap',
      },
      shake: [{ start: 1.05, end: 1.4, amplitude: 0.02, frequency: 24, seed: 5, decay: 9 }],
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0]), plate()],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: { color: '#efe6d2', sfx: [focusLines('reaction-lines', 0.75, 2.5, '#2a2238', { intensity: 2.2, size: 120, y: 38 })] },
    worldSfx: [],
    sfx: [focusLines('zoom-lines', 0.75, 1.15, '#3b3150', { intensity: 1.2, size: 130, y: 40 })],
    copy: copy(
      { title: 'Snap zoom', description: 'A full figure, then a crash push to the eyes in under a third of a second, with speed lines during the move.', requirements: [`${CUTOUT_EN} (subject)`, PLATE_EN] },
      { title: 'Zoom relámpago', description: 'Figura entera y, en menos de un tercio de segundo, empujón brusco hasta los ojos, con líneas de velocidad durante el movimiento.', requirements: [`${CUTOUT_ES} (protagonista)`, PLATE_ES] },
    ),
  },
  'anime-sword-clash': {
    category: 'action', duration: 4, light: KEY,
    camera: cam('fixed', [0, 1.15, 5.4], [0, 1, 0], 38, {
      shake: [{ start: CLASH, end: 3.6, amplitude: 0.12, frequency: 18, seed: 9, decay: 3 }],
    }),
    slots: [
      cutout('subject', 'subject_1', [-4.2, 0, 0.3], { motion: { to: [1.9, 0, 0.3], easing: 'smooth' } }),
      cutout('rival', 'subject_2', [4.2, 0, -0.3], { motion: { to: [-1.9, 0, -0.3], easing: 'smooth' } }),
      plate(),
    ],
    aliases: { subject: 'subject', rival: 'rival', background: 'background' },
    backdrop: { color: '#1a2240', sfx: [focusLines('rush-lines', 0, 4, '#8fb6ff', { intensity: 1.2, y: 45 })] },
    worldSfx: [
      { id: 'clash-ring', kind: 'shockwave', start: CLASH, end: CLASH + 1.1, position: { x: 0, y: 0.02, z: 0 }, scale: 1.6, color: '#bfe8ff' },
      { id: 'clash-sparks', kind: 'sparks', start: CLASH, end: CLASH + 0.7, position: { x: 0, y: 1.2, z: 0 }, scale: 1.2, color: '#ffd27a' },
    ],
    sfx: [
      { id: 'slash', kind: 'sword_slash', start: CLASH - frames(2), end: CLASH + 0.3, x: 50, y: 40, size: 80, rotation: -18, color: '#ffffff' },
      { id: 'clash-flash', kind: 'impact_flash', start: CLASH, end: CLASH + frames(3), x: 50, y: 45, size: 60 },
    ],
    copy: copy(
      { title: 'Sword clash', description: 'Two fighters rush in from both edges and cross at the centre: a slash, a shockwave, a white impact frame and a hard shake.', requirements: [`${CUTOUT_EN} (subject)`, `${CUTOUT_EN} (rival)`, PLATE_EN] },
      { title: 'Choque de espadas', description: 'Dos luchadores entran a la carrera por los lados y se cruzan en el centro: tajo, onda expansiva, fotograma blanco y sacudida fuerte.', requirements: [`${CUTOUT_ES} (protagonista)`, `${CUTOUT_ES} (rival)`, PLATE_ES] },
    ),
  },
  'anime-face-off': {
    category: 'action', duration: 4, light: KEY,
    camera: cam('establishment', [0, 1.6, 1.7], [0, 1.6, 0], 36, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0.5 / FIGURE, 0.02, 1.75], to: [0.5 / FIGURE, 0.04, 1.25], lookFrom: [0.5 / FIGURE, 0, 0], lookTo: [0.5 / FIGURE, 0.02, 0],
      },
      shake: [{ start: FACE_OFF_FLASH, end: 4, amplitude: 0.025, frequency: 22, seed: 2, decay: 6 }],
    }),
    slots: [
      cutout('subject', 'subject_1', [-0.5, 0, 0], { rotationY: 0.15 }),
      cutout('rival', 'subject_2', [0.5, 0, -0.12], { rotationY: -0.15 }),
      plate(),
    ],
    aliases: { subject: 'subject', rival: 'rival', background: 'background' },
    backdrop: { color: '#0e0a1a', sfx: [focusLines('stare-lines', 0, 4, '#ff4d3a', { intensity: 1.6, size: 160 })] },
    worldSfx: [
      { id: 'glare', kind: 'lightning', start: 1.4, end: 3.5, position: { x: -0.38, y: 1.6, z: 0.05 }, targetPosition: { x: 0.38, y: 1.6, z: -0.07 }, scale: 0.5, color: '#ffe36c' },
    ],
    sfx: [{ id: 'stare-flash', kind: 'impact_flash', start: FACE_OFF_FLASH, end: FACE_OFF_FLASH + frames(3), x: 50, y: 40, size: 60 }],
    copy: copy(
      { title: 'Face-off', description: 'Two rivals stare each other down in close-up on the left and right halves, over dark focus lines; a slow push and a flash.', requirements: [`${CUTOUT_EN} (subject, left)`, `${CUTOUT_EN} (rival, right)`, PLATE_EN] },
      { title: 'Duelo de miradas', description: 'Dos rivales se miran en primer plano, uno en cada mitad, sobre líneas oscuras; empuje lento y un destello final.', requirements: [`${CUTOUT_ES} (protagonista, izquierda)`, `${CUTOUT_ES} (rival, derecha)`, PLATE_ES] },
    ),
  },
  'anime-airship-flyby': {
    category: 'action', duration: 6, light: light([-0.45, -0.7, -0.35], 2.1, '#fff1d6'),
    camera: cam('follow', [-4, 3.5, 9.5], [-12, 6, -4], 42, {
      // The software preview has no framing: `follow` keeps the vehicle centred there too.
      orbitRadius: 13,
      framing: {
        targetSlot: 'vehicle', anchor: 'center', relativeToFacing: false,
        from: [-2.2, -1.6, 7.5], to: [2, -1, 6.5], lookFrom: [0.9, 0, 0], lookTo: [-0.8, 0, 0],
      },
      shake: [{ start: 0, end: 6, amplitude: 0.025, frequency: 3, seed: 4 }],
    }),
    slots: [
      model('vehicle', 'subject_1', [-16, 6, -4], { rotationY: PI / 2, scale: 1.8, motion: { to: [16, 7, -4], via: [0, 7.8, -2], faceTravel: true, easing: 'linear' } }),
      plate(),
    ],
    aliases: { vehicle: 'vehicle', background: 'background' },
    backdrop: { color: '#6db6ea', sfx: [] },
    // Near clouds sit below and above the line of sight so they stream past without hiding the vehicle.
    worldSfx: [
      cloud('near-1', -14, 1.2, 2, 3, 6), cloud('near-2', -5, 9.5, 1, 2.6, 6), cloud('near-3', 3, 1.4, 3, 3, 6),
      cloud('near-4', 12, 9.8, 2, 2.6, 6), cloud('far-1', -16, 4, -16, 5, 6), cloud('far-2', -6, 10, -18, 5, 6),
      cloud('far-3', 6, 3.5, -17, 5, 6), cloud('far-4', 16, 9.5, -16, 5, 6),
    ],
    sfx: [],
    copy: copy(
      { title: 'Airship flyby', description: 'A vehicle flies across a painted sky on a gentle arc while the camera tracks it and clouds stream past.', requirements: ['GLB vehicle, static or with a clip (vehicle)', 'Optional sky image (environment plate)'] },
      { title: 'Pasada de aeronave', description: 'Un vehículo cruza un cielo pintado en un arco suave; la cámara lo sigue y las nubes pasan de largo.', requirements: ['GLB del vehículo, fijo o con clip (vehicle)', 'Imagen de cielo opcional (plano de entorno)'] },
    ),
  },
  'anime-fleet-approach': {
    category: 'action', duration: 6, light: light([-0.3, -0.75, -0.55], 2, '#fff1d6'),
    camera: cam('establishment', [0, 4, 14], [0, 6.5, -30], 34, {
      shake: [{ start: 4.6, end: 6, amplitude: 0.05, frequency: 7, seed: 13 }],
    }),
    slots: [
      model('vehicle_1', 'prop', [0, 6, -66], { scale: 1.6, motion: { to: [0.6, 4.6, 6], faceTravel: true, easing: 'linear' } }),
      model('vehicle_2', 'prop', [-8, 8.5, -72], { scale: 1.6, motion: { to: [-5.5, 6.8, -6], faceTravel: true, easing: 'linear' } }),
      model('vehicle_3', 'prop', [8.5, 7.5, -70], { scale: 1.6, motion: { to: [5.8, 6.2, -4], faceTravel: true, easing: 'linear' } }),
      model('vehicle_4', 'prop', [-2.5, 11, -80], { scale: 1.6, motion: { to: [-2, 9.5, -16], faceTravel: true, easing: 'linear' } }),
      plate(),
    ],
    aliases: { vehicle: 'vehicle_1', background: 'background' },
    backdrop: { color: '#5aa3dd', sfx: [] },
    // Two layers of bank hide the formation at first; the ships cross them at about a third of the shot.
    worldSfx: [
      cloud('bank-1', -16, 6, -46, 10, 6, 1.6), cloud('bank-2', 0, 9, -47, 12, 6, 1.6), cloud('bank-3', 16, 6.5, -46, 10, 6, 1.6),
      cloud('bank-4', -7, 4.5, -42, 9, 6, 1.4), cloud('bank-5', 9, 11, -43, 9, 6, 1.4),
      cloud('mid-1', -15, 5, -22, 5, 6), cloud('mid-2', 14, 11, -24, 5, 6), cloud('near-1', -8, 1.6, 4, 3, 6),
    ],
    sfx: [],
    copy: copy(
      { title: 'Fleet approach', description: 'Four copies of one vehicle break out of a cloud bank in a staggered formation and come at the camera.', requirements: ['The same GLB in vehicle_1 … vehicle_4 (role prop)', 'Optional sky image (environment plate)'] },
      { title: 'Llegada de la flota', description: 'Cuatro copias de un mismo vehículo salen de un banco de nubes en formación escalonada y vienen hacia la cámara.', requirements: ['El mismo GLB en vehicle_1 … vehicle_4 (papel prop)', 'Imagen de cielo opcional (plano de entorno)'] },
    ),
  },
  'anime-eyecatch': {
    category: 'cinema', duration: 3, light: KEY,
    camera: cam('fixed', [0, 1.1, 4.6], [0, 1, 0], 38),
    slots: [
      cutout('subject', 'subject_1', [0, 0, -7], { motion: { to: [0, 0, 1], turnTo: PI * 4, easing: 'smooth' } }),
      plate(),
    ],
    aliases: { subject: 'subject', background: 'background' },
    backdrop: {
      color: '#ffcf3a',
      sfx: [
        focusLines('card-lines', 0, 3, '#e8432f', { intensity: 2.4, size: 170, y: 50 }),
        { id: 'card-stars', kind: 'stars', start: 0, end: 3, x: 50, y: 50, size: 120, intensity: 0.8, color: '#ffffff' },
      ],
    },
    worldSfx: [],
    sfx: [{ id: 'landing-stars', kind: 'stars', start: 2.1, end: 3, x: 50, y: 45, size: 60, color: '#fffbe0' }],
    title: { id: 'eyecatch-title', start: 1.6, end: 3, preset: 'impact', x: 50, y: 86, size: 9, color: '#ffffff', rotation: -4 },
    copy: copy(
      { title: 'Eyecatch', description: 'A short scene-change card: the figure spins in from the distance over a graphic backdrop of focus lines and stars.', requirements: [`${CUTOUT_EN} (subject)`, 'Optional title text', PLATE_EN] },
      { title: 'Eyecatch (cortinilla)', description: 'Cortinilla breve de cambio de escena: la figura llega girando desde el fondo sobre un fondo gráfico de líneas y estrellas.', requirements: [`${CUTOUT_ES} (protagonista)`, 'Texto de título opcional', PLATE_ES] },
    ),
  },
}

export function isAnimeTemplateId(id: string): id is AnimeTemplateId {
  return (ANIME_TEMPLATE_IDS as readonly string[]).includes(id)
}

function uniqueRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  return [...new Set(slots.map(slot => slot.slot))]
}

export const ANIME_TEMPLATES = ANIME_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
  tags: ['anime'] as const,
}))

export const ANIME_CATEGORIES = Object.fromEntries(
  ANIME_TEMPLATE_IDS.map(id => [id, SPECS[id].category]),
) as Record<AnimeTemplateId, 'action' | 'cinema'>

function bindSlot(slot: Scene3DSlot, roles: AnimeApplyOptions['roles'], aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const alias = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const family = slot.id.replace(/_\d+$/, '')
  const url = roles[slot.id] ?? (alias ? roles[alias] : undefined) ?? roles[family] ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

function buildDocument(spec: AnimeSpec, id: AnimeTemplateId, options: AnimeApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.fps = FPS
  doc.width = vertical ? 1080 : 1920
  doc.height = vertical ? 1920 : 1080
  doc.environment = { reflectiveFloor: false, platform: false, bloom: 0.12, floorStyle: 'none' }
  // Flat cel colours: a neutral curve at 0 EV keeps backdrop and cutout colours as authored.
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

export function applyAnimeTemplate(id: string, options: AnimeApplyOptions = {}): Scene3DDocument | null {
  if (!isAnimeTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function animeTemplateDocument(id: string): Scene3DDocument | null {
  return applyAnimeTemplate(id)
}

export function animeCard(id: string, locale: 'en' | 'es' = 'en'): AnimeCardCopy | undefined {
  if (!isAnimeTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

/** The authored cue kinds before parsing, so a check can prove none was dropped as unknown. */
export function animeAuthoredCueKinds(id: string): { sfx: string[]; worldSfx: string[]; backdrop: string[] } {
  if (!isAnimeTemplateId(id)) return { sfx: [], worldSfx: [], backdrop: [] }
  const kinds = (cues: Array<Record<string, unknown>>) => cues.map(cue => String(cue.kind))
  return { sfx: kinds(SPECS[id].sfx), worldSfx: kinds(SPECS[id].worldSfx), backdrop: kinds(SPECS[id].backdrop.sfx) }
}

export function animeAliases(id: string): Record<string, string> {
  return isAnimeTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
