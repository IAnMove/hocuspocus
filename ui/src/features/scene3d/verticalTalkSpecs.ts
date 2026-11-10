import { copy, headFraming, KEY, model, plate, CAST_EN, CAST_ES, PLATE_EN, PLATE_ES, type CastPackSpec } from './castPacks.ts'
import { portraitCam } from './verticalDialogueSpecs.ts'
import type { VerticalTalkId } from './verticalTemplateIds.ts'
import type { Scene3DSlot } from './types.ts'

const ALIASES = { speaker: 'subject_1', background: 'background' }
const speaker = (patch: Partial<Scene3DSlot> = {}): Scene3DSlot[] => [model('subject_1', 'subject_1', [0, 0, 0], patch), plate()]
const requirements = (en: string, es: string) => ({ en: [`${CAST_EN}, ${en} (subject_1)`, PLATE_EN], es: [`${CAST_ES}, ${es} (subject_1)`, PLATE_ES] })
const card = (spec: Omit<CastPackSpec, 'category' | 'light' | 'frame' | 'dressing' | 'aliases'>): CastPackSpec => (
  { category: 'cinema', dressing: 'citadel', light: KEY, frame: 'portrait', aliases: ALIASES, ...spec }
)

export const VERTICAL_TALK_SPECS: Record<VerticalTalkId, CastPackSpec> = {
  'vertical-talk-bust': card({
    duration: 6,
    camera: portraitCam([0, 1.46, 1.45], [0, 1.31, 0], 40, {
      framing: headFraming('subject_1', [0, -0.02, 1.45], [0, -0.02, 1.3], { lookFrom: [0, -0.17, 0], lookTo: [0, -0.15, 0] }),
    }),
    slots: speaker({ rotationY: 0.08 }),
    copy: copy(
      { title: 'Portrait bust to camera', description: 'One figure talks straight to the lens in a 9:16 portrait bust: the eyes on the upper third, a little air over the head and the chest in the lower third for captions, with a slow push.', requirements: requirements('speaker', 'hablante').en },
      { title: 'Busto vertical a cámara', description: 'Una figura habla directamente a cámara en un busto vertical 9:16: los ojos en el tercio superior, algo de aire sobre la cabeza y el pecho en el tercio inferior para los subtítulos, con un empuje lento.', requirements: requirements('speaker', 'hablante').es },
    ),
  }),
}
