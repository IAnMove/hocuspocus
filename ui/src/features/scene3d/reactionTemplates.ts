import {
  buildCastPackDocument, cam, castPackCategories, castPackRows, copy, headFraming, KEY, model, plate,
  CAST_EN, CAST_ES, CAST_PACK_FPS, PLATE_EN, PLATE_ES, type CastPackApplyOptions, type CastPackCardCopy, type CastPackSpec,
} from './castPacks.ts'
import { REACTION_TEMPLATE_IDS, type ReactionTemplateId } from './reactionTemplateIds.ts'
import type { Scene3DDocument, Scene3DSlot } from './types.ts'

export { REACTION_TEMPLATE_IDS, type ReactionTemplateId }

const frames = (count: number) => count / CAST_PACK_FPS
const subject = (patch: Partial<Scene3DSlot> = {}): Scene3DSlot[] => [model('subject_1', 'subject_1', [0, 0, 0], patch), plate()]
const ALIASES = { subject: 'subject_1', background: 'background' }
const requirements = (en: string, es: string) => ({ en: [`${CAST_EN} (subject_1)${en}`, PLATE_EN], es: [`${CAST_ES} (subject_1)${es}`, PLATE_ES] })

/** The hit lands here: the shake, the white frames and the snap push all start on it. */
const HIT = 1.6
const IMPACT_DURATION = 5

const SPECS: Record<ReactionTemplateId, CastPackSpec> = {
  'reaction-push-face': {
    category: 'cinema', duration: 5, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.45, 1.9], [0, 1.42, 0], 36, {
      framing: headFraming('subject_1', [0, -0.08, 2.1], [0, -0.03, 1.25], { lookFrom: [0, -0.12, 0], lookTo: [0, -0.04, 0], moveStart: 0.2 }),
    }),
    slots: subject({ rotationY: 0.12 }),
    aliases: ALIASES,
    copy: copy(
      { title: 'Push on the face', description: 'One figure; after a short hold the camera pushes slowly from a medium-close to a close-up on the face.', requirements: requirements('', '').en },
      { title: 'Empuje a la cara', description: 'Una figura; tras una pausa breve la cámara empuja despacio desde un plano medio corto hasta un primer plano de la cara.', requirements: requirements('', '').es },
    ),
  },
  'reaction-orbit-face': {
    category: 'cinema', duration: 6, dressing: 'citadel', light: KEY,
    camera: cam('orbit', [0, 1.5, 1.35], [0, 1.45, 0], 36, {
      orbitRadius: 1.35, orbitHeight: 0.4, orbitTurns: 0.12,
      framing: headFraming('subject_1', [0, 0, 1.35], [0, 0, 1.35], { lookFrom: [0, -0.03, 0], lookTo: [0, -0.03, 0], orbitTurns: 0.12 }),
    }),
    slots: subject(),
    aliases: ALIASES,
    copy: copy(
      { title: 'Orbit on the face', description: 'A slow arc of a tenth of a turn around the head at close distance; the face stays framed while the place turns behind it.', requirements: requirements('', '').en },
      { title: 'Arco sobre la cara', description: 'Un arco lento de una décima de vuelta alrededor de la cabeza a corta distancia; la cara sigue encuadrada mientras el lugar gira detrás.', requirements: requirements('', '').es },
    ),
  },
  'reaction-turn-to-camera': {
    category: 'cinema', duration: 5, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 1.5, 1.55], [0, 1.45, 0], 36, {
      framing: headFraming('subject_1', [0, -0.04, 1.6], [0, -0.03, 1.46], { lookFrom: [0, -0.05, 0], lookTo: [0, -0.05, 0] }),
    }),
    // A turn in place: the path ends where it starts, only the heading changes.
    slots: subject({ rotationY: 1.35, motion: { to: [0, 0, 0], turnTo: 0, easing: 'smooth' } }),
    aliases: ALIASES,
    copy: copy(
      { title: 'Turn to camera', description: 'The figure turns in place from profile to face the camera while the camera holds close with a tiny push.', requirements: requirements(', turned by the shot', ', girado por el plano').en },
      { title: 'Giro a cámara', description: 'La figura gira sobre sí misma, de perfil a mirar a cámara, mientras la cámara aguanta cerca con un empuje mínimo.', requirements: requirements(', turned by the shot', ', girado por el plano').es },
    ),
  },
  'reaction-look-up': {
    category: 'cinema', duration: 5, dressing: 'citadel', light: KEY,
    camera: cam('establishment', [0, 0.8, 1.5], [0, 1.35, 0], 38, {
      framing: headFraming('subject_1', [0, -0.75, 1.5], [0, -0.42, 1.25], { lookFrom: [0, -0.45, 0], lookTo: [0, -0.02, 0] }),
    }),
    slots: subject({ rotationY: 0.1 }),
    aliases: ALIASES,
    copy: copy(
      { title: 'Look up', description: 'A low angle on the face that rises and tilts up as it pushes in, close.', requirements: requirements('', '').en },
      { title: 'Contrapicado a la cara', description: 'Un contrapicado sobre la cara que sube e inclina hacia arriba mientras empuja, cerca.', requirements: requirements('', '').es },
    ),
  },
  'reaction-impact': {
    category: 'cinema', duration: IMPACT_DURATION, light: KEY,
    environment: { reflectiveFloor: false, platform: false, bloom: 0.1, floorStyle: 'none' },
    // Plain colours: a neutral curve at 0 EV keeps the backdrop as authored.
    look: { toneMapping: 'neutral', exposure: 0 },
    camera: cam('establishment', [0, 1.45, 1.8], [0, 1.42, 0], 36, {
      framing: headFraming('subject_1', [0, -0.1, 2], [0, -0.03, 1.2], {
        lookFrom: [0, -0.12, 0], lookTo: [0, -0.04, 0], moveStart: HIT / IMPACT_DURATION, moveEnd: HIT / IMPACT_DURATION + 0.08, ease: 'snap',
      }),
      shake: [{ start: HIT, end: HIT + 0.55, amplitude: 0.07, frequency: 18, seed: 7, decay: 4 }],
    }),
    slots: subject({ rotationY: 0.1 }),
    aliases: ALIASES,
    backdrop: { color: '#2b1530', sfx: [] },
    sfx: [{ id: 'hit-flash', kind: 'impact_flash', start: HIT, end: HIT + frames(2), x: 50, y: 40, size: 70 }],
    copy: copy(
      { title: 'Impact on the face', description: 'A hit lands: two white frames, a short shake and a snap push to the face over plain colours.', requirements: requirements('', '').en },
      { title: 'Impacto en la cara', description: 'Llega el golpe: dos fotogramas blancos, una sacudida corta y un empuje brusco a la cara sobre colores planos.', requirements: requirements('', '').es },
    ),
  },
}

export function isReactionTemplateId(id: string): id is ReactionTemplateId {
  return (REACTION_TEMPLATE_IDS as readonly string[]).includes(id)
}

export const REACTION_TEMPLATES = castPackRows(REACTION_TEMPLATE_IDS, SPECS)
export const REACTION_CATEGORIES = castPackCategories(REACTION_TEMPLATE_IDS, SPECS)

export function applyReactionTemplate(id: string, options: CastPackApplyOptions = {}): Scene3DDocument | null {
  if (!isReactionTemplateId(id)) return null
  return buildCastPackDocument(SPECS[id], id, options)
}

export function reactionTemplateDocument(id: string): Scene3DDocument | null {
  return applyReactionTemplate(id)
}

export function reactionCard(id: string, locale: 'en' | 'es' = 'en'): CastPackCardCopy | undefined {
  if (!isReactionTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function reactionAliases(id: string): Record<string, string> {
  return isReactionTemplateId(id) ? { ...SPECS[id].aliases } : {}
}

/** The authored screen cue kinds before parsing, so a check can prove none was dropped as unknown. */
export function reactionAuthoredCueKinds(id: string): string[] {
  return isReactionTemplateId(id) ? (SPECS[id].sfx ?? []).map(cue => String(cue.kind)) : []
}
