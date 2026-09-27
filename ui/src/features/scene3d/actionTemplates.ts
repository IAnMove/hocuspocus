import { createDefaultScene3DDocument, parseScene3DDocument } from './document.ts'
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
import type { Scene3DSoundtrack } from './speech/types.ts'
import { FACE_PACK_SOUNDTRACK, talkingMascot } from './speech/facePackExamples.ts'

export const ACTION_TEMPLATE_IDS = [
  'sea-deck',
  'lunar-outpost',
  'car-chase',
  'ship-chase',
  'rooftop-run',
  'alley-motorcycle',
  'hangar-standoff',
  'train-roof',
  'desert-convoy',
  'night-rain-pursuit',
  'dock-ambush',
  'bridge-standoff',
  'cockpit-pursuit',
  'helicopter-extract',
  'warehouse-breach',
  'canyon-run',
  'jungle-ambush',
  'snow-compound',
  'casino-heist',
  'bank-vault',
  'skyscraper-ledge',
  'oil-rig',
  'subway-brawl',
  'freeway-overpass',
  'prison-break',
  'arctic-chase',
  'clock-tower',
  'mansion-infil',
  'cargo-hold',
  'jungle-river',
  'red-carpet',
  'volcano-ridge',
  'hangar-talk',
  'sea-talk',
  'voxel-talk',
] as const

export type ActionTemplateId = typeof ACTION_TEMPLATE_IDS[number]
export type ActionOrientation = 'horizontal' | 'vertical'
export type ActionApplyOptions = {
  orientation?: ActionOrientation
  roles?: Partial<Record<string, string>>
  audio?: Scene3DSourceRef
  text?: boolean | string
}
export type ActionCardCopy = { title: string; description: string; requirements: string[] }

type ActionSpec = {
  category: 'action'
  duration: number
  dressing?: Scene3DDocument['dressing']
  environment?: Scene3DDocument['environment']
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  texts: KineticText[]
  worldSfx: Array<Record<string, unknown>>
  sfx: Array<Record<string, unknown>>
  soundtrack?: Scene3DSoundtrack[]
  copy: { en: ActionCardCopy; es: ActionCardCopy }
}

const PI = Math.PI
const model = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'model3d', sourceUrl: '', clip: null, position, rotationY: 0, scale: 1, ...patch,
})
const backdrop = (position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => (
  model('background', 'background', position, { media: 'image', scale: 8, ...patch })
)
const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
const light = (direction: Vec3, intensity: number, color: string): Scene3DLight => (
  { kind: 'directional', direction, intensity, color }
)
const title = (id: string, text: string, preset: KineticText['preset'], x: number, y: number, size: number, color: string, end: number): KineticText => (
  { id, text, start: 0.2, end, preset, x, y, size, color, rotation: 0 }
)
const copy = (en: ActionCardCopy, es: ActionCardCopy) => ({ en, es })

export function isActionTemplateId(id: string): id is ActionTemplateId {
  return (ACTION_TEMPLATE_IDS as readonly string[]).includes(id)
}

const SPECS: Record<ActionTemplateId, ActionSpec> = {
  'sea-deck': {
    category: 'action', duration: 8, dressing: 'open-sea',
    light: light([-0.35, -0.85, 0.25], 2.6, '#ffe2b0'),
    camera: cam('establishment', [6.4, 2.6, 9.2], [0, 0.85, 0.4], 42),
    slots: [
      model('subject_1', 'subject_1', [-0.6, 0, 4.6], { rotationY: PI, motion: { to: [0.15, 0, 0.55], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [1.35, 0, -4.2], { rotationY: 0, scale: 0.96, motion: { to: [1.2, 0, 1.1], faceTravel: true, easing: 'smooth' } }),
    ],
    aliases: { captain: 'subject_1', crew: 'subject_2' },
    texts: [title('sea-label', 'OPEN WATER', 'rise', 50, 14, 9, '#d7f4ff', 6.8)],
    worldSfx: [
      { id: 'bow-splash', kind: 'splash', start: 0, end: 8, position: { x: 0, y: 0.02, z: -6.2 }, scale: 1.6, color: '#9ad8ff' },
      { id: 'sea-fog', kind: 'fog', start: 0, end: 8, position: { x: 0, y: 0.08, z: -4 }, scale: 2.2, color: '#c5e7f4' },
    ],
    sfx: [{ id: 'horizon', kind: 'aurora', start: 0.3, end: 7.6, x: 50, y: 22 }],
    copy: copy(
      { title: 'Sea deck', description: 'Two leads walk the deck of a boat on open water while spray hits the bow.', requirements: ['GLB captain (lead)', 'GLB crew (second)', 'Optional seascape plate', 'Optional title / soundtrack'] },
      { title: 'Cubierta en el mar', description: 'Dos protagonistas recorren la cubierta de un barco en mar abierto mientras el agua golpea la proa.', requirements: ['GLB capitán (protagonista)', 'GLB tripulación (segundo)', 'Placa de mar opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'lunar-outpost': {
    category: 'action', duration: 9, dressing: 'lunar',
    environment: { reflectiveFloor: false, platform: false, bloom: 0.38 },
    light: light([-0.55, -0.7, -0.2], 2.8, '#e8f0ff'),
    camera: cam('orbit', [0, 1.7, 6.4], [0, 1.1, 0], 42, { orbitRadius: 6.4, orbitHeight: 1.35, orbitTurns: 0.32 }),
    slots: [
      model('subject_1', 'subject_1', [-4.6, 0, 2.8], { motion: { to: [0.35, 0, -0.4], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [2.4, 0, -1.8], { scale: 0.85, grounded: true }),
    ],
    aliases: { astronaut: 'subject_1', habitat: 'prop' },
    texts: [title('moon-label', 'NEAR SIDE', 'typewriter', 18, 86, 7, '#d7e8ff', 7.6)],
    worldSfx: [
      { id: 'regolith', kind: 'dust', start: 0.4, end: 9, position: { x: 0, y: 0.03, z: 0 }, scale: 1.8, color: '#c9c4b8' },
      { id: 'suit-ice', kind: 'ice_burst', start: 2.2, end: 4.4, position: { x: 0.3, y: 0.4, z: -0.3 }, color: '#cfefff' },
    ],
    sfx: [{ id: 'stars', kind: 'stars', start: 0.2, end: 8.6, x: 50, y: 28 }],
    copy: copy(
      { title: 'Lunar outpost', description: 'An astronaut crosses cratered ground toward a habitat with Earth hanging in the sky.', requirements: ['GLB astronaut (lead)', 'Optional habitat prop', 'Optional sky plate', 'Optional title / soundtrack'] },
      { title: 'Puesto lunar', description: 'Un astronauta cruza el regolito hacia el hábitat con la Tierra en el cielo.', requirements: ['GLB astronauta (protagonista)', 'Atrezzo de hábitat opcional', 'Placa de cielo opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'car-chase': {
    category: 'action', duration: 6, dressing: 'chase-street',
    light: light([-0.15, -0.65, 0.55], 1.9, '#ffe6c8'),
    camera: cam('side', [0, 1.2, 5.2], [0, 0.85, 0], 40, {
      eyeOffset: [5.6, 0.08, 0.55], targetOffset: [0, 0.05, 0],
      framing: { targetSlot: 'subject_1', anchor: 'center', from: [5.5, 0.12, 0.45], to: [5.5, 0.2, -0.3], relativeToFacing: true },
    }),
    slots: [
      model('subject_1', 'subject_1', [-8.4, 0, 0], { rotationY: PI / 2, motion: { to: [9.2, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-11.6, 0, -1.35], { rotationY: PI / 2, scale: 0.96, motion: { to: [6.4, 0, -1.35], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1, -7], { scale: 14 }),
    ],
    aliases: { leadCar: 'subject_1', pursuer: 'subject_2', backdrop: 'background' },
    texts: [title('chase-label', 'DO NOT LOSE THEM', 'impact', 78, 16, 9, '#ffe3a0', 5.2)],
    worldSfx: [
      { id: 'tire-dust', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 0 }, scale: 1.7 },
      { id: 'exhaust', kind: 'smoke', start: 0.3, end: 6, position: { x: -3, y: 0.25, z: -0.5 }, color: '#6b5348', anchor: { slotId: 'subject_2', offset: { x: 0, y: 0.3, z: 1.6 } } },
      { id: 'rim-sparks', kind: 'sparks', start: 1.4, end: 5.6, position: { x: 0, y: 0.12, z: 0 }, color: '#ffbb55', anchor: { slotId: 'subject_1', offset: { x: -0.8, y: 0.1, z: 0 } } },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.15, end: 6, x: 50, y: 48 }],
    copy: copy(
      { title: 'Car chase', description: 'A side track sticks to two cars screaming down a city street.', requirements: ['GLB lead car', 'GLB pursuer car', 'Optional street plate', 'Optional title / soundtrack'] },
      { title: 'Persecución en coche', description: 'Un travelling lateral se pega a dos coches a toda velocidad por la ciudad.', requirements: ['GLB coche principal', 'GLB coche perseguidor', 'Placa de calle opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'ship-chase': {
    category: 'action', duration: 7, dressing: 'space-lane',
    environment: { reflectiveFloor: false, platform: false, bloom: 0.62 },
    light: light([-0.4, -0.35, 0.7], 2.2, '#dceaff'),
    camera: cam('chase', [0.4, 1.4, 6.2], [0, 0.9, -1.2], 46),
    slots: [
      model('subject_1', 'subject_1', [-1.6, 1.1, 2.4], { scale: 0.85, motion: { to: [2.4, 0.7, -7.2], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [1.8, 2.2, 6.4], { scale: 0.78, motion: { to: [3.6, 1.1, -3.4], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { fighter: 'subject_1', hunter: 'subject_2' },
    texts: [title('space-label', 'LOCK ON', 'impact', 76, 18, 10, '#9be7ff', 5.8)],
    worldSfx: [
      { id: 'cannon', kind: 'laser', start: 0.6, end: 6.4, position: { x: 1.8, y: 2.1, z: 5.2 }, targetPosition: { x: -1.2, y: 1.1, z: 1.6 }, color: '#66ffbb' },
      { id: 'beam', kind: 'energy_beam', start: 2.1, end: 4.8, position: { x: 3, y: 1.6, z: 0.4 }, targetPosition: { x: 1.4, y: 0.9, z: -4.2 }, color: '#70dcff' },
      { id: 'burst', kind: 'explosion', start: 5.2, end: 7, position: { x: 2.8, y: 1.2, z: -3.6 }, color: '#ff7040', scale: 1.4 },
    ],
    sfx: [{ id: 'hud', kind: 'scanline', start: 0, end: 7, x: 50, y: 42, color: '#66ffbb' }],
    copy: copy(
      { title: 'Ship chase', description: 'Two craft tear through an asteroid lane while lasers stitch the dark.', requirements: ['GLB lead ship', 'GLB hunter ship', 'Optional nebula plate', 'Optional title / soundtrack'] },
      { title: 'Persecución de naves', description: 'Dos naves cruzan un pasillo de asteroides mientras los láseres cortan la oscuridad.', requirements: ['GLB nave principal', 'GLB nave cazadora', 'Placa de nebulosa opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'rooftop-run': {
    category: 'action', duration: 6, dressing: 'rooftop',
    light: light([-0.2, -0.75, 0.4], 2.1, '#ffd7c0'),
    camera: cam('pursuit', [0, 1.4, 4.2], [0, 1.1, 0], 44, {
      eyeOffset: [-2.2, 0.2, 3.1], targetOffset: [0, 0.1, 0],
      framing: { targetSlot: 'subject_1', anchor: 'center', from: [-2.0, 0.25, 3.0], to: [-1.6, 0.18, 2.4], relativeToFacing: true },
    }),
    slots: [
      model('subject_1', 'subject_1', [-7.2, 0, 0.4], { rotationY: PI / 2, motion: { to: [7.4, 0, 0.4], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-9.4, 0, -1.1], { rotationY: PI / 2, scale: 0.97, motion: { to: [5.1, 0, -1.1], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1, -10], { scale: 12 }),
    ],
    aliases: { runner: 'subject_1', pursuer: 'subject_2', backdrop: 'background' },
    texts: [title('roof-label', 'NO WAY DOWN', 'impact', 78, 18, 9, '#ffe3a0', 5.1)],
    worldSfx: [
      { id: 'grit', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 0.4 }, scale: 1.4 },
      { id: 'vent-steam', kind: 'smoke', start: 0.8, end: 6, position: { x: -6.4, y: 1.1, z: -5.2 }, color: '#9aa4b0' },
    ],
    sfx: [{ id: 'dash', kind: 'speedlines', start: 0.2, end: 6, x: 52, y: 46 }],
    copy: copy(
      { title: 'Rooftop run', description: 'A pursuit camera chases two runners across a city roof toward the helipad.', requirements: ['GLB lead runner', 'GLB pursuer', 'Optional skyline plate', 'Optional title / soundtrack'] },
      { title: 'Carrera en azotea', description: 'La cámara de persecución sigue a dos corredores por la azotea hacia el helipuerto.', requirements: ['GLB corredor principal', 'GLB perseguidor', 'Placa de skyline opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'alley-motorcycle': {
    category: 'action', duration: 5, dressing: 'chase-street',
    light: light([0.1, -0.55, 0.7], 1.7, '#ffc8a0'),
    camera: cam('side', [0, 0.85, 4.4], [0, 0.7, 0], 38, {
      eyeOffset: [4.4, -0.15, 0.7], targetOffset: [0, -0.05, 0],
      framing: { targetSlot: 'subject_1', anchor: 'center', from: [4.3, -0.1, 0.55], to: [4.3, -0.05, -0.2], relativeToFacing: true },
    }),
    slots: [
      model('subject_1', 'subject_1', [-7.2, 0, 0.2], { rotationY: PI / 2, scale: 0.85, motion: { to: [8.4, 0, 0.2], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-10.4, 0, -1.2], { rotationY: PI / 2, scale: 0.82, motion: { to: [5.6, 0, -1.2], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1, -7], { scale: 12 }),
    ],
    aliases: { rider: 'subject_1', target: 'subject_2', backdrop: 'background' },
    texts: [title('bike-label', 'HOLD ON', 'impact', 50, 80, 10, '#ffd18a', 4.4)],
    worldSfx: [
      { id: 'alley-sparks', kind: 'sparks', start: 0.4, end: 5, position: { x: -0.6, y: 0.08, z: -1.2 }, color: '#ffbb55' },
      { id: 'engine-smoke', kind: 'smoke', start: 0, end: 5, position: { x: 0, y: 0.2, z: 1.1 }, color: '#5a4a42' },
    ],
    sfx: [{ id: 'rush', kind: 'speedlines', start: 0, end: 5, x: 50, y: 50 }],
    copy: copy(
      { title: 'Alley motorcycle', description: 'A hood-mounted rush down a tight street with the target dead ahead.', requirements: ['GLB rider or bike (lead)', 'GLB target ahead', 'Optional alley plate', 'Optional title / soundtrack'] },
      { title: 'Moto en callejón', description: 'Una carrera a ras de faro por una calle estrecha con el objetivo al frente.', requirements: ['GLB piloto o moto (protagonista)', 'GLB objetivo delante', 'Placa de callejón opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'hangar-standoff': {
    category: 'action', duration: 7, dressing: 'hangar',
    light: light([-0.45, -0.8, -0.15], 2.45, '#fff0d9'),
    camera: cam('encounter', [0, 1.7, 7.4], [0, 1.15, 0], 40),
    slots: [
      model('subject_1', 'subject_1', [-5.2, 0, 1.4], { rotationY: 1.15, motion: { to: [-1.55, 0, 0.25], turnTo: 1.05, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [5.4, 0, 1.2], { rotationY: -1.15, scale: 0.98, motion: { to: [1.6, 0, 0.2], turnTo: -1.05, easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, -3.4], { scale: 1.1, grounded: true }),
      backdrop([0, 1.6, -10], { scale: 10 }),
    ],
    aliases: { agent: 'subject_1', rival: 'subject_2', crate: 'prop', backdrop: 'background' },
    texts: [title('hangar-label', 'NO DEAL', 'impact', 50, 16, 10, '#ffe3a0', 5.8)],
    worldSfx: [
      { id: 'weld', kind: 'sparks', start: 0.6, end: 6.8, position: { x: -8.2, y: 1.4, z: -4 }, color: '#ffbb55' },
      { id: 'standoff-aura', kind: 'anime_aura', start: 2.4, end: 7, position: { x: -1.55, y: 0.9, z: 0.25 }, color: '#ffe36c', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.9, z: 0 } } },
    ],
    sfx: [{ id: 'tension', kind: 'scanline', start: 0.2, end: 7, x: 50, y: 40 }],
    copy: copy(
      { title: 'Hangar standoff', description: 'Two figures close the gap inside a hangar until they freeze a few metres apart.', requirements: ['GLB agent (lead)', 'GLB rival', 'Optional crate prop', 'Optional title / soundtrack'] },
      { title: 'Enfrentamiento en hangar', description: 'Dos figuras cierran distancias en un hangar hasta quedarse a pocos metros.', requirements: ['GLB agente (protagonista)', 'GLB rival', 'Atrezzo de caja opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'train-roof': {
    category: 'action', duration: 6, dressing: 'train',
    light: light([-0.25, -0.7, 0.45], 2.15, '#e8f0ff'),
    camera: cam('side', [0, 1.4, 5.2], [0, 0.9, 0], 40, {
      eyeOffset: [6.8, 1.35, 0.8], targetOffset: [0, 0.05, 0],
    }),
    slots: [
      model('subject_1', 'subject_1', [-3.4, 0, 0.35], { rotationY: PI / 2, motion: { to: [4.2, 0, 0.35], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [5.6, 0, -0.45], { rotationY: -PI / 2, scale: 0.96, motion: { to: [-1.2, 0, -0.45], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1.2, -8], { scale: 11 }),
    ],
    aliases: { runner: 'subject_1', blocker: 'subject_2', backdrop: 'background' },
    texts: [title('train-label', 'KEEP MOVING', 'impact', 78, 16, 9, '#d7e8ff', 5.2)],
    worldSfx: [
      { id: 'rail-sparks', kind: 'sparks', start: 0, end: 6, position: { x: 0, y: -2.2, z: 0.7 }, color: '#ffbb55' },
      { id: 'wind', kind: 'smoke', start: 0.2, end: 6, position: { x: -4, y: 0.4, z: 0 }, color: '#9aa8b8' },
    ],
    sfx: [{ id: 'rush', kind: 'speedlines', start: 0.15, end: 6, x: 48, y: 44 }],
    copy: copy(
      { title: 'Train roof', description: 'Two fighters close on a moving train roof while the landscape screams past.', requirements: ['GLB lead on the roof', 'GLB opponent', 'Optional countryside plate', 'Optional title / soundtrack'] },
      { title: 'Techo del tren', description: 'Dos luchadores se cierran en el techo de un tren en marcha mientras el paisaje vuela.', requirements: ['GLB protagonista en el techo', 'GLB oponente', 'Placa de paisaje opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'desert-convoy': {
    category: 'action', duration: 8, dressing: 'desert',
    light: light([-0.55, -0.75, 0.2], 2.7, '#ffe0b0'),
    camera: cam('follow', [0.4, 2.4, 8.5], [0, 1.0, 0], 48, { eyeOffset: [0.5, 1.15, 8.2], targetOffset: [0, 0.12, 0], orbitRadius: 8.2 }),
    slots: [
      model('subject_1', 'subject_1', [-7.4, 0, 0], { rotationY: PI / 2, motion: { to: [8.6, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-10.8, 0, -2.1], { rotationY: PI / 2, scale: 0.95, motion: { to: [5.2, 0, -2.1], faceTravel: true, easing: 'linear' } }),
      model('prop', 'prop', [-13.6, 0, 1.6], { rotationY: PI / 2, scale: 1.05, motion: { to: [2.4, 0, 1.6], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1.4, -16], { scale: 14 }),
    ],
    aliases: { lead: 'subject_1', escort: 'subject_2', tanker: 'prop', backdrop: 'background' },
    texts: [title('convoy-label', 'STAY IN FORMATION', 'typewriter', 50, 84, 7, '#ffe3a0', 6.8)],
    worldSfx: [
      { id: 'wake', kind: 'dust', start: 0, end: 8, position: { x: 0, y: 0.04, z: 0 }, scale: 2.2, color: '#c9a06a' },
      { id: 'heat', kind: 'fog', start: 0, end: 8, position: { x: 0, y: 0.2, z: -6 }, scale: 2.4, color: '#e8c48a' },
    ],
    sfx: [{ id: 'glare', kind: 'sparks', start: 1.1, end: 7.2, x: 70, y: 28, size: 30 }],
    copy: copy(
      { title: 'Desert convoy', description: 'A follow cam rides three vehicles through a canyon cut in the dunes.', requirements: ['GLB lead vehicle', 'GLB escort', 'GLB tanker or third vehicle (prop)', 'Optional desert plate'] },
      { title: 'Convoy en el desierto', description: 'Una cámara de seguimiento monta tres vehículos por un cañón entre dunas.', requirements: ['GLB vehículo principal', 'GLB escolta', 'GLB cisterna o tercer vehículo (atrezzo)', 'Placa de desierto opcional'] },
    ),
  },
  'night-rain-pursuit': {
    category: 'action', duration: 7, dressing: 'chase-street',
    light: light([0.2, -0.6, -0.45], 1.55, '#c8d8ff'),
    camera: cam('front', [0, 1.25, 4.2], [0, 1.05, 0], 36, { eyeOffset: [0, -0.05, 4.2], targetOffset: [0, 0.05, 0] }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 7.4], { rotationY: PI, motion: { to: [0, 0, -3.8], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [0.85, 0, 9.6], { rotationY: PI, scale: 0.96, motion: { to: [0.7, 0, -1.6], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1, -8], { scale: 13 }),
    ],
    aliases: { quarry: 'subject_1', hunter: 'subject_2', backdrop: 'background' },
    texts: [title('rain-label', 'WET STREETS', 'rise', 50, 16, 8, '#b8d4ff', 6.2)],
    worldSfx: [
      { id: 'downpour', kind: 'rain', start: 0, end: 7, position: { x: 0, y: 0.05, z: 0 }, scale: 2.4, color: '#88bbff' },
      { id: 'flash', kind: 'lightning', start: 1.6, end: 2.4, position: { x: 2, y: 8, z: -4 }, targetPosition: { x: 0.4, y: 0.2, z: -2 }, color: '#bbddff' },
      { id: 'splash-tyre', kind: 'splash', start: 0.4, end: 7, position: { x: 0, y: 0.02, z: 2 }, scale: 1.3, color: '#9ad0ff', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.05, z: 1.2 } } },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0, end: 7, x: 50, y: 46, color: '#88bbff' }],
    copy: copy(
      { title: 'Night rain pursuit', description: 'Head-on pursuit through a flooded street as lightning hits the block.', requirements: ['GLB quarry (lead)', 'GLB hunter', 'Optional wet-street plate', 'Optional title / soundtrack'] },
      { title: 'Persecución bajo la lluvia', description: 'Persecución de frente por una calle inundada cuando cae el rayo.', requirements: ['GLB objetivo (protagonista)', 'GLB cazador', 'Placa de calle mojada opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'dock-ambush': {
    category: 'action', duration: 6, dressing: 'open-sea',
    light: light([-0.3, -0.82, 0.35], 2.05, '#ffd7c4'),
    camera: cam('establishment', [9.6, 2.5, 8.4], [7.4, 0.85, 0.2], 44),
    slots: [
      model('subject_1', 'subject_1', [4.4, 0, 1.6], { rotationY: PI / 2, motion: { to: [8.1, 0, 0.2], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [10.6, 0, -1.5], { rotationY: -1.9, scale: 0.97, motion: { to: [8.8, 0, 0.15], turnTo: -2.2, easing: 'smooth' } }),
    ],
    aliases: { walker: 'subject_1', ambusher: 'subject_2' },
    texts: [title('dock-label', 'TOO QUIET', 'typewriter', 22, 84, 7, '#ffe3a0', 5.2)],
    worldSfx: [
      { id: 'blast', kind: 'explosion', start: 3.1, end: 5.4, position: { x: 9.2, y: 0.45, z: -0.4 }, color: '#ff7040', scale: 1.7, sound: true },
      { id: 'shock', kind: 'shockwave', start: 3.2, end: 5.6, position: { x: 9.2, y: 0.03, z: -0.4 }, color: '#ff8866', scale: 1.6 },
      { id: 'spray', kind: 'splash', start: 3.15, end: 6, position: { x: 11.2, y: 0.02, z: 0 }, scale: 1.5, color: '#9ad8ff' },
    ],
    sfx: [{ id: 'hit', kind: 'manga_impact', start: 3.05, end: 4.6, x: 58, y: 48 }],
    copy: copy(
      { title: 'Dock ambush', description: 'A walk along the pier turns into an explosion as the second figure steps out.', requirements: ['GLB walker (lead)', 'GLB ambusher', 'Optional harbour plate', 'Optional title / soundtrack'] },
      { title: 'Emboscada en el muelle', description: 'Un paseo por el muelle acaba en explosión cuando sale la segunda figura.', requirements: ['GLB peatón (protagonista)', 'GLB emboscador', 'Placa de puerto opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'bridge-standoff': {
    category: 'action', duration: 6, dressing: 'rooftop',
    light: light([0.15, -0.88, -0.3], 2.25, '#e4ecff'),
    camera: cam('encounter', [7.6, 2.15, 16], [0, 1.15, 16], 40),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 8.4], { rotationY: 0, motion: { to: [0, 0, 14.2], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [0, 0, 22.6], { rotationY: PI, scale: 0.98, motion: { to: [0, 0, 17.6], faceTravel: true, easing: 'smooth' } }),
      backdrop([0, 1, 32], { scale: 12 }),
    ],
    aliases: { west: 'subject_1', east: 'subject_2', backdrop: 'background' },
    texts: [title('bridge-label', 'ONE STEP', 'rise', 50, 14, 9, '#d7e8ff', 5.4)],
    worldSfx: [
      { id: 'wind-fog', kind: 'fog', start: 0, end: 6, position: { x: 0, y: 0.1, z: 16 }, scale: 1.8, color: '#b8c4d4' },
      { id: 'coat-aura', kind: 'anime_aura', start: 2.6, end: 6, position: { x: 0, y: 0.9, z: 14.2 }, color: '#c9e7ff', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.9, z: 0 } } },
    ],
    sfx: [{ id: 'stars', kind: 'stars', start: 0.4, end: 5.8, x: 50, y: 24 }],
    copy: copy(
      { title: 'Bridge standoff', description: 'Two figures walk a skybridge from opposite ends and stop in the middle.', requirements: ['GLB west lead', 'GLB east lead', 'Optional city plate', 'Optional title / soundtrack'] },
      { title: 'Enfrentamiento en el puente', description: 'Dos figuras recorren un puente aéreo desde extremos opuestos y se detienen en el centro.', requirements: ['GLB protagonista oeste', 'GLB protagonista este', 'Placa de ciudad opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'cockpit-pursuit': {
    category: 'action', duration: 5, dressing: 'space-lane',
    environment: { reflectiveFloor: false, platform: false, bloom: 0.7 },
    light: light([0.1, -0.2, 0.9], 1.8, '#c8e4ff'),
    camera: cam('hood', [0, 1.04, -0.85], [0, 0.82, -14], 55),
    slots: [
      model('subject_1', 'subject_1', [0.12, 0.42, 0.22], { rotationY: PI, scale: 0.55, motion: { to: [0.08, 0.42, 0.18], easing: 'smooth' } }),
      model('subject_2', 'subject_2', [0.3, 1.1, -16], { scale: 0.7, motion: { to: [0.15, 0.85, -5.2], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { pilot: 'subject_1', bogey: 'subject_2' },
    texts: [title('cockpit-label', 'INCOMING', 'impact', 50, 18, 11, '#ff6a5a', 4.2)],
    worldSfx: [
      { id: 'tracer', kind: 'laser', start: 0.5, end: 4.8, position: { x: 0.4, y: 0.7, z: -0.4 }, targetPosition: { x: 0.2, y: 0.9, z: -10 }, color: '#66ffbb' },
      { id: 'lock', kind: 'energy_orb', start: 1.2, end: 4.6, position: { x: 0.15, y: 0.9, z: -8 }, color: '#ff6a5a', anchor: { slotId: 'subject_2', offset: { x: 0, y: 0.4, z: 0 } } },
    ],
    sfx: [{ id: 'hud', kind: 'scanline', start: 0, end: 5, x: 50, y: 44, color: '#ff6a5a' }],
    copy: copy(
      { title: 'Cockpit pursuit', description: 'A hood view from the cockpit as the enemy ship fills the glass.', requirements: ['GLB pilot (lead)', 'GLB enemy ship ahead', 'Optional starfield plate', 'Optional title / soundtrack'] },
      { title: 'Persecución desde cabina', description: 'Vista de cabina mientras la nave enemiga llena el cristal.', requirements: ['GLB piloto (protagonista)', 'GLB nave enemiga al frente', 'Placa de estrellas opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'helicopter-extract': {
    category: 'action', duration: 8, dressing: 'rooftop',
    light: light([-0.25, -0.9, 0.35], 2.35, '#ffe6c8'),
    camera: cam('reveal', [4.8, 8.4, 8.6], [0, 1.4, 0.4], 50),
    slots: [
      model('subject_1', 'subject_1', [6.4, 0, 3.2], { rotationY: -2.2, motion: { to: [0.4, 0, 0.7], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [0, 5.6, -1.4], { scale: 1.15, motion: { to: [0, 1.8, 0.4], easing: 'smooth' } }),
      backdrop([0, 1, -12], { scale: 12 }),
    ],
    aliases: { extractee: 'subject_1', helicopter: 'prop', backdrop: 'background' },
    texts: [title('extract-label', 'GO GO GO', 'impact', 50, 80, 10, '#ffe3a0', 6.6)],
    worldSfx: [
      { id: 'rotor-dust', kind: 'dust', start: 1.6, end: 8, position: { x: 0, y: 0.04, z: 0.5 }, scale: 2.0, color: '#8a9098' },
      { id: 'rotor-wash', kind: 'tornado', start: 2.2, end: 8, position: { x: 0, y: 0.05, z: 0.4 }, scale: 1.1, color: '#c5cdd6' },
      { id: 'flare', kind: 'sparks', start: 3.4, end: 6.2, position: { x: 2.4, y: 0.4, z: 2.2 }, color: '#ffbb55' },
    ],
    sfx: [{ id: 'wind', kind: 'speedlines', start: 2, end: 8, x: 50, y: 40 }],
    copy: copy(
      { title: 'Helicopter extract', description: 'A crane drops onto the helipad as the lead sprints in for pickup.', requirements: ['GLB extractee (lead)', 'GLB helicopter (prop)', 'Optional skyline plate', 'Optional title / soundtrack'] },
      { title: 'Extracción en helicóptero', description: 'Una grúa baja al helipuerto mientras el protagonista entra a la carrera.', requirements: ['GLB rescatado (protagonista)', 'GLB helicóptero (atrezzo)', 'Placa de skyline opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'warehouse-breach': {
    category: 'action', duration: 5, dressing: 'hangar',
    light: light([0.35, -0.7, -0.4], 2.4, '#ffd0c0'),
    camera: cam('establishment', [2.4, 2.5, -8.2], [0, 1.05, 3.4], 46),
    slots: [
      model('subject_1', 'subject_1', [-6.8, 0, 0.2], { rotationY: PI / 2, motion: { to: [0.6, 0, 0.15], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [3.4, 0, -2.2], { rotationY: -0.4, scale: 0.97, motion: { to: [4.2, 0, 1.6], turnTo: -1.4, easing: 'smooth' } }),
      backdrop([0, 1.8, -10], { scale: 10 }),
    ],
    aliases: { breacher: 'subject_1', guard: 'subject_2', backdrop: 'background' },
    texts: [title('breach-label', 'BREACH', 'impact', 50, 18, 12, '#ff6a5a', 3.8)],
    worldSfx: [
      { id: 'door-blast', kind: 'explosion', start: 0.35, end: 2.4, position: { x: 0, y: 0.5, z: 10.4 }, color: '#ff7040', scale: 1.9, sound: true },
      { id: 'ring', kind: 'shockwave', start: 0.4, end: 2.6, position: { x: 0, y: 0.03, z: 9.6 }, color: '#ff8866', scale: 1.8 },
      { id: 'smoke-bay', kind: 'smoke', start: 0.5, end: 5, position: { x: 0, y: 0.4, z: 8.8 }, color: '#6b5348', scale: 1.6 },
    ],
    sfx: [{ id: 'impact', kind: 'manga_impact', start: 0.32, end: 1.8, x: 50, y: 46 }],
    copy: copy(
      { title: 'Warehouse breach', description: 'The door blows and the lead charges the bay while a guard dives for cover.', requirements: ['GLB breacher (lead)', 'GLB guard', 'Optional warehouse plate', 'Optional title / soundtrack'] },
      { title: 'Asalto al almacén', description: 'La puerta salta y el protagonista entra mientras el guardia busca cobertura.', requirements: ['GLB asaltante (protagonista)', 'GLB guardia', 'Placa de almacén opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'canyon-run': {
    category: 'action', duration: 7, dressing: 'desert',
    light: light([-0.4, -0.65, 0.5], 2.5, '#ffd09a'),
    camera: cam('side', [0, 1.35, 4.2], [0, 0.9, 0], 44, {
      eyeOffset: [0.25, 0.7, 3.5], targetOffset: [0, 0.12, 0],
    }),
    slots: [
      model('subject_1', 'subject_1', [-8.6, 0, 0], { rotationY: PI / 2, motion: { to: [10.2, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-11.4, 0, -1.6], { rotationY: PI / 2, scale: 0.95, motion: { to: [7.6, 0, -1.6], faceTravel: true, easing: 'linear' } }),
      backdrop([0, 1.5, -14], { scale: 13 }),
    ],
    aliases: { lead: 'subject_1', tail: 'subject_2', backdrop: 'background' },
    texts: [title('canyon-label', 'NARROW MARGIN', 'impact', 78, 16, 9, '#ffe3a0', 5.8)],
    worldSfx: [
      { id: 'sand', kind: 'dust', start: 0, end: 7, position: { x: 0, y: 0.04, z: 0 }, scale: 2.0, color: '#c9a06a' },
      { id: 'ricochet', kind: 'sparks', start: 1.8, end: 6.2, position: { x: -7.4, y: 1.4, z: -2 }, color: '#ffbb55' },
      { id: 'near-miss', kind: 'shockwave', start: 4.4, end: 6.4, position: { x: 3.2, y: 0.03, z: 0 }, color: '#e8c48a', scale: 1.3 },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.2, end: 7, x: 50, y: 48 }],
    copy: copy(
      { title: 'Canyon run', description: 'Two vehicles thread a desert canyon with sand exploding off the walls.', requirements: ['GLB lead vehicle', 'GLB tailing vehicle', 'Optional canyon plate', 'Optional title / soundtrack'] },
      { title: 'Carrera en el cañón', description: 'Dos vehículos se cuelan por un cañón del desierto con la arena saltando de las paredes.', requirements: ['GLB vehículo principal', 'GLB vehículo que sigue', 'Placa de cañón opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'jungle-ambush': {
    category: 'action', duration: 6, dressing: 'jungle',
    light: light([-0.3, -0.7, 0.4], 1.7, '#c8e8b0'),
    camera: cam('encounter', [0, 1.85, 6.2], [0, 1.05, 0], 42),
    slots: [
      model('subject_1', 'subject_1', [-4.4, 0, 1.2], { rotationY: 1.1, motion: { to: [-1.3, 0, 0.3], turnTo: 1.05, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [4.6, 0, 1.1], { rotationY: -1.1, scale: 0.97, motion: { to: [1.4, 0, 0.25], turnTo: -1.05, easing: 'smooth' } }),
    ],
    aliases: { scout: 'subject_1', trap: 'subject_2' },
    texts: [title('jungle-label', 'NO PATH BACK', 'rise', 50, 16, 8, '#c8f4b0', 5.2)],
    worldSfx: [
      { id: 'canopy', kind: 'fog', start: 0, end: 6, position: { x: 0, y: 0.2, z: 0 }, scale: 2.0, color: '#8aaa70' },
      { id: 'dart', kind: 'sparks', start: 2.4, end: 5.6, position: { x: 1.2, y: 1.4, z: -2 }, color: '#ffe36c' },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0.3, end: 6, x: 50, y: 40, color: '#88ffaa' }],
    copy: copy(
      { title: 'Jungle ambush', description: 'Two figures close in a ruined clearing while the canopy swallows the light.', requirements: ['GLB scout (lead)', 'GLB ambusher', 'Optional jungle plate', 'Optional title / soundtrack'] },
      { title: 'Emboscada en la selva', description: 'Dos figuras se cierran en un claro en ruinas mientras la copa se traga la luz.', requirements: ['GLB explorador (protagonista)', 'GLB emboscador', 'Placa de selva opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'snow-compound': {
    category: 'action', duration: 8, dressing: 'snow',
    light: light([-0.5, -0.75, 0.15], 2.6, '#e8f4ff'),
    camera: cam('follow', [0.2, 2.2, 7.6], [0, 1.05, 0], 46, { eyeOffset: [0.25, 1.35, 7.4], targetOffset: [0, 0.1, 0], orbitRadius: 7.4 }),
    slots: [
      model('subject_1', 'subject_1', [-5.6, 0, 2.4], { motion: { to: [2.2, 0, -1.1], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [3.4, 0, -2.2], { scale: 0.9, grounded: true }),
    ],
    aliases: { agent: 'subject_1', lodge: 'prop' },
    texts: [title('snow-label', 'WHITEOUT', 'typewriter', 20, 84, 7, '#e8f4ff', 6.8)],
    worldSfx: [
      { id: 'flurry', kind: 'snow', start: 0, end: 8, position: { x: 0, y: 0.05, z: 0 }, scale: 2.3, color: '#e0f4ff' },
      { id: 'breath', kind: 'fog', start: 0.4, end: 8, position: { x: 0, y: 0.15, z: 0 }, scale: 1.5, color: '#d5e4f0' },
    ],
    sfx: [{ id: 'wind', kind: 'aurora', start: 0.2, end: 7.6, x: 50, y: 22 }],
    copy: copy(
      { title: 'Snow compound', description: 'An agent crosses the drift toward a lodge while snow eats the horizon.', requirements: ['GLB agent (lead)', 'Optional lodge prop', 'Optional winter plate', 'Optional title / soundtrack'] },
      { title: 'Complejo en la nieve', description: 'Un agente cruza el ventisquero hacia el refugio mientras la nieve se come el horizonte.', requirements: ['GLB agente (protagonista)', 'Atrezzo de refugio opcional', 'Placa de invierno opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'casino-heist': {
    category: 'action', duration: 7, dressing: 'casino',
    light: light([-0.35, -0.85, -0.2], 2.15, '#ffe0c0'),
    camera: cam('establishment', [5.2, 2.8, 8.6], [0, 1.0, 0.4], 40),
    slots: [
      model('subject_1', 'subject_1', [-4.8, 0, 3.4], { rotationY: PI / 2, motion: { to: [-0.6, 0, 0.4], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [5.2, 0, 2.8], { rotationY: -1.4, scale: 0.96, motion: { to: [1.5, 0, 0.5], turnTo: -1.2, easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, 0], { scale: 0.7, grounded: true }),
    ],
    aliases: { thief: 'subject_1', mark: 'subject_2', table: 'prop' },
    texts: [title('casino-label', 'ONE CHIP', 'impact', 78, 16, 9, '#f2d36b', 5.6)],
    worldSfx: [
      { id: 'glint', kind: 'sparks', start: 0.8, end: 6.4, position: { x: 0, y: 0.7, z: 0 }, color: '#f2d36b' },
      { id: 'haze', kind: 'fog', start: 0, end: 7, position: { x: 0, y: 0.08, z: 0 }, scale: 1.6, color: '#4a2030' },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0.2, end: 7, x: 50, y: 42, color: '#f2d36b' }],
    copy: copy(
      { title: 'Casino heist', description: 'Two players close on a felt table under gold light.', requirements: ['GLB thief (lead)', 'GLB mark', 'Optional table prop', 'Optional title / soundtrack'] },
      { title: 'Atraco al casino', description: 'Dos jugadores se cierran sobre una mesa de tapete bajo luz dorada.', requirements: ['GLB ladrón (protagonista)', 'GLB marca', 'Atrezzo de mesa opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'bank-vault': {
    category: 'action', duration: 6, dressing: 'hangar',
    light: light([0.2, -0.75, -0.5], 2.2, '#dce8ff'),
    camera: cam('reveal', [3.2, 4.6, 7.4], [0, 1.2, -2.2], 44),
    slots: [
      model('subject_1', 'subject_1', [-3.6, 0, 2.2], { rotationY: 0.4, motion: { to: [-0.8, 0, -0.4], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, -3.6], { scale: 1.3, grounded: true }),
    ],
    aliases: { cracksman: 'subject_1', vault: 'prop' },
    texts: [title('vault-label', 'OPEN IT', 'typewriter', 22, 84, 8, '#c8e4ff', 5.4)],
    worldSfx: [
      { id: 'torch', kind: 'sparks', start: 1.2, end: 6, position: { x: 0, y: 1.1, z: -3.4 }, color: '#ffbb55' },
      { id: 'shock', kind: 'shockwave', start: 4.4, end: 6, position: { x: 0, y: 0.03, z: -3.4 }, color: '#77ddff', scale: 1.4 },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0, end: 6, x: 50, y: 44 }],
    copy: copy(
      { title: 'Bank vault', description: 'A crane drops onto the vault as the cracksman steps in with a torch.', requirements: ['GLB cracksman (lead)', 'GLB or model for the vault (prop)', 'Optional title / soundtrack'] },
      { title: 'Cámara acorazada', description: 'Una grúa baja a la cámara mientras el ladrón entra con el soplete.', requirements: ['GLB ladrón (protagonista)', 'GLB o modelo de la cámara (atrezzo)', 'Título / banda sonora opcionales'] },
    ),
  },
  'skyscraper-ledge': {
    category: 'action', duration: 6, dressing: 'rooftop',
    light: light([-0.15, -0.6, 0.55], 2.0, '#ffd0b8'),
    camera: cam('pursuit', [0, 1.5, 4.8], [0, 1.1, 0], 46, {
      eyeOffset: [-1.5, 0.55, 4.2], targetOffset: [0, 0.08, 0],
      framing: { targetSlot: 'subject_1', anchor: 'center', from: [-1.4, 0.5, 4.1], to: [-1.1, 0.35, 3.4], relativeToFacing: true },
    }),
    slots: [
      model('subject_1', 'subject_1', [-8.2, 0, 7.2], { rotationY: PI / 2, motion: { to: [8.4, 0, 7.2], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-10.6, 0, 6.4], { rotationY: PI / 2, scale: 0.96, motion: { to: [6.1, 0, 6.4], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { runner: 'subject_1', pursuer: 'subject_2' },
    texts: [title('ledge-label', 'DO NOT LOOK DOWN', 'impact', 78, 18, 8, '#ffe3a0', 5.1)],
    worldSfx: [
      { id: 'grit', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 7.2 }, scale: 1.3 },
      { id: 'gust', kind: 'smoke', start: 0.4, end: 6, position: { x: 0, y: 0.8, z: 8.4 }, color: '#9aa4b0' },
    ],
    sfx: [{ id: 'dash', kind: 'speedlines', start: 0.15, end: 6, x: 52, y: 48 }],
    copy: copy(
      { title: 'Skyscraper ledge', description: 'A pursuit along the parapet with the city falling away.', requirements: ['GLB lead runner', 'GLB pursuer', 'Optional skyline plate', 'Optional title / soundtrack'] },
      { title: 'Cornisa del rascacielos', description: 'Una persecución por el pretil con la ciudad cayendo al vacío.', requirements: ['GLB corredor principal', 'GLB perseguidor', 'Placa de skyline opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'oil-rig': {
    category: 'action', duration: 8, dressing: 'open-sea',
    light: light([-0.45, -0.8, 0.2], 2.4, '#ffd09a'),
    camera: cam('reveal', [8.4, 6.2, 10.4], [0, 1.4, 0], 50),
    slots: [
      model('subject_1', 'subject_1', [2.2, 0, 3.4], { rotationY: PI, motion: { to: [0.2, 0, 0.5], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, -2.2], { scale: 1.2, grounded: true }),
    ],
    aliases: { worker: 'subject_1', derrick: 'prop' },
    texts: [title('rig-label', 'BLOWOUT', 'impact', 50, 16, 11, '#ff6a5a', 6.4)],
    worldSfx: [
      { id: 'flare', kind: 'fire', start: 1.4, end: 8, position: { x: 0, y: 0.2, z: -2.2 }, color: '#ff7040', scale: 1.5 },
      { id: 'spray', kind: 'splash', start: 0, end: 8, position: { x: 0, y: 0.02, z: -6 }, scale: 1.7, color: '#9ad8ff' },
    ],
    sfx: [{ id: 'heat', kind: 'sparks', start: 1.6, end: 7.4, x: 50, y: 40, size: 40 }],
    copy: copy(
      { title: 'Oil rig', description: 'A crane over open water as fire licks the derrick.', requirements: ['GLB worker (lead)', 'GLB derrick or rig prop', 'Optional title / soundtrack'] },
      { title: 'Plataforma petrolífera', description: 'Una grúa sobre mar abierto mientras el fuego lame la torre.', requirements: ['GLB operario (protagonista)', 'GLB torre o atrezzo de plataforma', 'Título / banda sonora opcionales'] },
    ),
  },
  'subway-brawl': {
    category: 'action', duration: 5, dressing: 'train',
    light: light([0.25, -0.55, -0.4], 1.65, '#c8d8ff'),
    camera: cam('front', [0, 1.2, 3.8], [0, 1.0, 0], 38, { eyeOffset: [0.35, 0.18, 3.6], targetOffset: [0, 0.04, 0] }),
    slots: [
      model('subject_1', 'subject_1', [-1.2, 0, 4.6], { rotationY: PI, motion: { to: [-0.4, 0, 0.3], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [1.3, 0, 5.2], { rotationY: PI, scale: 0.97, motion: { to: [0.5, 0, 0.4], faceTravel: true, easing: 'smooth' } }),
    ],
    aliases: { striker: 'subject_1', rival: 'subject_2' },
    texts: [title('subway-label', 'LAST STOP', 'impact', 50, 80, 10, '#ffe3a0', 4.4)],
    worldSfx: [
      { id: 'sparks', kind: 'sparks', start: 0.3, end: 5, position: { x: 0, y: -2.2, z: 0.7 }, color: '#ffbb55' },
      { id: 'hit', kind: 'shockwave', start: 2.2, end: 4.2, position: { x: 0, y: 0.03, z: 0.3 }, color: '#ff8866', scale: 1.2 },
    ],
    sfx: [{ id: 'impact', kind: 'manga_impact', start: 2.15, end: 3.6, x: 50, y: 48 }],
    copy: copy(
      { title: 'Subway brawl', description: 'Two fighters close in a rocking carriage as the rails spit sparks.', requirements: ['GLB striker (lead)', 'GLB rival', 'Optional title / soundtrack'] },
      { title: 'Pelea en el metro', description: 'Dos luchadores se cierran en un vagón mientras los raíles echan chispas.', requirements: ['GLB golpeador (protagonista)', 'GLB rival', 'Título / banda sonora opcionales'] },
    ),
  },
  'freeway-overpass': {
    category: 'action', duration: 6, dressing: 'chase-street',
    light: light([-0.2, -0.7, 0.45], 1.85, '#ffe6c8'),
    camera: cam('side', [0, 1.6, 5.4], [0, 0.9, 0], 42, { eyeOffset: [7.2, 1.75, 1.15], targetOffset: [0, 0.1, 0] }),
    slots: [
      model('subject_1', 'subject_1', [-9.2, 0, 0.3], { rotationY: PI / 2, motion: { to: [9.6, 0, 0.3], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-12.4, 0, -1.6], { rotationY: PI / 2, scale: 0.95, motion: { to: [6.8, 0, -1.6], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { lead: 'subject_1', tail: 'subject_2' },
    texts: [title('freeway-label', 'NO EXITS', 'impact', 78, 16, 9, '#ffe3a0', 5.2)],
    worldSfx: [
      { id: 'dust', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 0 }, scale: 1.6 },
      { id: 'exhaust', kind: 'smoke', start: 0.3, end: 6, position: { x: -2, y: 0.25, z: -0.8 }, color: '#6b5348' },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.1, end: 6, x: 50, y: 46 }],
    copy: copy(
      { title: 'Freeway overpass', description: 'A high side track of two vehicles under sodium lamps.', requirements: ['GLB lead vehicle', 'GLB tailing vehicle', 'Optional street plate', 'Optional title / soundtrack'] },
      { title: 'Autopista y paso elevado', description: 'Un travelling alto de dos vehículos bajo lámparas de sodio.', requirements: ['GLB vehículo principal', 'GLB vehículo que sigue', 'Placa de calle opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'prison-break': {
    category: 'action', duration: 6, dressing: 'hangar',
    light: light([0.4, -0.65, 0.2], 1.9, '#e8dcc8'),
    camera: cam('side', [0, 1.3, 5], [0, 1, 0], 40, { eyeOffset: [5.1, 0.55, -0.35], targetOffset: [0, 0.06, 0] }),
    slots: [
      model('subject_1', 'subject_1', [-6.4, 0, 0], { rotationY: PI / 2, motion: { to: [7.2, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [4.8, 0, -1.4], { rotationY: -0.4, scale: 0.97, motion: { to: [5.2, 0, 1.8], turnTo: -1.6, easing: 'smooth' } }),
    ],
    aliases: { escapee: 'subject_1', guard: 'subject_2' },
    texts: [title('prison-label', 'GO', 'impact', 50, 18, 12, '#ff6a5a', 4.6)],
    worldSfx: [
      { id: 'alarm', kind: 'lightning', start: 0.4, end: 1.4, position: { x: 0, y: 6, z: -8 }, targetPosition: { x: 0, y: 1, z: 0 }, color: '#ff8866' },
      { id: 'dust', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 0 }, scale: 1.4 },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0, end: 6, x: 50, y: 42, color: '#ff6a5a' }],
    copy: copy(
      { title: 'Prison break', description: 'The lead sprints the yard while a guard turns too late.', requirements: ['GLB escapee (lead)', 'GLB guard', 'Optional title / soundtrack'] },
      { title: 'Fuga de prisión', description: 'El protagonista cruza el patio mientras el guardia gira demasiado tarde.', requirements: ['GLB fugado (protagonista)', 'GLB guardia', 'Título / banda sonora opcionales'] },
    ),
  },
  'arctic-chase': {
    category: 'action', duration: 7, dressing: 'snow',
    light: light([-0.4, -0.6, 0.5], 2.5, '#e8f4ff'),
    camera: cam('side', [0, 1.4, 5.2], [0, 0.9, 0], 42, { eyeOffset: [0.15, 0.85, 5.8], targetOffset: [0, 0.1, 0] }),
    slots: [
      model('subject_1', 'subject_1', [-8.8, 0, 0], { rotationY: PI / 2, motion: { to: [9.4, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-11.6, 0, -1.8], { rotationY: PI / 2, scale: 0.95, motion: { to: [6.8, 0, -1.8], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { lead: 'subject_1', hunter: 'subject_2' },
    texts: [title('arctic-label', 'NO TRACKS', 'impact', 78, 16, 9, '#e8f4ff', 5.8)],
    worldSfx: [
      { id: 'snow', kind: 'snow', start: 0, end: 7, position: { x: 0, y: 0.05, z: 0 }, scale: 2.2, color: '#e0f4ff' },
      { id: 'wake', kind: 'dust', start: 0, end: 7, position: { x: 0, y: 0.04, z: 0 }, scale: 1.8, color: '#d5e4f0' },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.2, end: 7, x: 50, y: 48 }],
    copy: copy(
      { title: 'Arctic chase', description: 'Two vehicles cut a white waste while snow blinds the tail.', requirements: ['GLB lead vehicle', 'GLB hunter', 'Optional winter plate', 'Optional title / soundtrack'] },
      { title: 'Persecución ártica', description: 'Dos vehículos cortan un páramo blanco mientras la nieve ciega al que sigue.', requirements: ['GLB vehículo principal', 'GLB cazador', 'Placa de invierno opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'clock-tower': {
    category: 'action', duration: 8, dressing: 'rooftop',
    environment: { reflectiveFloor: false, platform: false, bloom: 0.45 },
    light: light([-0.25, -0.9, 0.3], 2.3, '#ffe2c4'),
    camera: cam('orbit', [0, 2.4, 7.2], [0, 1.6, 0.4], 48, { orbitRadius: 5.2, orbitHeight: 2.75, orbitTurns: 0.22 }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 0.6], { motion: { to: [0, 0, -0.2], easing: 'smooth' } }),
      model('prop', 'prop', [0, 0, -2.4], { scale: 1.15, grounded: true }),
    ],
    aliases: { climber: 'subject_1', tower: 'prop' },
    texts: [title('clock-label', 'MIDNIGHT', 'rise', 50, 14, 9, '#ffe3a0', 6.6)],
    worldSfx: [
      { id: 'gust', kind: 'smoke', start: 0, end: 8, position: { x: 0, y: 1.4, z: 0 }, color: '#9aa4b0' },
      { id: 'sparks', kind: 'sparks', start: 3.2, end: 6.8, position: { x: 0, y: 2.2, z: -2.2 }, color: '#ffbb55' },
    ],
    sfx: [{ id: 'stars', kind: 'stars', start: 0.4, end: 7.6, x: 50, y: 24 }],
    copy: copy(
      { title: 'Clock tower', description: 'An orbit around a climber on the tower as the city turns below.', requirements: ['GLB climber (lead)', 'Optional tower prop', 'Optional title / soundtrack'] },
      { title: 'Torre del reloj', description: 'Una órbita alrededor del trepador en la torre mientras la ciudad gira abajo.', requirements: ['GLB trepador (protagonista)', 'Atrezzo de torre opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'mansion-infil': {
    category: 'action', duration: 7, dressing: 'citadel',
    light: light([-0.4, -0.85, -0.25], 2.35, '#e9e3ff'),
    camera: cam('establishment', [4.1, 2.2, 7.8], [0, 1.1, -0.4], 42),
    slots: [
      model('subject_1', 'subject_1', [-3.8, 0, 2.6], { rotationY: 0.6, motion: { to: [0.2, 0, 0.3], faceTravel: true, easing: 'smooth' } }),
      model('prop', 'prop', [2.2, 0, -1.6], { scale: 0.85, grounded: true }),
    ],
    aliases: { infiltrator: 'subject_1', hall: 'prop' },
    texts: [title('mansion-label', 'LIGHTS OUT', 'typewriter', 18, 86, 7, '#d8c6ff', 6.2)],
    worldSfx: [
      { id: 'gate', kind: 'fog', start: 0, end: 7, position: { x: 0, y: 0.08, z: 0 }, scale: 1.7, color: '#8890a8' },
      { id: 'glint', kind: 'sparks', start: 2.1, end: 5.4, position: { x: 2.2, y: 1.2, z: -1.6 }, color: '#d8c6ff' },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0.3, end: 7, x: 50, y: 40, color: '#b997ff' }],
    copy: copy(
      { title: 'Mansion infil', description: 'The infiltrator crosses a marble hall toward the inner door.', requirements: ['GLB infiltrator (lead)', 'Optional hall prop', 'Optional title / soundtrack'] },
      { title: 'Infiltración en la mansión', description: 'El infiltrado cruza un salón de mármol hacia la puerta interior.', requirements: ['GLB infiltrado (protagonista)', 'Atrezzo de salón opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'cargo-hold': {
    category: 'action', duration: 6, dressing: 'hangar',
    light: light([0.15, -0.55, 0.7], 1.75, '#ffe0c4'),
    camera: cam('front', [0, 1.35, 5.2], [0, 1.05, 0], 40, { eyeOffset: [0.05, 0.42, 5.5], targetOffset: [0, 0.06, 0] }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 6.4], { rotationY: PI, motion: { to: [0, 0, -1.2], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [1.1, 0, 8.2], { rotationY: PI, scale: 0.96, motion: { to: [0.8, 0, 0.6], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { jumper: 'subject_1', crew: 'subject_2' },
    texts: [title('cargo-label', 'BAY OPEN', 'impact', 50, 18, 10, '#ffe3a0', 4.8)],
    worldSfx: [
      { id: 'wind', kind: 'smoke', start: 0.4, end: 6, position: { x: 0, y: 0.4, z: 8 }, color: '#9aa4b0', scale: 1.6 },
      { id: 'lamp', kind: 'sparks', start: 0.8, end: 6, position: { x: -6, y: 5.5, z: 0 }, color: '#ffbb55' },
    ],
    sfx: [{ id: 'rush', kind: 'speedlines', start: 0.2, end: 6, x: 50, y: 50 }],
    copy: copy(
      { title: 'Cargo hold', description: 'A head-on rush down the bay as the ramp yawns behind.', requirements: ['GLB jumper (lead)', 'GLB crew', 'Optional title / soundtrack'] },
      { title: 'Bodega de carga', description: 'Una carrera de frente por la bodega mientras la rampa se abre detrás.', requirements: ['GLB saltador (protagonista)', 'GLB tripulación', 'Título / banda sonora opcionales'] },
    ),
  },
  'jungle-river': {
    category: 'action', duration: 7, dressing: 'jungle',
    light: light([-0.35, -0.7, 0.35], 1.85, '#d0f0b8'),
    camera: cam('side', [0, 1.3, 4.8], [0, 0.9, 0], 44, { eyeOffset: [0.45, 0.75, 4.8], targetOffset: [0, 0.1, 0] }),
    slots: [
      model('subject_1', 'subject_1', [-7.4, 0, 0], { rotationY: PI / 2, motion: { to: [8.2, 0, 0], faceTravel: true, easing: 'linear' } }),
      model('subject_2', 'subject_2', [-9.8, 0, -1.4], { rotationY: PI / 2, scale: 0.95, motion: { to: [5.6, 0, -1.4], faceTravel: true, easing: 'linear' } }),
    ],
    aliases: { lead: 'subject_1', tail: 'subject_2' },
    texts: [title('river-label', 'KEEP PADDLING', 'rise', 78, 16, 8, '#c8f4b0', 6.0)],
    worldSfx: [
      { id: 'mist', kind: 'fog', start: 0, end: 7, position: { x: 0, y: 0.08, z: 0 }, scale: 2.0, color: '#8aaa70' },
      { id: 'splash', kind: 'splash', start: 0.4, end: 7, position: { x: 0, y: 0.02, z: 0 }, scale: 1.3, color: '#9ad8ff', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.05, z: 0.8 } } },
    ],
    sfx: [{ id: 'whoosh', kind: 'speedlines', start: 0.2, end: 7, x: 50, y: 48 }],
    copy: copy(
      { title: 'Jungle river', description: 'A side track of two craft sliding a misty river under the canopy.', requirements: ['GLB lead craft', 'GLB tailing craft', 'Optional jungle plate', 'Optional title / soundtrack'] },
      { title: 'Río en la selva', description: 'Un travelling de dos embarcaciones en un río de niebla bajo la copa.', requirements: ['GLB embarcación principal', 'GLB embarcación que sigue', 'Placa de selva opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'red-carpet': {
    category: 'action', duration: 6, dressing: 'casino',
    environment: { reflectiveFloor: true, platform: false, bloom: 0.55 },
    light: light([-0.3, -0.92, 0.2], 2.7, '#ffe2c4'),
    camera: cam('product', [0, 1.45, 4.6], [0, 1.15, 0], 34, { orbitRadius: 4.8, orbitHeight: 0.55, orbitTurns: 0.2 }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 2.8], { motion: { to: [0, 0, 0.2], easing: 'smooth' } }),
      model('subject_2', 'subject_2', [1.6, 0, -0.8], { rotationY: -0.4, scale: 0.92, motion: { to: [1.1, 0, -0.2], easing: 'smooth' } }),
    ],
    aliases: { star: 'subject_1', escort: 'subject_2' },
    texts: [title('carpet-label', 'AND THE WINNER', 'rise', 50, 14, 8, '#f2d36b', 5.4)],
    worldSfx: [
      { id: 'flash', kind: 'sparks', start: 0.6, end: 5.8, position: { x: 0, y: 1.2, z: 0.4 }, color: '#fff1aa' },
      { id: 'aura', kind: 'anime_aura', start: 1.4, end: 6, position: { x: 0, y: 0.9, z: 0.2 }, color: '#f2d36b', anchor: { slotId: 'subject_1', offset: { x: 0, y: 0.9, z: 0 } } },
    ],
    sfx: [{ id: 'stars', kind: 'stars', start: 0.3, end: 5.8, x: 50, y: 28 }],
    copy: copy(
      { title: 'Red carpet', description: 'A slow orbit as the star walks the gold floor into a close-up.', requirements: ['GLB star (lead)', 'Optional escort', 'Optional title / soundtrack'] },
      { title: 'Alfombra roja', description: 'Una órbita lenta mientras la estrella recorre el suelo dorado hasta el primer plano.', requirements: ['GLB estrella (protagonista)', 'Escolta opcional', 'Título / banda sonora opcionales'] },
    ),
  },
  'volcano-ridge': {
    category: 'action', duration: 7, dressing: 'desert',
    light: light([-0.5, -0.55, 0.4], 2.8, '#ffb070'),
    camera: cam('reveal', [6.8, 5.4, 9.6], [0, 1.1, 0], 48),
    slots: [
      model('subject_1', 'subject_1', [-2.4, 0, 2.2], { rotationY: 0.5, motion: { to: [0.3, 0, 0.2], faceTravel: true, easing: 'smooth' } }),
      model('subject_2', 'subject_2', [3.6, 0, -1.4], { rotationY: -0.8, scale: 0.96, motion: { to: [1.4, 0, 0.1], turnTo: -0.9, easing: 'smooth' } }),
    ],
    aliases: { climber: 'subject_1', rival: 'subject_2' },
    texts: [title('volcano-label', 'THE EDGE', 'impact', 50, 16, 10, '#ff7040', 5.8)],
    worldSfx: [
      { id: 'lava', kind: 'fire', start: 0, end: 7, position: { x: 0, y: 0.15, z: -4 }, color: '#ff7040', scale: 1.8 },
      { id: 'ash', kind: 'smoke', start: 0, end: 7, position: { x: 0, y: 0.3, z: -3 }, color: '#6b5348', scale: 1.7 },
      { id: 'burst', kind: 'explosion', start: 4.6, end: 6.8, position: { x: 2.2, y: 0.4, z: -2.4 }, color: '#ff7040', scale: 1.5, sound: true },
    ],
    sfx: [{ id: 'heat', kind: 'sparks', start: 0.4, end: 6.6, x: 50, y: 38, size: 36 }],
    copy: copy(
      { title: 'Volcano ridge', description: 'A crane over two figures on the ridge as the caldera breathes fire.', requirements: ['GLB climber (lead)', 'GLB rival', 'Optional title / soundtrack'] },
      { title: 'Cresta del volcán', description: 'Una grúa sobre dos figuras en la cresta mientras la caldera respira fuego.', requirements: ['GLB trepador (protagonista)', 'GLB rival', 'Título / banda sonora opcionales'] },
    ),
  },
  'hangar-talk': {
    category: 'action', duration: 8, dressing: 'hangar',
    light: light([-0.4, -0.78, -0.12], 2.4, '#fff0d9'),
    camera: cam('encounter', [0, 1.55, 5.6], [0, 1.28, 0.1], 38),
    slots: [
      talkingMascot('subject_1', 'subject_1', [-1.7, 0, 0.7], 'tv', { rotationY: 0.22, motion: { to: [-0.85, 0, 0.25], turnTo: 0.18, easing: 'smooth' } }),
      talkingMascot('subject_2', 'subject_2', [1.8, 0, 0.65], 'skull', { rotationY: -0.22, scale: 0.98, motion: { to: [0.9, 0, 0.2], turnTo: -0.18, easing: 'smooth' } }),
    ],
    aliases: { crt: 'subject_1', skull: 'subject_2' },
    texts: [title('talk-label', 'SAY IT', 'typewriter', 50, 14, 8, '#c8f4ff', 6.4)],
    worldSfx: [
      { id: 'weld', kind: 'sparks', start: 0.4, end: 7.6, position: { x: -7.4, y: 1.3, z: -3.6 }, color: '#ffbb55' },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0.2, end: 8, x: 50, y: 42 }],
    soundtrack: FACE_PACK_SOUNDTRACK,
    copy: copy(
      { title: 'Hangar talk', description: 'CRT-head and a basic skull face take turns on synthetic vowels, with visemes and expressions.', requirements: ['Bundled CRT-head GLB (both roles)', 'Experimental face pack', 'Neutral synthetic vowels', 'Optional title'] },
      { title: 'Charla en hangar', description: 'Cabeza CRT y un cráneo básico se turnan con vocales sintéticas, visemas y expresiones.', requirements: ['GLB CRT-head incluido (ambos papeles)', 'Face pack experimental', 'Vocales sintéticas neutras', 'Título opcional'] },
    ),
  },
  'sea-talk': {
    category: 'action', duration: 8, dressing: 'open-sea',
    light: light([-0.32, -0.82, 0.22], 2.55, '#ffe2b0'),
    camera: cam('establishment', [0.15, 1.85, 10.4], [0.04, 1.25, 5.1], 40),
    slots: [
      talkingMascot('subject_1', 'subject_1', [-1.2, 0, 5.3], 'tv', { rotationY: 0.16, motion: { to: [-0.65, 0, 4.9], turnTo: 0.12, easing: 'smooth' } }),
      talkingMascot('subject_2', 'subject_2', [1.25, 0, 5.2], 'skull', { rotationY: -0.16, scale: 0.96, motion: { to: [0.7, 0, 4.85], turnTo: -0.12, easing: 'smooth' } }),
    ],
    aliases: { crt: 'subject_1', skull: 'subject_2' },
    texts: [title('sea-talk-label', 'OPEN MIC', 'rise', 50, 14, 8, '#d7f4ff', 6.6)],
    worldSfx: [
      { id: 'spray', kind: 'splash', start: 0, end: 8, position: { x: 0, y: 0.02, z: -5.4 }, scale: 1.4, color: '#9ad8ff' },
    ],
    sfx: [{ id: 'horizon', kind: 'aurora', start: 0.2, end: 7.6, x: 50, y: 20 }],
    soundtrack: FACE_PACK_SOUNDTRACK,
    copy: copy(
      { title: 'Sea talk', description: 'The same CRT-head and skull mascots lipsync on the boat deck with a closer two-shot.', requirements: ['Bundled CRT-head GLB (both roles)', 'Experimental face pack', 'Neutral synthetic vowels', 'Optional title'] },
      { title: 'Charla en cubierta', description: 'Los mismos mascotas CRT y cráneo hacen lipsync en la cubierta, en un plano más cerrado.', requirements: ['GLB CRT-head incluido (ambos papeles)', 'Face pack experimental', 'Vocales sintéticas neutras', 'Título opcional'] },
    ),
  },
  'voxel-talk': {
    category: 'action', duration: 8, dressing: 'rooftop',
    light: light([-0.28, -0.76, 0.18], 2.35, '#ffe8c8'),
    camera: cam('encounter', [0.12, 1.48, 4.85], [0.02, 1.2, 0.08], 36),
    slots: [
      talkingMascot('subject_1', 'subject_1', [-1.55, 0, 0.55], 'voxel', { rotationY: 0.2, motion: { to: [-0.8, 0, 0.18], turnTo: 0.16, easing: 'smooth' } }),
      talkingMascot('subject_2', 'subject_2', [1.6, 0, 0.5], 'cubeskull', { rotationY: -0.2, scale: 0.98, motion: { to: [0.85, 0, 0.14], turnTo: -0.16, easing: 'smooth' } }),
    ],
    aliases: { cube: 'subject_1', skull: 'subject_2' },
    texts: [title('voxel-label', 'BLOCK TALK', 'typewriter', 50, 14, 8, '#ffe3a0', 6.2)],
    worldSfx: [
      { id: 'city-glow', kind: 'aurora', start: 0.2, end: 7.8, position: { x: 0, y: 2.4, z: -6 }, color: '#ffb070' },
    ],
    sfx: [{ id: 'scan', kind: 'scanline', start: 0.2, end: 8, x: 50, y: 38 }],
    soundtrack: FACE_PACK_SOUNDTRACK,
    copy: copy(
      { title: 'Voxel talk', description: 'A cube-head and a voxel skull take turns on the roof, anime eyes on blocky faces.', requirements: ['Bundled CRT-head GLB (both roles)', 'Voxel face packs', 'Neutral synthetic vowels', 'Optional title'] },
      { title: 'Charla voxel', description: 'Una cabeza cubo y un cráneo voxel se turnan en la azotea, ojos anime sobre caras de bloques.', requirements: ['GLB CRT-head incluido (ambos papeles)', 'Face packs voxel', 'Vocales sintéticas neutras', 'Título opcional'] },
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

export const ACTION_TEMPLATES = ACTION_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
}))

export const ACTION_CATEGORIES = Object.fromEntries(
  ACTION_TEMPLATE_IDS.map(id => [id, SPECS[id].category]),
) as Record<ActionTemplateId, 'action'>

function orientCamera(camera: Scene3DCamera, vertical: boolean): Scene3DCamera {
  const next = structuredClone(camera)
  if (!vertical) return next
  next.fov = Math.max(28, next.fov - 8)
  next.eye = [next.eye[0] * 0.72, next.eye[1] * 1.06, next.eye[2] * 0.82]
  if (!next.framing) return next
  next.framing.from = [next.framing.from[0] * 0.86, next.framing.from[1], next.framing.from[2] * 0.86]
  next.framing.to = [next.framing.to[0] * 0.86, next.framing.to[1], next.framing.to[2] * 0.86]
  return next
}

function bindSlot(slot: Scene3DSlot, roles: Partial<Record<string, string>> | undefined, aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const role = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const url = roles[slot.id] ?? (role ? roles[role] : undefined) ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

function chooseTexts(texts: KineticText[], text?: boolean | string) {
  if (text === false) return undefined
  if (typeof text !== 'string') return texts.map(cue => ({ ...cue }))
  return texts.map((cue, index) => (index === 0 ? { ...cue, text } : { ...cue }))
}

function attachAudio(doc: Scene3DDocument, audio?: Scene3DSourceRef) {
  if (!audio) return
  doc.soundtrack = [{ id: 'action-audio', audio, start: 0, offset: 0, gain: 1 }]
}

function buildDocument(spec: ActionSpec, id: ActionTemplateId, options: ActionApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.width = vertical ? 720 : 1280
  doc.height = vertical ? 1280 : 720
  doc.dressing = spec.dressing
  doc.environment = spec.environment
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = orientCamera(spec.camera, vertical)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  doc.worldSfx = parseWorldSfx(spec.worldSfx)
  doc.sfx = parseSceneFx(spec.sfx)
  doc.texts = chooseTexts(spec.texts, options.text)
  if (spec.soundtrack) doc.soundtrack = spec.soundtrack.map(track => ({ ...track, audio: { ...track.audio } }))
  attachAudio(doc, options.audio)
  return doc
}

export function applyActionTemplate(id: string, options: ActionApplyOptions = {}): Scene3DDocument | null {
  if (!isActionTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function actionTemplateDocument(id: string): Scene3DDocument | null {
  return applyActionTemplate(id)
}

export function parseActionDocument(raw: unknown): Scene3DDocument | null {
  return parseScene3DDocument(raw)
}

export function actionCard(id: string, locale: 'en' | 'es' = 'en'): ActionCardCopy | undefined {
  if (!isActionTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function actionAliases(id: string): Record<string, string> {
  return isActionTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
