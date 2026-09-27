import { createDefaultScene3DDocument, parseScene3DDocument } from './document.ts'
import { toPortraitCamera } from './frameFormat.ts'
import { defaultMediaScreen } from './mediaScreen.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import { parseWorldSfx } from '../sceneFx/world.ts'
import type { KineticText } from '../../lib/kineticText.ts'
import type {
  Scene3DCamera,
  Scene3DCameraFamily,
  Scene3DDocument,
  Scene3DLight,
  Scene3DSlot,
  Scene3DSlotId,
  Scene3DSourceRef,
  Vec3,
} from './types.ts'

export const CAMPAIGN_TEMPLATE_IDS = [
  'server-inspection',
  'coding-desk',
  'tracking-chase',
  'character-presentation',
  'screen-alert',
  'product-comparison',
  'topic-travelling',
  'heroic-close',
] as const

export type CampaignTemplateId = typeof CAMPAIGN_TEMPLATE_IDS[number]
export type CampaignOrientation = 'horizontal' | 'vertical'
export type CampaignApplyOptions = {
  orientation?: CampaignOrientation
  roles?: Partial<Record<string, string>>
  audio?: Scene3DSourceRef
  text?: boolean | string
}
export type CampaignCardCopy = { title: string; description: string; requirements: string[] }

type CampaignSpec = {
  category: 'cinema' | 'product'
  duration: number
  dressing?: Scene3DDocument['dressing']
  workshopScreen?: Scene3DDocument['workshopScreen']
  environment?: Scene3DDocument['environment']
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  texts: KineticText[]
  worldSfx: Array<Record<string, unknown>>
  sfx: Array<Record<string, unknown>>
  copy: { en: CampaignCardCopy; es: CampaignCardCopy }
}

const PI = Math.PI
const model = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'model3d', sourceUrl: '', clip: null, position, rotationY: 0, scale: 1, ...patch,
})
const backdrop = (position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => (
  model('background', 'background', position, { media: 'image', scale: 8, ...patch })
)
const screen = (id: string, position: Vec3, width: number, height: number, style: NonNullable<Scene3DSlot['screen']>['style'], rotationY = 0): Scene3DSlot => ({
  id, slot: 'prop', media: 'screen', sourceUrl: '', clip: null, position, rotationY, scale: 1,
  screen: { ...defaultMediaScreen(), width, height, style },
})
const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
const light = (direction: Vec3, intensity: number, color: string): Scene3DLight => (
  { kind: 'directional', direction, intensity, color }
)
const title = (id: string, text: string, preset: KineticText['preset'], x: number, y: number, size: number, color: string, end: number, font?: KineticText['font']): KineticText => (
  { id, text, start: 0.2, end, preset, x, y, size, color, rotation: 0, ...(font ? { font } : {}) }
)
const copy = (en: CampaignCardCopy, es: CampaignCardCopy) => ({ en, es })

export function isCampaignTemplateId(id: string): id is CampaignTemplateId {
  return (CAMPAIGN_TEMPLATE_IDS as readonly string[]).includes(id)
}

const SPECS: Record<CampaignTemplateId, CampaignSpec> = {
  'server-inspection': {
    category: 'cinema', duration: 8, dressing: 'citadel',
    light: light([-0.2, -0.95, 0.35], 2.3, '#dceaff'),
    camera: cam('reveal', [2.2, 7.4, 8.2], [0, 1.1, -0.4], 48),
    slots: [
      model('subject_1', 'subject_1', [-4.2, 0, 2.4], { rotationY: PI / 2, motion: { to: [0.55, 0, 0.9], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, -1.1], { scale: 1.25, grounded: true }),
      backdrop([0, 1.2, -8], { scale: 10 }),
    ],
    aliases: { inspector: 'subject_1', rack: 'prop', backdrop: 'background' },
    texts: [title('inspect-label', 'SERVER 04', 'typewriter', 50, 86, 8, '#b8f4ff', 7, 'mono')],
    worldSfx: [
      { id: 'rack-sparks', kind: 'sparks', start: 1.2, end: 7.4, position: { x: 0, y: 0.9, z: -1.1 }, color: '#7ad7ff', sound: true },
      { id: 'scan-beam', kind: 'energy_beam', start: 2, end: 5.5, position: { x: 0.4, y: 4.2, z: -0.4 }, targetPosition: { x: 0, y: 1, z: -1.1 }, color: '#70dcff' },
    ],
    sfx: [{ id: 'hud-scan', kind: 'scanline', start: 0.4, end: 8, x: 50, y: 42 }],
    copy: copy(
      { title: 'Server inspection', description: 'A crane drops onto a rack while an inspector walks in from the aisle.', requirements: ['GLB inspector (lead)', 'GLB or model for the rack (prop)', 'Optional backdrop image', 'Optional title / soundtrack'] },
      { title: 'Inspección de servidor', description: 'Una grúa baja hacia el rack mientras el inspector entra por el pasillo.', requirements: ['GLB inspector (protagonista)', 'GLB o modelo del rack (atrezzo)', 'Imagen de fondo opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'coding-desk': {
    category: 'cinema', duration: 7, dressing: 'workshop', workshopScreen: 'code',
    light: light([-0.45, -0.8, -0.2], 1.45, '#fff0d9'),
    camera: cam('establishment', [3.1, 1.95, 3.6], [0, 1.05, -0.35], 40),
    slots: [
      model('subject_1', 'subject_1', [-2.8, 0, 1.6], { performance: 'typing', motion: { to: [0, 0, 0.55], turnTo: PI, easing: 'smooth' } }),
      screen('desk-monitor', [-0.1, 1.36, -0.94], 1.18, 0.62, 'monitor'),
      backdrop([0, 0.7, -4.8], { scale: 6 }),
    ],
    aliases: { coder: 'subject_1', display: 'desk-monitor', backdrop: 'background' },
    texts: [title('commit-label', 'git commit', 'typewriter', 18, 88, 6, '#72daef', 6.4, 'mono')],
    worldSfx: [],
    sfx: [{ id: 'keys', kind: 'sparks', start: 1.4, end: 6.5, x: 48, y: 70, size: 28 }],
    copy: copy(
      { title: 'Coding desk', description: 'The coder sits at a workshop desk; the monitor is a replaceable screen.', requirements: ['GLB coder (lead)', 'Image or video for the desk monitor', 'Optional backdrop', 'Optional title / soundtrack'] },
      { title: 'Mesa de código', description: 'El programador se sienta en el taller; el monitor es una pantalla intercambiable.', requirements: ['GLB programador (protagonista)', 'Imagen o vídeo para el monitor', 'Fondo opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'tracking-chase': {
    category: 'cinema', duration: 6, dressing: 'chase-street',
    light: light([-0.15, -0.7, 0.6], 1.8, '#ffe6c8'),
    camera: cam('side', [0, 1.35, 5], [0, 1, 0], 44, {
      eyeOffset: [5.4, 0.15, 0.4], targetOffset: [0, 0.12, 0],
      framing: { targetSlot: 'subject_1', anchor: 'center', from: [5.2, 0.18, 0.35], to: [5.2, 0.22, -0.25], relativeToFacing: true },
    }),
    slots: [
      model('subject_1', 'subject_1', [-7, 0, 0], { motion: { to: [8, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-9.2, 0, -1.15], { scale: 0.95, motion: { to: [6.1, 0, -1.15], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1, -6], { scale: 13 }),
    ],
    aliases: { runner: 'subject_1', pursuer: 'subject_2', backdrop: 'background' },
    texts: [title('chase-label', 'KEEP UP', 'impact', 78, 18, 10, '#ffe3a0', 5.4)],
    worldSfx: [
      { id: 'street-dust', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.04, z: 0 }, scale: 1.8 },
      { id: 'exhaust', kind: 'smoke', start: 0.4, end: 6, position: { x: -2, y: 0.2, z: -0.4 }, color: '#6b5348' },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.2, end: 6, x: 50, y: 48 }],
    copy: copy(
      { title: 'Tracking chase', description: 'A side-on track follows two runners along a street; they enter left and exit right.', requirements: ['GLB lead runner', 'GLB pursuer', 'Optional street plate', 'Optional title / soundtrack'] },
      { title: 'Persecución en travelling', description: 'Un travelling lateral sigue a dos corredores; entran por la izquierda y salen por la derecha.', requirements: ['GLB corredor principal', 'GLB perseguidor', 'Placa de calle opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'character-presentation': {
    category: 'cinema', duration: 8, dressing: 'citadel',
    environment: { reflectiveFloor: true, platform: true, bloom: 0.52 },
    light: light([-0.4, -0.85, -0.45], 3.1, '#e9e3ff'),
    camera: cam('orbit', [0, 1.6, 4.4], [0, 1.2, 0], 36, { orbitRadius: 4.4, orbitHeight: 1.15, orbitTurns: 0.38 }),
    slots: [
      model('subject_1', 'subject_1', [0, 0.2, 3.4], {
        appearance: { start: 1.15, duration: 0.85, color: '#83e8ff' },
        performance: 'idle',
        motion: { to: [0, 0.235, 0], easing: 'smooth' },
      }),
      model('prop', 'prop', [0, 0, 0], { scale: 0.38, grounded: true }),
      backdrop([0, 0, 0], { scale: 1, surface: 'environment' }),
    ],
    aliases: { hero: 'subject_1', pedestal: 'prop', backdrop: 'background' },
    texts: [title('intro-label', 'INTRODUCING', 'rise', 50, 14, 9, '#d8c6ff', 6.5)],
    worldSfx: [
      { id: 'gate', kind: 'summoning_gate', start: 0.6, end: 3.6, position: { x: 0, y: 1.4, z: -0.5 }, color: '#b997ff' },
      { id: 'arrival-sparks', kind: 'sparks', start: 1.2, end: 4.2, position: { x: 0, y: 0.3, z: 0 }, color: '#f7c186' },
    ],
    sfx: [{ id: 'stars', kind: 'stars', start: 1.1, end: 7.2, x: 50, y: 40 }],
    copy: copy(
      { title: 'Character presentation', description: 'An orbit around a materializing hero on a reflective pedestal.', requirements: ['GLB hero (lead)', 'Optional pedestal prop', 'Optional illustrated backdrop', 'Optional title / soundtrack'] },
      { title: 'Presentación de personaje', description: 'Una órbita alrededor del héroe que materializa sobre una tarima reflectante.', requirements: ['GLB héroe (protagonista)', 'Atrezzo de tarima opcional', 'Fondo ilustrado opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'screen-alert': {
    category: 'product', duration: 5, dressing: 'observatory',
    light: light([0.25, -0.7, -0.55], 3.05, '#ffd7d0'),
    camera: cam('front', [0, 1.7, 6.2], [0, 1.5, -1.2], 38, { eyeOffset: [0, 0.12, 4.35] }),
    slots: [
      model('subject_1', 'subject_1', [2.5, 0, 1.9], { motion: { to: [1.15, 0, 0.55], turnTo: -0.4, easing: 'smooth' } }),
      screen('alert-screen', [0, 1.55, -2.2], 5.4, 3.05, 'billboard'),
      backdrop([0, 0, 0], { scale: 1, surface: 'environment' }),
    ],
    aliases: { operator: 'subject_1', display: 'alert-screen', backdrop: 'background' },
    texts: [title('alert-label', 'ALERT', 'impact', 50, 22, 12, '#ff6a5a', 4.6)],
    worldSfx: [
      { id: 'bolt', kind: 'lightning', start: 0.35, end: 1.4, position: { x: 0.3, y: 4.6, z: -1.4 }, targetPosition: { x: 0, y: 1.6, z: -2.1 }, color: '#bbddff', intensity: 1.4 },
      { id: 'pulse', kind: 'shockwave', start: 0.5, end: 2.4, position: { x: 0, y: 0.04, z: -1.8 }, color: '#ff8866', scale: 1.7 },
    ],
    sfx: [{ id: 'alert-scan', kind: 'scanline', start: 0, end: 5, x: 50, y: 46, color: '#66ffbb' }],
    copy: copy(
      { title: 'Screen alert', description: 'An operator rushes a giant alert board as lightning hits the glass.', requirements: ['GLB operator (lead)', 'Image or video for the alert board', 'Optional backdrop', 'Optional title / soundtrack'] },
      { title: 'Alerta en pantalla', description: 'El operador corre hacia el mural de alerta cuando el rayo golpea el cristal.', requirements: ['GLB operador (protagonista)', 'Imagen o vídeo del mural', 'Fondo opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'product-comparison': {
    category: 'product', duration: 6, dressing: 'retro-lab',
    light: light([-0.25, -1, -0.15], 2.05, '#fff4e5'),
    camera: cam('product', [0, 1.35, 3.5], [0, 0.85, 0], 34, { orbitRadius: 3.35, orbitHeight: 0.42, orbitTurns: 0.18 }),
    slots: [
      model('subject_1', 'subject_1', [-3.15, 0.18, 0], { scale: 0.72, motion: { to: [-0.85, 0.16, 0], easing: 'smooth' } }),
      model('subject_2', 'subject_2', [3.15, 0.18, 0], { scale: 0.72, motion: { to: [0.85, 0.16, 0], easing: 'smooth' } }),
      backdrop([0, 0.8, -6], { scale: 8 }),
    ],
    aliases: { left: 'subject_1', right: 'subject_2', backdrop: 'background' },
    texts: [title('vs-label', 'A vs B', 'wave', 50, 84, 9, '#ffe3a0', 5.6)],
    worldSfx: [],
    sfx: [{ id: 'glints', kind: 'sparks', start: 0.6, end: 5.4, x: 50, y: 58, size: 36 }],
    copy: copy(
      { title: 'Product comparison', description: 'Two products slide in from opposite sides while the camera orbits the pair.', requirements: ['GLB or model for product A', 'GLB or model for product B', 'Optional lab backdrop', 'Optional title / soundtrack'] },
      { title: 'Comparación de producto', description: 'Dos productos entran desde lados opuestos mientras la cámara orbita el par.', requirements: ['GLB o modelo del producto A', 'GLB o modelo del producto B', 'Fondo de laboratorio opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'topic-travelling': {
    category: 'cinema', duration: 9, dressing: 'broadcast-plaza',
    light: light([-0.35, -0.75, -0.3], 2.4, '#dde9ff'),
    camera: cam('follow', [0.4, 2.1, 7], [0, 1.25, 0], 47, { eyeOffset: [0.35, 0.8, 7.2], targetOffset: [0, 0.18, 0], orbitRadius: 7.2 }),
    slots: [
      model('subject_1', 'subject_1', [0, 0.2, -6.4], { motion: { to: [0, 0.2, 5.2], faceTravel: true, easing: 'linear' } }),
      screen('topic-a', [-4.1, 1.35, -2.4], 3.6, 2.2, 'frameless', PI / 2),
      screen('topic-b', [4.1, 1.45, 0.4], 3.6, 2.2, 'frameless', -PI / 2),
      screen('topic-c', [-4.1, 1.3, 3.2], 3.6, 2.2, 'frameless', PI / 2),
      backdrop([0, 0, 0], { scale: 1, surface: 'environment' }),
    ],
    aliases: { guide: 'subject_1', display: 'topic-a', backdrop: 'background' },
    texts: [title('topic-label', 'NEXT STOP', 'rise', 50, 16, 8, '#c9e7ff', 7.5)],
    worldSfx: [{ id: 'plaza-fog', kind: 'fog', start: 0, end: 9, position: { x: 0, y: 0.08, z: 0 }, scale: 2.1, color: '#aabbcc' }],
    sfx: [{ id: 'aurora', kind: 'aurora', start: 0.3, end: 8.5, x: 50, y: 28 }],
    copy: copy(
      { title: 'Topic travelling', description: 'A guide walks a plaza corridor past replaceable topic screens.', requirements: ['GLB guide (lead)', 'Image or video for topic screens', 'Optional plaza backdrop', 'Optional title / soundtrack'] },
      { title: 'Travelling temático', description: 'La guía recorre un pasillo de plaza junto a pantallas de tema intercambiables.', requirements: ['GLB guía (protagonista)', 'Imagen o vídeo para las pantallas', 'Fondo de plaza opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'heroic-close': {
    category: 'cinema', duration: 5, dressing: 'citadel',
    environment: { reflectiveFloor: true, platform: false, bloom: 0.72 },
    light: light([-0.28, -0.92, 0.48], 3.45, '#ffe2c4'),
    camera: cam('pursuit', [0.45, 1.15, 3.3], [0, 1.42, 0], 30, {
      framing: {
        targetSlot: 'subject_1', anchor: 'head',
        from: [0.38, -0.44, 2.65], to: [0.05, 0.05, 0.9],
        lookFrom: [0, -0.16, 0], lookTo: [0, 0.04, 0],
      },
    }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 1.45], { scale: 1.12, motion: { to: [0, 0, 0.12], easing: 'smooth' } }),
      backdrop([0, 1, -7], { scale: 9 }),
    ],
    aliases: { hero: 'subject_1', backdrop: 'background' },
    texts: [title('stand-label', 'STAND', 'impact', 50, 80, 11, '#ffe3a0', 4.4)],
    worldSfx: [
      { id: 'aura', kind: 'anime_aura', start: 0.8, end: 5, position: { x: 0, y: 0.9, z: 0.2 }, color: '#ffe36c', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.9, z: 0 } } },
      { id: 'close-shock', kind: 'shockwave', start: 3.1, end: 5, position: { x: 0, y: 0.03, z: 0.12 }, color: '#ffec77', scale: 1.5 },
    ],
    sfx: [{ id: 'impact', kind: 'manga_impact', start: 3.05, end: 4.7, x: 52, y: 46 }],
    copy: copy(
      { title: 'Heroic close', description: 'A low pursuit push lands on the face as the hero steps into a close-up.', requirements: ['GLB hero (lead)', 'Optional backdrop image', 'Optional title / soundtrack'] },
      { title: 'Cierre heroico', description: 'Un empuje bajo a la cara mientras el héroe entra en primer plano.', requirements: ['GLB héroe (protagonista)', 'Imagen de fondo opcional', 'Título / banda sonora opcionales'] },
    ),
  },
}

function uniqueRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  const seen = new Set<Scene3DSlotId>()
  const roles: Scene3DSlotId[] = []
  for (const slot of slots) {
    if (seen.has(slot.slot)) continue
    seen.add(slot.slot)
    roles.push(slot.slot)
  }
  return roles
}

export const CAMPAIGN_TEMPLATES = CAMPAIGN_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
}))

export const CAMPAIGN_CATEGORIES = Object.fromEntries(
  CAMPAIGN_TEMPLATE_IDS.map(id => [id, SPECS[id].category]),
) as Record<CampaignTemplateId, 'cinema' | 'product'>

function orientCamera(camera: Scene3DCamera, vertical: boolean): Scene3DCamera {
  return vertical ? toPortraitCamera(camera) : structuredClone(camera)
}

function bindSlot(slot: Scene3DSlot, roles: Partial<Record<string, string>> | undefined, aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const role = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const url = roles[slot.id] ?? (role ? roles[role] : undefined) ?? roles[slot.slot]
  if (!url) return next
  if (next.media === 'screen') {
    next.screen = { ...(next.screen ?? defaultMediaScreen()), sourceUrl: url }
    return next
  }
  next.sourceUrl = url
  return next
}

function chooseTexts(texts: KineticText[], text?: boolean | string) {
  if (text === false) return undefined
  if (typeof text !== 'string') return texts.map(cue => ({ ...cue }))
  return texts.map((cue, index) => (index === 0 ? { ...cue, text } : { ...cue }))
}

function attachAudio(doc: Scene3DDocument, audio?: Scene3DSourceRef) {
  if (!audio) return
  doc.soundtrack = [{ id: 'campaign-audio', audio, start: 0, offset: 0, gain: 1 }]
}

function buildDocument(spec: CampaignSpec, id: CampaignTemplateId, options: CampaignApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.width = vertical ? 720 : 1280
  doc.height = vertical ? 1280 : 720
  doc.dressing = spec.dressing
  doc.workshopScreen = spec.workshopScreen
  doc.environment = spec.environment
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = orientCamera(spec.camera, vertical)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  doc.worldSfx = parseWorldSfx(spec.worldSfx)
  doc.sfx = parseSceneFx(spec.sfx)
  doc.texts = chooseTexts(spec.texts, options.text)
  attachAudio(doc, options.audio)
  return doc
}

export function applyCampaignTemplate(id: string, options: CampaignApplyOptions = {}): Scene3DDocument | null {
  if (!isCampaignTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function campaignTemplateDocument(id: string): Scene3DDocument | null {
  return applyCampaignTemplate(id)
}

export function parseCampaignDocument(raw: unknown): Scene3DDocument | null {
  return parseScene3DDocument(raw)
}

export function campaignCard(id: string, locale: 'en' | 'es' = 'en'): CampaignCardCopy | undefined {
  if (!isCampaignTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function campaignAliases(id: string): Record<string, string> {
  return isCampaignTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
