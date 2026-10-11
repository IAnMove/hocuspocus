import {
  buildCastPackDocument, cam, castPackCategories, castPackRows, copy, headFraming, KEY, model, person, plate,
  CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackApplyOptions, type CastPackCardCopy, type CastPackSpec,
} from './castPacks.ts'
import { defaultMediaScreen } from './mediaScreen.ts'
import { DIALOGUE_TEMPLATE_IDS, type DialogueTemplateId } from './dialogueTemplateIds.ts'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types.ts'

export { DIALOGUE_TEMPLATE_IDS, type DialogueTemplateId }

const PI = Math.PI
const mirror = (v: Vec3): Vec3 => [-v[0], v[1], v[2]]

/** The over-the-shoulder pair: subject_1 on the left looking right, subject_2 on the right looking left, 1.7 m apart. */
const OTS_GAP = 1.7
const otsPair = (): Scene3DSlot[] => [
  model('subject_1', 'subject_1', [-OTS_GAP / 2, 0, 0], { rotationY: PI / 2 }),
  model('subject_2', 'subject_2', [OTS_GAP / 2, 0, 0], { rotationY: -PI / 2 }),
  plate(),
]
/** Camera A sits behind subject_1's shoulder; its push is 6 % so neither speaker is still. B mirrors it in x. */
const OTS_FROM: Vec3 = [-2.4, -0.05, 0.6]
const OTS_TO: Vec3 = [-2.26, -0.05, 0.56]
const OTS_LOOK: Vec3 = [0, -0.02, 0]

/** A thin dark plane between the two halves of a split screen: a frameless screen slot that needs no media. */
const divider = (): Scene3DSlot => ({
  id: 'divider', slot: 'prop', media: 'screen', sourceUrl: '', clip: null, position: [0, 0, 0.3], rotationY: 0, scale: 1,
  screen: { ...defaultMediaScreen(), style: 'frameless', width: 0.06, height: 2.6 },
})

const SPECS: Record<DialogueTemplateId, CastPackSpec> = {
  'dialogue-ots-a': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [-2.25, 1.5, 0.75], [0.85, 1.45, 0], 36, {
      framing: headFraming('subject_2', OTS_FROM, OTS_TO, { lookFrom: OTS_LOOK, lookTo: OTS_LOOK }),
    }),
    slots: otsPair(),
    aliases: { left: 'subject_1', right: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Over the shoulder A', description: 'Two figures face each other 1.7 m apart; the camera looks over the left speaker’s shoulder onto the right one’s face, medium-close with a slow push. Use A for one speaker and B for the other: the eyelines match.', requirements: [`${CAST_EN}, left speaker (subject_1)`, `${CAST_EN}, right speaker (subject_2)`, PLATE_EN] },
      { title: 'Por encima del hombro A', description: 'Dos figuras se miran a 1,7 m; la cámara mira por encima del hombro del que habla a la izquierda hacia la cara del de la derecha, plano medio corto con empuje lento. Usa A para un interlocutor y B para el otro: las miradas casan.', requirements: [`${CAST_ES}, interlocutor izquierdo (subject_1)`, `${CAST_ES}, interlocutor derecho (subject_2)`, PLATE_ES] },
    ),
  },
  'dialogue-ots-b': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [2.25, 1.5, 0.75], [-0.85, 1.45, 0], 36, {
      framing: headFraming('subject_1', mirror(OTS_FROM), mirror(OTS_TO), { lookFrom: OTS_LOOK, lookTo: OTS_LOOK }),
    }),
    slots: otsPair(),
    aliases: { left: 'subject_1', right: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Over the shoulder B', description: 'The reverse of A: the same two figures, the camera over the right speaker’s shoulder onto the left one’s face, at the same distance and with the same push, so cutting A and B keeps the eyelines.', requirements: [`${CAST_EN}, left speaker (subject_1)`, `${CAST_EN}, right speaker (subject_2)`, PLATE_EN] },
      { title: 'Por encima del hombro B', description: 'El inverso de A: las mismas dos figuras, la cámara por encima del hombro del de la derecha hacia la cara del de la izquierda, a la misma distancia y con el mismo empuje, para que montar A y B conserve las miradas.', requirements: [`${CAST_ES}, interlocutor izquierdo (subject_1)`, `${CAST_ES}, interlocutor derecho (subject_2)`, PLATE_ES] },
    ),
  },
  'dialogue-table': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    // No framing: the encounter family slides in at seated eye height and looks between the two seats.
    camera: cam('encounter', [0, 1.15, 2.4], [0, 1.1, 0], 40),
    slots: [
      model('subject_1', 'subject_1', [-0.75, 0, 0], { rotationY: 1.25 }),
      model('subject_2', 'subject_2', [0.75, 0, 0], { rotationY: -1.25 }),
      model('table', 'prop', [0, 0, 0], { scale: 0.45, grounded: true }),
      plate(),
    ],
    aliases: { left: 'subject_1', right: 'subject_2', table: 'table', background: 'background' },
    copy: copy(
      { title: 'Seated at a table', description: 'Two figures sit across a table, three-quarter to the camera, at seated eye height (1.15 m) with a gentle slide. The cast needs a seated clip (sit_down held) or seated cutouts; bind a table GLB to the table slot.', requirements: ['GLB with a seated clip (sit_down held) or seated cutout (subject_1)', 'GLB with a seated clip (sit_down held) or seated cutout (subject_2)', 'GLB table (table, role prop)', PLATE_EN] },
      { title: 'Sentados a la mesa', description: 'Dos figuras sentadas a una mesa, en tres cuartos hacia la cámara, a la altura de los ojos de alguien sentado (1,15 m) con un deslizamiento suave. El reparto necesita un clip sentado (sit_down mantenido) o recortes sentados; enlaza un GLB de mesa en el hueco table.', requirements: ['GLB con clip sentado (sit_down mantenido) o recorte sentado (subject_1)', 'GLB con clip sentado (sit_down mantenido) o recorte sentado (subject_2)', 'GLB de mesa (table, papel prop)', PLATE_ES] },
    ),
  },
  'dialogue-triangle': {
    category: 'cinema', duration: 7, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.8, 3.8], [0, 0.9, 0], 42, {
      framing: headFraming('subject_1', [0, 0.3, 4.8], [0, 0.3, 4.8], { lookFrom: [0, -0.6, 1], lookTo: [0, -0.6, 1], orbitTurns: 0.06 }),
    }),
    slots: [
      model('subject_1', 'subject_1', [0, 0, -1]),
      model('subject_2', 'subject_2', [-1.2, 0, 0.5], { rotationY: 1.6 }),
      person('person_3', [1.2, 0, 0.5], -1.6),
      plate(),
    ],
    aliases: { back: 'subject_1', left: 'subject_2', third: 'person_3', background: 'background' },
    copy: copy(
      { title: 'Triangle of three', description: 'Three figures in a triangle: one at the back facing the camera and two in profile in front; a master shot with a slow arc. The third figure is the prop slot person_3.', requirements: [`${CAST_EN}, back figure (subject_1)`, `${CAST_EN}, left figure (subject_2)`, 'GLB, right figure (person_3, role prop)', PLATE_EN] },
      { title: 'Triángulo de tres', description: 'Tres figuras en triángulo: una al fondo de cara a la cámara y dos de perfil delante; plano general con un arco lento. La tercera figura es el hueco prop person_3.', requirements: [`${CAST_ES}, figura del fondo (subject_1)`, `${CAST_ES}, figura izquierda (subject_2)`, 'GLB, figura derecha (person_3, papel prop)', PLATE_ES] },
    ),
  },
  'dialogue-embrace': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.5, 1.9], [0, 1.45, 0], 36, {
      framing: headFraming('subject_1', [0.27, 0, 1.95], [0.27, 0, 1.7], { lookFrom: [0.27, -0.05, -0.04], lookTo: [0.27, -0.05, -0.04], orbitTurns: 0.03 }),
    }),
    slots: [
      model('subject_1', 'subject_1', [-0.27, 0, 0.04], { rotationY: 1.15 }),
      model('subject_2', 'subject_2', [0.27, 0, -0.04], { rotationY: -1.15 }),
      plate(),
    ],
    aliases: { left: 'subject_1', right: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Embrace', description: 'Two figures close together in a tight two-shot at head height, with a slow push and a shallow arc: a kiss, a hug, a farewell.', requirements: [`${CAST_EN}, left figure (subject_1)`, `${CAST_EN}, right figure (subject_2)`, PLATE_EN] },
      { title: 'Abrazo', description: 'Dos figuras muy juntas en un plano de dos cerrado a la altura de la cabeza, con empuje lento y un arco corto: un beso, un abrazo, una despedida.', requirements: [`${CAST_ES}, figura izquierda (subject_1)`, `${CAST_ES}, figura derecha (subject_2)`, PLATE_ES] },
    ),
  },
  'dialogue-phone-split': {
    category: 'cinema', duration: 6, light: KEY,
    environment: { reflectiveFloor: false, platform: false, bloom: 0.1, floorStyle: 'none' },
    // Flat colours: a neutral curve at 0 EV keeps the backdrop as authored.
    look: { toneMapping: 'neutral', exposure: 0 },
    camera: cam('establishment', [0, 1.4, 3], [0, 1.35, 0], 36, {
      framing: headFraming('subject_1', [1.25, -0.1, 3], [1.25, -0.08, 2.72], { lookFrom: [1.25, -0.12, 0], lookTo: [1.25, -0.12, 0] }),
    }),
    slots: [
      model('subject_1', 'subject_1', [-1.25, 0, 0]),
      model('subject_2', 'subject_2', [1.25, 0, 0]),
      divider(),
      plate(),
    ],
    aliases: { caller: 'subject_1', callee: 'subject_2', divider: 'divider', background: 'background' },
    backdrop: { color: '#1b2238', sfx: [] },
    copy: copy(
      { title: 'Phone split', description: 'Two figures far apart face the camera as the two halves of the frame, with a thin dark divider between them; each half a medium-close, with a slow symmetric push: a phone call, a video call.', requirements: [`${CAST_EN}, left half (subject_1)`, `${CAST_EN}, right half (subject_2)`, 'Dark divider plane (divider, role prop): a screen slot that needs no media', PLATE_EN] },
      { title: 'Llamada a pantalla partida', description: 'Dos figuras lejos una de otra miran a cámara como las dos mitades del cuadro, con un separador oscuro y fino entre ellas; cada mitad un plano medio corto, con un empuje lento y simétrico: una llamada, una videollamada.', requirements: [`${CAST_ES}, mitad izquierda (subject_1)`, `${CAST_ES}, mitad derecha (subject_2)`, 'Plano separador oscuro (divider, papel prop): un hueco de pantalla que no necesita medio', PLATE_ES] },
    ),
  },
}

export function isDialogueTemplateId(id: string): id is DialogueTemplateId {
  return (DIALOGUE_TEMPLATE_IDS as readonly string[]).includes(id)
}

export const DIALOGUE_TEMPLATES = castPackRows(DIALOGUE_TEMPLATE_IDS, SPECS)
export const DIALOGUE_CATEGORIES = castPackCategories(DIALOGUE_TEMPLATE_IDS, SPECS)

export function applyDialogueTemplate(id: string, options: CastPackApplyOptions = {}): Scene3DDocument | null {
  if (!isDialogueTemplateId(id)) return null
  return buildCastPackDocument(SPECS[id], id, options)
}

export function dialogueTemplateDocument(id: string): Scene3DDocument | null {
  return applyDialogueTemplate(id)
}

export function dialogueCard(id: string, locale: 'en' | 'es' = 'en'): CastPackCardCopy | undefined {
  if (!isDialogueTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function dialogueAliases(id: string): Record<string, string> {
  return isDialogueTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
