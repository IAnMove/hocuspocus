import { copy, headFraming, KEY, model, plate, CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackSpec } from './castPacks.ts'
import { portraitCam } from './verticalDialogueSpecs.ts'
import type { VerticalTalkId } from './verticalTemplateIds.ts'
import type { Scene3DSlot } from './types.ts'

const ALIASES = { speaker: 'subject_1', background: 'background' }
const speaker = (patch: Partial<Scene3DSlot> = {}): Scene3DSlot[] => [model('subject_1', 'subject_1', [0, 0, 0], patch), plate()]
const requirements = (en: string, es: string) => ({ en: [`${CAST_EN}, ${en} (subject_1)`, PLATE_EN], es: [`${CAST_ES}, ${es} (subject_1)`, PLATE_ES] })
const SPEAKER = requirements('speaker', 'hablante')
const card = (spec: Omit<CastPackSpec, 'category' | 'light' | 'frame' | 'dressing' | 'aliases'>): CastPackSpec => (
  { category: 'cinema', dressing: 'citadel', light: KEY, frame: 'portrait', aliases: ALIASES, ...spec }
)

export const VERTICAL_TALK_SPECS: Record<VerticalTalkId, CastPackSpec> = {
  'vertical-talk-bust': card({
    duration: 6,
    camera: portraitCam([0, 1.48, 1.12], [0, 1.43, 0], 40, {
      framing: headFraming('subject_1', [0, 0, 1.12], [0, 0, 1], { lookFrom: [0, -0.05, 0], lookTo: [0, -0.045, 0] }),
    }),
    slots: speaker({ rotationY: 0.08 }),
    copy: copy(
      { title: 'Portrait to camera, chest up', description: 'One figure talks straight to the lens in a 9:16 portrait bust: the eyes on the upper third, a little air over the head and the chest in the lower third for captions, with a slow push.', requirements: SPEAKER.en },
      { title: 'A cámara en vertical, hasta el pecho', description: 'Una figura habla directamente a cámara en un busto vertical 9:16: los ojos en el tercio superior, algo de aire sobre la cabeza y el pecho en el tercio inferior para los subtítulos, con un empuje lento.', requirements: SPEAKER.es },
    ),
  }),
  'vertical-talk-caption': card({
    duration: 6,
    camera: portraitCam([-0.11, 1.48, 1.65], [0, 1.3, 0], 40, {
      framing: headFraming('subject_1', [-0.11, 0, 1.65], [0.09, 0, 1.6], { lookFrom: [0, -0.18, 0], lookTo: [0, -0.18, 0] }),
    }),
    slots: speaker({ rotationY: 0.05 }),
    copy: copy(
      { title: 'Portrait medium with room for captions', description: 'One figure talks to camera from the waist up in 9:16 portrait, the face high in the frame and the whole lower third free for captions or a title, while the camera slides a little sideways.', requirements: SPEAKER.en },
      { title: 'Plano medio vertical con sitio para subtítulos', description: 'Una figura habla a cámara de cintura para arriba en vertical 9:16, con la cara alta en el cuadro y todo el tercio inferior libre para subtítulos o un rótulo, mientras la cámara se desliza un poco de lado.', requirements: SPEAKER.es },
    ),
  }),
  'vertical-talk-three-quarter': card({
    duration: 6,
    camera: portraitCam([0, 1.48, 1.25], [-0.07, 1.4, 0], 40, {
      framing: headFraming('subject_1', [0, 0, 1.25], [0, 0, 1.2], { lookFrom: [-0.07, -0.08, 0], lookTo: [-0.07, -0.08, 0], orbitTurns: 0.03 }),
    }),
    slots: speaker({ rotationY: -0.6 }),
    copy: copy(
      { title: 'Portrait three-quarter talk', description: 'One figure turned three-quarter to the lens talks in a 9:16 portrait medium-close, the eyes on the upper third; the camera arcs slowly toward the face.', requirements: SPEAKER.en },
      { title: 'Tres cuartos en vertical', description: 'Una figura girada en tres cuartos habla en un plano medio corto vertical 9:16, con los ojos en el tercio superior; la cámara traza un arco lento hacia la cara.', requirements: SPEAKER.es },
    ),
  }),
  'vertical-talk-low': card({
    duration: 6,
    camera: portraitCam([0, 0.93, 1.35], [0, 1.39, 0], 42, {
      framing: headFraming('subject_1', [0, -0.55, 1.35], [0, -0.47, 1.22], { lookFrom: [0, -0.09, 0], lookTo: [0, -0.11, 0] }),
    }),
    slots: speaker({ rotationY: 0.06 }),
    copy: copy(
      { title: 'Portrait low-angle talk', description: 'One figure talks seen from below in 9:16 portrait: a low lens at chest height looks up at the face and rises a little as it creeps in. Authority, a speech, a threat.', requirements: SPEAKER.en },
      { title: 'Contrapicado en vertical', description: 'Una figura habla vista desde abajo en vertical 9:16: una lente baja a la altura del pecho mira hacia la cara y sube un poco mientras se acerca. Autoridad, un discurso, una amenaza.', requirements: SPEAKER.es },
    ),
  }),
  'vertical-talk-push': card({
    duration: 6,
    camera: portraitCam([0, 1.48, 1.75], [0, 1.31, 0], 40, {
      framing: headFraming('subject_1', [0, 0, 1.75], [0, 0, 1], { lookFrom: [0, -0.17, 0], lookTo: [0, -0.045, 0], moveStart: 0.1 }),
    }),
    slots: speaker({ rotationY: 0.04 }),
    copy: copy(
      { title: 'Portrait slow push to the face', description: 'One figure talks to camera while the 9:16 portrait frame pushes slowly from the waist to the face, keeping the eyes on the upper third the whole way.', requirements: SPEAKER.en },
      { title: 'Empuje lento vertical a la cara', description: 'Una figura habla a cámara mientras el cuadro vertical 9:16 empuja despacio desde la cintura hasta la cara, con los ojos en el tercio superior todo el tiempo.', requirements: SPEAKER.es },
    ),
  }),
  'vertical-talk-side': card({
    duration: 6,
    camera: portraitCam([-0.18, 1.48, 1.3], [0.12, 1.41, 0], 40, {
      framing: headFraming('subject_1', [-0.18, 0, 1.3], [-0.06, 0, 1.28], { lookFrom: [0.12, -0.07, 0], lookTo: [0.12, -0.07, 0] }),
    }),
    slots: speaker({ rotationY: 0.62 }),
    copy: copy(
      { title: 'Portrait talk to someone off frame', description: 'One figure talks to someone off frame, as in an interview: in 9:16 portrait the face sits left with room to look into on the right, and the camera slides slowly the same way.', requirements: SPEAKER.en },
      { title: 'Hablar a alguien fuera de cuadro, vertical', description: 'Una figura habla con alguien fuera de cuadro, como en una entrevista: en vertical 9:16 la cara queda a la izquierda con aire a la derecha hacia donde mira, y la cámara se desliza despacio en ese sentido.', requirements: SPEAKER.es },
    ),
  }),
}
