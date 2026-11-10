import { cam, copy, headFraming, KEY, model, person, plate, CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackSpec } from './castPacks.ts'
import type { VerticalDialogueId } from './verticalTemplateIds.ts'
import type { Scene3DCamera, Scene3DSlot, Vec3 } from './types.ts'

/** Shared by the vertical packs: a camera drawn for 9:16 is marked so no frame adapter scales it again. */
export const portraitCam = (eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  cam('establishment', eye, look, fov, { frameFormat: 'portrait', ...patch })
)
const ALIASES = { a: 'subject_1', b: 'subject_2', background: 'background' }
const pair = (left: string, right: string, leftEs: string, rightEs: string) => ({
  en: [`${CAST_EN}, ${left} (subject_1)`, `${CAST_EN}, ${right} (subject_2)`, PLATE_EN],
  es: [`${CAST_ES}, ${leftEs} (subject_1)`, `${CAST_ES}, ${rightEs} (subject_2)`, PLATE_ES],
})
const card = (spec: Omit<CastPackSpec, 'category' | 'light' | 'frame' | 'dressing' | 'aliases'> & { aliases?: Record<string, string> }): CastPackSpec => (
  { category: 'cinema', dressing: 'citadel', light: KEY, frame: 'portrait', aliases: ALIASES, ...spec }
)
const two = (a: Vec3, aYaw: number, b: Vec3, bYaw: number): Scene3DSlot[] => [
  model('subject_1', 'subject_1', a, { rotationY: aYaw }),
  model('subject_2', 'subject_2', b, { rotationY: bYaw }),
  plate(),
]
const mirror = (v: Vec3): Vec3 => [-v[0], v[1], v[2]]

/** The pair of the over-the-shoulders and the singles, 1.4 m apart: closer than the landscape pair so both fit 9:16.
 * subject_1 stands left looking right, subject_2 right looking left; every camera of the set is on the same side. */
const GAP = 1.4
const facingPair = () => two([-GAP / 2, 0, 0], Math.PI / 2, [GAP / 2, 0, 0], -Math.PI / 2)
/** Over subject_1's shoulder onto subject_2's face, high on the right; B mirrors it in x. */
const OTS = { from: [-2.45, 0.03, 0.5] as Vec3, to: [-2.3, 0.03, 0.48] as Vec3, lookFrom: [0, -0.22, -0.22] as Vec3, lookTo: [0, -0.215, -0.21] as Vec3 }
/** A clean single from in front of the other speaker's place: the face three-quarter, looking past the lens. */
const SINGLE = { from: [0.86, 0, 0.74] as Vec3, to: [0.8, 0, 0.69] as Vec3, lookFrom: [0.06, -0.06, -0.01] as Vec3, lookTo: [0.055, -0.055, -0.01] as Vec3 }
/** World dust over the locked shot, so the frame is never a photograph. */
const LOCKED_DUST = { id: 'vertical-dust', kind: 'dust', start: 0, end: 6, position: { x: 0, y: 0.03, z: 0 }, rotation: { x: 0, y: 0, z: 0 },
  scale: 2.2, intensity: 0.35, color: '#c4a574', seed: 11, sound: false, volume: 0 }
const WALK_DURATION = 7
/** No «GLB» or «caminar» here: a plain walking query keeps finding the landscape walk-and-talk first. */
const WALKERS = {
  en: ['A figure with a walk clip, in front (subject_1)', 'A figure with a walk clip, half a step behind (subject_2)', PLATE_EN],
  es: ['Una figura con un clip walk, delante (subject_1)', 'Una figura con un clip walk, medio paso detrás (subject_2)', PLATE_ES],
}
/** 2.8 m in 7 s: a stroll (0.4 m/s), well under a run. */
const WALK = 2.8

export const VERTICAL_DIALOGUE_SPECS: Record<VerticalDialogueId, CastPackSpec> = {
  'vertical-dialogue-stack': card({
    duration: 6,
    camera: portraitCam([-0.12, 1.86, 1.85], [0.24, 1.23, -0.15], 40, {
      framing: headFraming('subject_1', [-0.12, 0.38, 1.3], [-0.113, 0.357, 1.222], { lookFrom: [0.24, -0.25, -0.7], lookTo: [0.24, -0.247, -0.7] }),
    }),
    slots: two([0, 0, 0.55], 1.1, [0.5, 0, -0.65], -0.45),
    copy: copy(
      { title: 'Portrait two-shot, near and far', description: 'A 9:16 portrait two-shot in depth: subject_1 near on the left, three-quarter, subject_2 behind on the right facing the camera, one face above the other. A slow push; the lower third stays free for captions.', requirements: pair('near speaker', 'far speaker', 'interlocutor cercano', 'interlocutor lejano').en },
      { title: 'Plano de dos vertical, cerca y lejos', description: 'Plano de dos vertical 9:16 en profundidad: subject_1 cerca a la izquierda, en tres cuartos, y subject_2 detrás a la derecha de cara a cámara, una cara sobre la otra. Empuje lento; el tercio inferior queda libre para subtítulos.', requirements: pair('near speaker', 'far speaker', 'interlocutor cercano', 'interlocutor lejano').es },
    ),
  }),
  'vertical-dialogue-ots-a': card({
    duration: 6,
    camera: portraitCam([-1.75, 1.51, 0.5], [0.7, 1.26, -0.22], 36, { framing: headFraming('subject_2', OTS.from, OTS.to, { lookFrom: OTS.lookFrom, lookTo: OTS.lookTo }) }),
    slots: facingPair(),
    copy: copy(
      { title: 'Portrait over the shoulder A', description: 'A 9:16 portrait over-the-shoulder: subject_1’s shoulder fills the left edge and subject_2’s face sits high on the right, medium-close with a slow push. Cut with B for the reverse; the eyelines match.', requirements: pair('left speaker, seen from behind', 'right speaker, framed', 'interlocutor izquierdo, de espaldas', 'interlocutor derecho, encuadrado').en },
      { title: 'Por encima del hombro vertical A', description: 'Por encima del hombro en vertical 9:16: el hombro de subject_1 ocupa el borde izquierdo y la cara de subject_2 queda alta a la derecha, plano medio corto con empuje lento. Monta B para el plano inverso; las miradas casan.', requirements: pair('left speaker, seen from behind', 'right speaker, framed', 'interlocutor izquierdo, de espaldas', 'interlocutor derecho, encuadrado').es },
    ),
  }),
  'vertical-dialogue-ots-b': card({
    duration: 6,
    camera: portraitCam([1.75, 1.51, 0.5], [-0.7, 1.26, -0.22], 36, {
      framing: headFraming('subject_1', mirror(OTS.from), mirror(OTS.to), { lookFrom: OTS.lookFrom, lookTo: OTS.lookTo }),
    }),
    slots: facingPair(),
    copy: copy(
      { title: 'Portrait over the shoulder B', description: 'The reverse of A in 9:16 portrait: subject_2’s shoulder fills the right edge and subject_1’s face sits high on the left, at the same distance and with the same push, so cutting A and B keeps the eyelines.', requirements: pair('left speaker, framed', 'right speaker, seen from behind', 'interlocutor izquierdo, encuadrado', 'interlocutor derecho, de espaldas').en },
      { title: 'Por encima del hombro vertical B', description: 'El inverso de A en vertical 9:16: el hombro de subject_2 ocupa el borde derecho y la cara de subject_1 queda alta a la izquierda, a la misma distancia y con el mismo empuje, para que montar A y B conserve las miradas.', requirements: pair('left speaker, framed', 'right speaker, seen from behind', 'interlocutor izquierdo, encuadrado', 'interlocutor derecho, de espaldas').es },
    ),
  }),
  'vertical-dialogue-single-a': card({
    duration: 6,
    camera: portraitCam([0.16, 1.48, 0.74], [-0.64, 1.42, -0.01], 40, {
      framing: headFraming('subject_1', SINGLE.from, SINGLE.to, { lookFrom: SINGLE.lookFrom, lookTo: SINGLE.lookTo }),
    }),
    slots: facingPair(),
    copy: copy(
      { title: 'Portrait single A', description: 'A clean 9:16 portrait single of subject_1, medium-close, looking screen right toward subject_2 just out of frame, with a slow push. Cut with single B and the over-the-shoulders: the same side, the same eyelines.', requirements: pair('left speaker, framed', 'right speaker, out of frame', 'interlocutor izquierdo, encuadrado', 'interlocutor derecho, fuera de cuadro').en },
      { title: 'Plano individual vertical A', description: 'Plano individual limpio en vertical 9:16 de subject_1, plano medio corto, mirando a la derecha del cuadro hacia subject_2, justo fuera de campo, con empuje lento. Monta el B y los hombros: mismo lado, mismas miradas.', requirements: pair('left speaker, framed', 'right speaker, out of frame', 'interlocutor izquierdo, encuadrado', 'interlocutor derecho, fuera de cuadro').es },
    ),
  }),
  'vertical-dialogue-single-b': card({
    duration: 6,
    camera: portraitCam([-0.16, 1.48, 0.74], [0.64, 1.42, -0.01], 40, {
      framing: headFraming('subject_2', mirror(SINGLE.from), mirror(SINGLE.to), { lookFrom: mirror(SINGLE.lookFrom), lookTo: mirror(SINGLE.lookTo) }),
    }),
    slots: facingPair(),
    copy: copy(
      { title: 'Portrait single B', description: 'The reverse single in 9:16 portrait: subject_2, medium-close, looking screen left toward subject_1 just out of frame, at the same distance and push as single A.', requirements: pair('left speaker, out of frame', 'right speaker, framed', 'interlocutor izquierdo, fuera de cuadro', 'interlocutor derecho, encuadrado').en },
      { title: 'Plano individual vertical B', description: 'El individual inverso en vertical 9:16: subject_2, plano medio corto, mirando a la izquierda del cuadro hacia subject_1, justo fuera de campo, a la misma distancia y con el mismo empuje que el A.', requirements: pair('left speaker, out of frame', 'right speaker, framed', 'interlocutor izquierdo, fuera de cuadro', 'interlocutor derecho, encuadrado').es },
    ),
  }),
  'vertical-dialogue-walk': card({
    duration: WALK_DURATION,
    camera: portraitCam([-0.04, 1.54, 0.8], [-0.04, 1.28, -1.8], 40, {
      framing: headFraming('subject_1', [0.22, 0.06, 2.3], [0.2, 0.05, 2.1], { lookFrom: [0.22, -0.27, -0.3], lookTo: [0.21, -0.26, -0.3] }),
    }),
    slots: [
      model('subject_1', 'subject_1', [-0.26, 0, -1.5], { motion: { to: [-0.26, 0, -1.5 + WALK], faceTravel: true } }),
      model('subject_2', 'subject_2', [0.3, 0, -2.1], { motion: { to: [0.3, 0, -2.1 + WALK], faceTravel: true } }),
      plate(),
    ],
    copy: copy(
      { title: 'Portrait talk on the go', description: 'Two figures walk toward the camera side by side, subject_2 half a step behind, and the 9:16 portrait frame backs away with them at a stroll, both faces on the upper third. Bind a walk clip to both.', requirements: WALKERS.en },
      { title: 'Charla de camino en vertical', description: 'Dos figuras caminan hacia la cámara una junto a otra, subject_2 medio paso detrás, y el cuadro vertical 9:16 retrocede con ellas al paso, las dos caras en el tercio superior. Pon a las dos un clip walk.', requirements: WALKERS.es },
    ),
  }),
  'vertical-dialogue-across': card({
    duration: 6,
    // The feet anchor: a seated clip lowers the head, never the feet, so the frame holds for a GLB or a seated cutout.
    // The push heads for subject_2, so the near head drifts out to the left instead of over the far face.
    camera: portraitCam([-0.4, 1.55, 2.15], [0.32, 0.85, -0.55], 40, {
      framing: { ...headFraming('subject_2', [-0.85, 1.55, 2.9], [-0.8, 1.5, 2.72], { lookFrom: [-0.13, 0.85, 0.2], lookTo: [-0.13, 0.85, 0.2] }), anchor: 'feet' },
    }),
    slots: [
      model('subject_1', 'subject_1', [-0.15, 0, 0.55], { rotationY: 2.35 }),
      model('subject_2', 'subject_2', [0.45, 0, -0.75], { rotationY: -0.6 }),
      model('table', 'prop', [0.15, 0, -0.1], { scale: 0.45, grounded: true }),
      plate(),
    ],
    aliases: { ...ALIASES, table: 'table' },
    copy: copy(
      { title: 'Portrait across a table', description: 'Two figures seated across a small table in 9:16 portrait: subject_1 near on the left from behind, subject_2 beyond the table facing the camera. A slow push at seated eye height; needs a seated clip (sit_down held) or seated cutouts.', requirements: ['GLB with a seated clip (sit_down held) or seated cutout, near speaker (subject_1)', 'GLB with a seated clip (sit_down held) or seated cutout, far speaker (subject_2)', 'GLB table (table, role prop)', PLATE_EN] },
      { title: 'Mesa frente a frente en vertical', description: 'Dos figuras sentadas a una mesa en vertical 9:16: subject_1 cerca a la izquierda de espaldas, subject_2 enfrente de cara a cámara. Empuje lento a la altura de los ojos; clip sentado (sit_down mantenido) o recortes sentados.', requirements: ['GLB con clip sentado (sit_down mantenido) o recorte sentado, interlocutor cercano (subject_1)', 'GLB con clip sentado (sit_down mantenido) o recorte sentado, interlocutor lejano (subject_2)', 'GLB de mesa (table, papel prop)', PLATE_ES] },
    ),
  }),
  'vertical-dialogue-trio': card({
    duration: 7,
    camera: portraitCam([-0.15, 1.93, 2.35], [0, 1.16, -0.05], 42, {
      framing: headFraming('subject_1', [-0.1, 0.45, 1.65], [-0.094, 0.42, 1.54], { lookFrom: [0.05, -0.32, -0.75], lookTo: [0.05, -0.31, -0.75], orbitTurns: 0.025 }),
    }),
    slots: [
      model('subject_1', 'subject_1', [-0.05, 0, 0.7], { rotationY: 2.9 }),
      model('subject_2', 'subject_2', [-0.46, 0, -0.75], { rotationY: 0.5 }),
      person('person_3', [0.42, 0, -0.55], -0.55),
      plate(),
    ],
    aliases: { front: 'subject_1', left: 'subject_2', third: 'person_3', background: 'background' },
    copy: copy(
      { title: 'Portrait three in a triangle', description: 'Three figures in a 9:16 portrait triangle: subject_1 near in the middle, seen from behind, subject_2 and a third figure beyond on either side facing the camera. A slow push with a slight arc. The third figure is the prop slot person_3.', requirements: [`${CAST_EN}, front figure, from behind (subject_1)`, `${CAST_EN}, back left figure (subject_2)`, 'GLB, back right figure (person_3, role prop)', PLATE_EN] },
      { title: 'Tres en triángulo, vertical', description: 'Tres figuras en triángulo en vertical 9:16: subject_1 cerca en el centro, de espaldas, y subject_2 y una tercera figura detrás a cada lado de cara a cámara. Empuje lento con un arco leve. La tercera es el hueco prop person_3.', requirements: [`${CAST_ES}, figura delantera, de espaldas (subject_1)`, `${CAST_ES}, figura trasera izquierda (subject_2)`, 'GLB, figura trasera derecha (person_3, papel prop)', PLATE_ES] },
    ),
  }),
  'vertical-dialogue-listener': card({
    duration: 6,
    camera: portraitCam([0.2, 1.6, 1.95], [0.06, 1.34, 0.05], 40, {
      framing: headFraming('subject_2', [0.02, 0.12, 1.5], [0.02, 0.11, 1.36], { lookFrom: [-0.12, -0.14, -0.4], lookTo: [-0.12, -0.135, -0.4] }),
    }),
    slots: two([-0.3, 0, -1.0], 0.3, [0.18, 0, 0.45], -0.15),
    aliases: { speaker: 'subject_1', listener: 'subject_2', background: 'background' },
    copy: copy(
      { title: 'Portrait speaker and listener', description: 'A 9:16 portrait reaction two-shot: the listener (subject_2) near on the right facing the camera, the speaker (subject_1) behind on the left talking to them. A slow push on the listener’s face.', requirements: pair('speaker, behind', 'listener, in front', 'quien habla, detrás', 'quien escucha, delante').en },
      { title: 'Quien habla y quien escucha en vertical', description: 'Plano de dos de reacción en vertical 9:16: quien escucha (subject_2) cerca a la derecha de cara a cámara y quien habla (subject_1) detrás a la izquierda, hablándole. Empuje lento sobre la cara de quien escucha.', requirements: pair('speaker, behind', 'listener, in front', 'quien habla, detrás', 'quien escucha, delante').es },
    ),
  }),
  'vertical-dialogue-low': card({
    duration: 6,
    camera: portraitCam([0.03, 0.73, 1.95], [0, 1.36, 0], 44, {
      framing: headFraming('subject_1', [0.3, -0.75, 1.85], [0.29, -0.68, 1.7], { lookFrom: [0.27, -0.12, -0.1], lookTo: [0.27, -0.12, -0.1] }),
    }),
    slots: two([-0.27, 0, 0.1], 1.55, [0.27, 0, -0.12], -1.25),
    copy: copy(
      { title: 'Portrait low-angle two-shot', description: 'Two figures face each other, seen from below in 9:16 portrait: a low lens at hip height looks up at both faces with the ceiling or the sky behind, and creeps in. Power, a challenge, a confession.', requirements: pair('left speaker', 'right speaker', 'interlocutor izquierdo', 'interlocutor derecho').en },
      { title: 'Plano de dos en contrapicado vertical', description: 'Dos figuras frente a frente, vistas desde abajo en vertical 9:16: una lente baja a la altura de la cadera mira hacia las dos caras con el techo o el cielo detrás y se acerca despacio. Poder, un desafío, una confesión.', requirements: pair('left speaker', 'right speaker', 'interlocutor izquierdo', 'interlocutor derecho').es },
    ),
  }),
  'vertical-dialogue-high': card({
    duration: 6,
    camera: portraitCam([-0.4, 2.83, 2.5], [0.05, 0.93, -0.1], 42, {
      framing: headFraming('subject_1', [-0.25, 1.35, 1.9], [-0.23, 1.22, 1.75], { lookFrom: [0.2, -0.45, -0.7], lookTo: [0.2, -0.45, -0.7] }),
    }),
    slots: two([-0.15, 0, 0.6], 2.75, [0.25, 0, -0.8], -0.3),
    copy: copy(
      { title: 'Portrait high-angle two-shot', description: 'Two figures face each other, seen from above in 9:16 portrait: the floor is the background, subject_1 near at the bottom with the back to the camera and subject_2 beyond at the top looking up. The camera sinks slowly.', requirements: pair('near speaker, from behind', 'far speaker', 'interlocutor cercano, de espaldas', 'interlocutor lejano').en },
      { title: 'Plano de dos en picado vertical', description: 'Dos figuras frente a frente, vistas desde arriba en vertical 9:16: el suelo es el fondo, subject_1 cerca abajo y de espaldas, subject_2 al fondo arriba mirando hacia arriba. La cámara baja despacio.', requirements: pair('near speaker, from behind', 'far speaker', 'interlocutor cercano, de espaldas', 'interlocutor lejano').es },
    ),
  }),
  'vertical-dialogue-locked': card({
    duration: 6,
    // A tripod frame: the camera holds, the dust drifts and the cast's own clips do the rest.
    camera: portraitCam([0, 1.52, 2.05], [0, 1.24, 0.1], 38, {
      framing: headFraming('subject_1', [0.28, 0.04, 1.95], [0.28, 0.04, 1.95], { lookFrom: [0.28, -0.24, 0], lookTo: [0.28, -0.24, 0] }),
    }),
    slots: two([-0.28, 0, 0.1], 1.35, [0.28, 0, -0.1], -1.1),
    worldSfx: [LOCKED_DUST],
    copy: copy(
      { title: 'Portrait locked two-shot', description: 'Two figures face each other in a 9:16 portrait two-shot on a locked tripod, from the knees up, both faces on the upper third. The camera never moves; dust drifts in the air and the cast’s clips carry the shot.', requirements: pair('left speaker', 'right speaker', 'interlocutor izquierdo', 'interlocutor derecho').en },
      { title: 'Plano de dos fijo en vertical', description: 'Dos figuras frente a frente, en un plano de dos vertical 9:16 con trípode fijo, de las rodillas para arriba, las caras en el tercio superior. La cámara no se mueve; flota polvo y los clips del reparto llevan el plano.', requirements: pair('left speaker', 'right speaker', 'interlocutor izquierdo', 'interlocutor derecho').es },
    ),
  }),
}
