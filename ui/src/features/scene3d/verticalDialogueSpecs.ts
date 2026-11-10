import { cam, copy, headFraming, KEY, model, plate, CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackSpec } from './castPacks.ts'
import type { VerticalDialogueId } from './verticalTemplateIds.ts'
import type { Scene3DCamera, Scene3DSlot, Vec3 } from './types.ts'

/** Shared by the vertical packs: a camera drawn for 9:16 is marked so no frame adapter scales it again. */
export const portraitCam = (eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  cam('establishment', eye, look, fov, { frameFormat: 'portrait', ...patch })
)
export const VERTICAL_ALIASES = { a: 'subject_1', b: 'subject_2', background: 'background' }
export const pairRequirements = (left: string, right: string, leftEs: string, rightEs: string) => ({
  en: [`${CAST_EN}, ${left} (subject_1)`, `${CAST_EN}, ${right} (subject_2)`, PLATE_EN],
  es: [`${CAST_ES}, ${leftEs} (subject_1)`, `${CAST_ES}, ${rightEs} (subject_2)`, PLATE_ES],
})
const card = (spec: Omit<CastPackSpec, 'category' | 'light' | 'frame' | 'dressing'>): CastPackSpec => (
  { category: 'cinema', dressing: 'citadel', light: KEY, frame: 'portrait', ...spec }
)

/** The over-the-shoulder pair, 1.4 m apart: closer than the landscape pair so both fit the narrow frame. */
const OTS_GAP = 1.4
const otsPair = (): Scene3DSlot[] => [
  model('subject_1', 'subject_1', [-OTS_GAP / 2, 0, 0], { rotationY: Math.PI / 2 }),
  model('subject_2', 'subject_2', [OTS_GAP / 2, 0, 0], { rotationY: -Math.PI / 2 }),
  plate(),
]
/** Camera A behind subject_1's shoulder, a little to the camera side so that shoulder is the frame's left edge. */
const OTS_FROM: Vec3 = [-2.05, 0.04, 0.3]
const OTS_TO: Vec3 = [-1.93, 0.04, 0.28]
const OTS_LOOK_FROM: Vec3 = [0, -0.2, -0.22]
const OTS_LOOK_TO: Vec3 = [0, -0.19, -0.21]

export const VERTICAL_DIALOGUE_SPECS: Record<VerticalDialogueId, CastPackSpec> = {
  'vertical-dialogue-stack': card({
    duration: 6,
    camera: portraitCam([-0.2, 1.8, 2.45], [0.08, 1.13, -0.35], 42, {
      framing: headFraming('subject_2', [-0.5, 0.32, 3.4], [-0.47, 0.3, 3.15], { lookFrom: [-0.22, -0.35, 0.6], lookTo: [-0.22, -0.34, 0.6] }),
    }),
    slots: [
      model('subject_1', 'subject_1', [-0.22, 0, 0.7], { rotationY: 1.75 }),
      model('subject_2', 'subject_2', [0.3, 0, -0.95], { rotationY: -0.3 }),
      plate(),
    ],
    aliases: VERTICAL_ALIASES,
    copy: copy(
      { title: 'Portrait two-shot, near and far', description: 'A 9:16 portrait two-shot in depth: subject_1 near on the left in profile, subject_2 behind on the right facing the camera, one face above the other. A slow push; the lower third stays free for captions.', requirements: pairRequirements('near speaker', 'far speaker', 'interlocutor cercano', 'interlocutor lejano').en },
      { title: 'Plano de dos vertical, cerca y lejos', description: 'Plano de dos vertical 9:16 en profundidad: subject_1 cerca a la izquierda de perfil y subject_2 detrás a la derecha de cara a cámara, una cara sobre la otra, hablando. Empuje lento; el tercio inferior queda libre para subtítulos.', requirements: pairRequirements('near speaker', 'far speaker', 'interlocutor cercano', 'interlocutor lejano').es },
    ),
  }),
  'vertical-dialogue-ots-a': card({
    duration: 6,
    camera: portraitCam([-1.35, 1.52, 0.3], [0.7, 1.28, -0.22], 42, {
      framing: headFraming('subject_2', OTS_FROM, OTS_TO, { lookFrom: OTS_LOOK_FROM, lookTo: OTS_LOOK_TO }),
    }),
    slots: otsPair(),
    aliases: VERTICAL_ALIASES,
    copy: copy(
      { title: 'Portrait over the shoulder A', description: 'A 9:16 portrait over-the-shoulder: subject_1’s shoulder fills the left edge and subject_2’s face sits high on the right, medium-close with a slow push. Cut with B for the reverse; the eyelines match.', requirements: pairRequirements('left speaker, seen from behind', 'right speaker, framed', 'interlocutor izquierdo, de espaldas', 'interlocutor derecho, encuadrado').en },
      { title: 'Por encima del hombro vertical A', description: 'Por encima del hombro en vertical 9:16: el hombro de subject_1 ocupa el borde izquierdo y la cara de subject_2 queda alta a la derecha, hablando, plano medio corto con empuje lento. Monta B para el contraplano; las miradas casan.', requirements: pairRequirements('left speaker, seen from behind', 'right speaker, framed', 'interlocutor izquierdo, de espaldas', 'interlocutor derecho, encuadrado').es },
    ),
  }),
}
