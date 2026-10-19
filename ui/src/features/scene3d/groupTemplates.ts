import {
  buildCastPackDocument, cam, castPackCategories, castPackRows, copy, cutout, headFraming, KEY, light, model, person, plate,
  CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackApplyOptions, type CastPackCardCopy, type CastPackSpec,
} from './castPacks.ts'
import { GROUP_TEMPLATE_IDS, type GroupTemplateId } from './groupTemplateIds.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types.ts'

export { GROUP_TEMPLATE_IDS, type GroupTemplateId }

const PI = Math.PI
const PERSON_EN = 'GLB for each person_N prop slot; one GLB bound to person fills them all'
const PERSON_ES = 'GLB para cada hueco prop person_N; un GLB enlazado en person los llena todos'
/** The platform disc is 0.23 m tall; the performer stands on it. */
const PLATFORM_TOP = 0.232

/** Five marks on a circle, numbered from the back (subject_1 facing the camera) clockwise, each facing the centre. */
function circle(radius: number): Array<{ position: Vec3; rotationY: number }> {
  return [0, 1, 2, 3, 4].map(index => {
    const angle = PI + index * (2 * PI / 5)
    const facing = ((angle + 2 * PI) % (2 * PI)) - PI
    return { position: [Math.round(Math.sin(angle) * radius * 100) / 100, 0, Math.round(Math.cos(angle) * radius * 100) / 100], rotationY: Math.round(facing * 100) / 100 }
  })
}
const RING = circle(1.5)

/** An audience cutout faces the stage, so the camera behind it sees its back. */
const crowd = (index: number, x: number, z: number): Scene3DSlot => cutout(`crowd_${index}`, 'prop', [x, 0, z], { rotationY: PI })

const SPECS: Record<GroupTemplateId, CastPackSpec> = {
  'group-arc-five': {
    category: 'cinema', duration: 7, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.9, 6.5], [0, 1, -0.2], 42, {
      framing: headFraming('subject_1', [0, 0.35, 5.8], [0, 0.3, 5.3], { lookFrom: [0, -0.55, -0.6], lookTo: [0, -0.55, -0.6] }),
    }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, 0.9]),
      person('person_2', [-2.1, 0, -0.5]),
      person('person_3', [-0.8, 0, -1.3]),
      person('person_4', [0.8, 0, -1.3]),
      person('person_5', [2.1, 0, -0.5]),
      plate(),
    ],
    aliases: { lead: 'subject_1', background: 'background' },
    copy: copy(
      { title: 'Arc of five', description: 'One figure in front and four behind in an arc, all facing the camera, with a slow wide push. The four behind are the prop slots person_2 to person_5.', requirements: [`${CAST_EN}, front figure (subject_1)`, PERSON_EN, PLATE_EN] },
      { title: 'Arco de cinco', description: 'Una figura delante y cuatro detrás en arco, todas de cara a la cámara, con un empuje lento en plano general. Las cuatro de detrás son los huecos prop person_2 a person_5.', requirements: [`${CAST_ES}, figura delantera (subject_1)`, PERSON_ES, PLATE_ES] },
    ),
  },
  'group-line-four': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.6, 5.6], [0, 0.95, 0], 42, {
      // A truck: the eye and the look slide together, so the line passes without a pan.
      framing: headFraming('subject_1', [-0.15, 0.2, 5.6], [1.65, 0.2, 5.6], { lookFrom: [-0.15, -0.6, 0], lookTo: [1.65, -0.6, 0] }),
    }),
    slots: [
      person('person_3', [-2.25, 0, 0]),
      model('subject_1', 'subject_1', [-0.75, 0, 0]),
      model('subject_2', 'subject_2', [0.75, 0, 0]),
      person('person_4', [2.25, 0, 0]),
      plate(),
    ],
    aliases: { left: 'subject_1', right: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Line of four', description: 'Four figures in a line facing the camera, with a lateral slide at chest height. The outer two are the prop slots person_3 and person_4.', requirements: [`${CAST_EN}, inner left (subject_1)`, `${CAST_EN}, inner right (subject_2)`, PERSON_EN, PLATE_EN] },
      { title: 'Fila de cuatro', description: 'Cuatro figuras en fila de cara a la cámara, con un deslizamiento lateral a la altura del pecho. Las dos de los extremos son los huecos prop person_3 y person_4.', requirements: [`${CAST_ES}, interior izquierda (subject_1)`, `${CAST_ES}, interior derecha (subject_2)`, PERSON_ES, PLATE_ES] },
    ),
  },
  'group-audience': {
    category: 'music', duration: 7, dressing: 'citadel',
    environment: { reflectiveFloor: false, platform: true, bloom: 0.3 },
    light: light([0.1, -0.9, 0.45], 1.9, '#ffe9d0'),
    camera: cam('establishment', [0, 1.6, 6.4], [0, 1.1, 0], 40, {
      framing: headFraming('subject_1', [0, -0.2, 6.4], [0, 0.35, 6], { lookFrom: [0, -0.7, 0], lookTo: [0, -0.35, 0] }),
    }),
    slots: [
      model('subject_1', 'subject_1', [0, PLATFORM_TOP, 0], { grounded: true }),
      crowd(1, -0.9, 2.3), crowd(2, 0.9, 2.3),
      crowd(3, -2.6, 3.4), crowd(4, -0.9, 3.4), crowd(5, 0.9, 3.4), crowd(6, 2.6, 3.4),
      plate(),
    ],
    aliases: { performer: 'subject_1', background: 'background' },
    copy: copy(
      { title: 'Performer and crowd', description: 'A performer on a low platform and a crowd of six cutouts seen from behind at the bottom of the frame; the camera cranes up over the crowd toward the stage. The crowd is the prop slots crowd_1 to crowd_6; one picture bound to crowd fills them all.', requirements: [`${CAST_EN}, performer (subject_1)`, 'Image cutout of a person seen from behind for each crowd_N prop slot; one image bound to crowd fills them all', PLATE_EN] },
      { title: 'Artista y público', description: 'Un artista sobre una tarima baja y un público (crowd) de seis recortes vistos de espaldas en la parte baja del cuadro; la cámara sube en grúa por encima del público hacia el escenario. El público son los huecos prop crowd_1 a crowd_6; una imagen enlazada en crowd los llena todos.', requirements: [`${CAST_ES}, artista (subject_1)`, 'Recorte de imagen de una persona de espaldas para cada hueco prop crowd_N; una imagen enlazada en crowd los llena todos', PLATE_ES] },
    ),
  },
  'group-circle': {
    category: 'cinema', duration: 7, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 4.2, 5], [0, 0.9, 0], 40, {
      framing: headFraming('subject_1', [0, 2.7, 6.5], [0, 2.7, 6.5], { lookFrom: [0, -0.6, 1.5], lookTo: [0, -0.6, 1.5], orbitTurns: 0.1 }),
    }),
    slots: [
      model('subject_1', 'subject_1', RING[0].position, { rotationY: RING[0].rotationY }),
      model('subject_2', 'subject_2', RING[1].position, { rotationY: RING[1].rotationY }),
      person('person_3', RING[2].position, RING[2].rotationY),
      person('person_4', RING[3].position, RING[3].rotationY),
      person('person_5', RING[4].position, RING[4].rotationY),
      plate(),
    ],
    aliases: { back: 'subject_1', left: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Circle of five', description: 'Five figures in a circle facing the centre; the camera orbits slowly above them. Three of them are the prop slots person_3 to person_5.', requirements: [`${CAST_EN}, back figure (subject_1)`, `${CAST_EN}, left figure (subject_2)`, PERSON_EN, PLATE_EN] },
      { title: 'Círculo de cinco', description: 'Cinco figuras en círculo mirando al centro; la cámara orbita despacio por encima. Tres de ellas son los huecos prop person_3 a person_5.', requirements: [`${CAST_ES}, figura del fondo (subject_1)`, `${CAST_ES}, figura izquierda (subject_2)`, PERSON_ES, PLATE_ES] },
    ),
  },
}

export function isGroupTemplateId(id: string): id is GroupTemplateId {
  return (GROUP_TEMPLATE_IDS as readonly string[]).includes(id)
}

export const GROUP_TEMPLATES = castPackRows(GROUP_TEMPLATE_IDS, SPECS)
export const GROUP_CATEGORIES = castPackCategories(GROUP_TEMPLATE_IDS, SPECS)

export function applyGroupTemplate(id: string, options: CastPackApplyOptions = {}): Scene3DDocument | null {
  if (!isGroupTemplateId(id)) return null
  return buildCastPackDocument(SPECS[id], id, options)
}

export function groupTemplateDocument(id: string): Scene3DDocument | null {
  return applyGroupTemplate(id)
}

export function groupCard(id: string, locale: 'en' | 'es' = 'en'): CastPackCardCopy | undefined {
  if (!isGroupTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function groupAliases(id: string): Record<string, string> {
  return isGroupTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
