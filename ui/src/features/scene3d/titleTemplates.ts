import { createDefaultScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame } from './frameFormat.ts'
import { parseScreenBackdrop } from './screenBackdrop.ts'
import { parseSceneFx } from '../sceneFx/types.ts'
import { TITLE_TEMPLATE_IDS, type TitleTemplateId } from './titleTemplateIds.ts'
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

export { TITLE_TEMPLATE_IDS, type TitleTemplateId }

export type TitleOrientation = 'horizontal' | 'vertical'
export type TitleApplyOptions = {
  orientation?: TitleOrientation
  /** Source URLs by slot id, alias or role. */
  roles?: Partial<Record<string, string>>
  /** The main line. The kinetic stage splits it into one word per beat. */
  text?: string
  /** The second line: the role under a name, the kicker over a chapter, the call to action of an end card. */
  subtext?: string
}
export type TitleCardCopy = { title: string; description: string; requirements: string[] }

type TitleSpec = {
  duration: number
  environment: NonNullable<Scene3DDocument['environment']>
  light: Scene3DLight
  camera: Scene3DCamera
  slots: Scene3DSlot[]
  aliases: Record<string, string>
  backdrop: { color: string; sfx: Array<Record<string, unknown>> }
  sfx: Array<Record<string, unknown>>
  /** The main line first, the second line next; later cues are decoration. */
  texts: KineticText[]
  /** The texts are one word per beat; `text` replaces the words, keeping the first cue's look and the beat grid. */
  beatWords?: true
  copy: { en: TitleCardCopy; es: TitleCardCopy }
}

const FPS = 24
/** A full-body cutout this size is about 1.9 m tall; a GLB in the same slot is fitted to 1.6 m. */
const FIGURE = 0.95
const MAX_BEAT_WORDS = 8

const cutout = (id: string, slot: Scene3DSlotId, position: Vec3, patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot, media: 'image', surface: 'cutout', imageLook: { unlit: true }, sourceUrl: '', clip: null,
  position, rotationY: 0, scale: FIGURE, ...patch,
})
const cam = (family: Scene3DCameraFamily, eye: Vec3, look: Vec3, fov: number, patch: Partial<Scene3DCamera> = {}): Scene3DCamera => (
  { family, eye, look, fov, ...patch }
)
const KEY: Scene3DLight = { kind: 'directional', direction: [-0.35, -0.85, -0.4], intensity: 1.5, color: '#fff6ea' }
const FLOOR_OFF: TitleSpec['environment'] = { reflectiveFloor: false, platform: false, bloom: 0.12, floorStyle: 'none' }
const copy = (en: TitleCardCopy, es: TitleCardCopy) => ({ en, es })
const text = (id: string, value: string, start: number, end: number, patch: Partial<KineticText>): KineticText => (
  { id, text: value, start, end, preset: 'rise', x: 50, y: 50, size: 8, color: '#ffffff', rotation: 0, ...patch }
)

/** The big word of the kinetic stage; every beat reuses this look. */
const BEAT_WORD: Partial<KineticText> = {
  preset: 'impact', x: 50, y: 34, size: 20, color: '#f5f5f7', font: 'display', weight: 900, uppercase: true,
  enter: { preset: 'impact', duration: 0.18 }, exit: { preset: 'fade', duration: 0.2 },
}
/** Words land on an even grid between `lead` and `end`. */
function beatCues(words: string[], look: Partial<KineticText>, lead: number, end: number): KineticText[] {
  const beat = (end - lead) / words.length
  return words.map((word, index) => text(`beat-${index + 1}`, word, lead + index * beat, lead + (index + 1) * beat, look))
}

const CUTOUT_EN = 'Image cutout or GLB (subject, optional)'
const CUTOUT_ES = 'Recorte de imagen o GLB (protagonista, opcional)'

const SPECS: Record<TitleTemplateId, TitleSpec> = {
  'title-lower-third': {
    duration: 5, environment: FLOOR_OFF, light: KEY,
    // The lens looks left of the figure, which sits right of centre and leaves the lower left for the text.
    camera: cam('establishment', [-0.45, 1.5, 2.9], [-0.45, 1.4, 0], 38, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [-0.45, -0.2, 2.9], to: [-0.45, -0.18, 2.6], lookFrom: [-0.45, -0.3, 0], lookTo: [-0.45, -0.3, 0], ease: 'smooth',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#30343e', sfx: [] },
    sfx: [],
    texts: [
      text('name', 'ALEX RIVERA', 0.4, 4.6, {
        x: 6, y: 78, size: 6.5, font: 'condensed', weight: 700, align: 'left', uppercase: true, letterSpacing: 0.04,
        enter: { preset: 'slide-left', duration: 0.5 }, exit: { preset: 'slide-left', duration: 0.4 },
        box: { kind: 'bar', color: '#1b1f2a', opacity: 0.85, padding: 0.5 },
      }),
      text('role', 'Field producer · Madrid', 0.7, 4.6, {
        x: 6, y: 85.5, size: 3.6, color: '#e8ebf2', font: 'sans', weight: 500, align: 'left',
        enter: { preset: 'slide-left', duration: 0.5 }, exit: { preset: 'slide-left', duration: 0.35 },
        box: { kind: 'underline', color: '#ffcf3a', opacity: 1, padding: 0.3 },
      }),
    ],
    copy: copy(
      { title: 'Lower third', description: 'A name on a bar and a role line slide in from the left, hold under the figure and slide out, over a slow push.', requirements: ['Name (text) and role line (subtext)', CUTOUT_EN] },
      { title: 'Rótulo inferior', description: 'Un nombre sobre una barra y una línea de cargo entran deslizándose por la izquierda, aguantan bajo la figura y salen, sobre un empuje lento.', requirements: ['Nombre (text) y cargo (subtext)', CUTOUT_ES] },
    ),
  },
  'title-kinetic-stage': {
    duration: 6, environment: { reflectiveFloor: true, platform: false, bloom: 0.2, floorStyle: 'mirror' }, light: KEY,
    camera: cam('establishment', [0, 1.5, 5.8], [0, 1.4, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.5, 5.8], to: [0, -0.46, 4.9], lookFrom: [0, -0.55, 0], lookTo: [0, -0.5, 0], ease: 'smooth',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#0b0d12', sfx: [] },
    sfx: [{ id: 'stage-light', kind: 'light_rays', start: 0, end: 6, x: 50, y: 0, size: 140, rotation: 90, intensity: 0.6, color: '#9aa8ff' }],
    texts: beatCues(['ONE', 'WORD', 'PER', 'BEAT'], BEAT_WORD, 0.3, 5.7),
    beatWords: true,
    copy: copy(
      { title: 'Kinetic stage', description: 'One big word per beat punches in over a dark mirror stage under a shaft of light, with a slow push on the figure. The line splits into words, up to eight.', requirements: ['The line (text), one word per beat', CUTOUT_EN] },
      { title: 'Escenario cinético', description: 'Una palabra grande por tiempo golpea sobre un escenario oscuro de espejo bajo un haz de luz, con un empuje lento sobre la figura. La frase se parte en palabras, hasta ocho.', requirements: ['La frase (text), una palabra por tiempo', CUTOUT_ES] },
    ),
  },
  'title-chapter': {
    duration: 4, environment: FLOOR_OFF, light: KEY,
    camera: cam('establishment', [0, 1.5, 4.6], [0, 1.4, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [0, -0.3, 4.6], to: [0, -0.28, 4.2], lookFrom: [0, -0.4, 0], lookTo: [0, -0.4, 0], ease: 'smooth',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#141720', sfx: [] },
    sfx: [{ id: 'card-vignette', kind: 'vignette', start: 0, end: 4, x: 50, y: 50, size: 55, intensity: 1.1, color: '#000000' }],
    texts: [
      text('title', 'THE ARRIVAL', 0.9, 3.8, {
        preset: 'impact', y: 52, size: 12, font: 'serif', weight: 700, uppercase: true, letterSpacing: 0.06,
        enter: { preset: 'wipe', duration: 0.7 }, exit: { preset: 'fade', duration: 0.3 },
      }),
      text('kicker', 'CHAPTER ONE', 0.3, 3.7, {
        y: 38, size: 3.4, color: '#cfd3dc', font: 'sans', weight: 600, uppercase: true, letterSpacing: 0.3,
        enter: { preset: 'letters', duration: 0.6 }, exit: { preset: 'fade', duration: 0.3 },
      }),
      text('rule', '————————', 0.6, 3.75, {
        y: 44, size: 3, color: '#ffcf3a', font: 'sans', weight: 400, letterSpacing: -0.1,
        enter: { preset: 'wipe', duration: 0.7 }, exit: { preset: 'fade', duration: 0.3 },
      }),
    ],
    copy: copy(
      { title: 'Chapter card', description: 'A centred chapter card: the kicker types in, a rule draws itself and the title wipes on, over a vignette and a slow push.', requirements: ['Chapter title (text) and kicker (subtext)', CUTOUT_EN] },
      { title: 'Cartela de capítulo', description: 'Cartela de capítulo centrada: el antetítulo se teclea, una línea se dibuja sola y el título entra con un barrido, sobre una viñeta y un empuje lento.', requirements: ['Título del capítulo (text) y antetítulo (subtext)', CUTOUT_ES] },
    ),
  },
  'title-end-card': {
    duration: 5, environment: FLOOR_OFF, light: KEY,
    camera: cam('establishment', [-0.25, 1.5, 4.2], [-0.1, 1.4, 0], 40, {
      framing: {
        targetSlot: 'subject', anchor: 'head', relativeToFacing: false,
        from: [-0.25, -0.3, 4.2], to: [0.25, -0.26, 4.1], lookFrom: [-0.1, -0.45, 0], lookTo: [0.1, -0.45, 0], ease: 'smooth',
      },
    }),
    slots: [cutout('subject', 'subject_1', [0, 0, 0])],
    aliases: { subject: 'subject' },
    backdrop: { color: '#1c2030', sfx: [] },
    sfx: [{ id: 'end-stars', kind: 'stars', start: 0, end: 5, x: 50, y: 40, size: 110, intensity: 0.5, color: '#ffffff' }],
    texts: [
      text('title', 'THANKS FOR WATCHING', 0.4, 4.8, {
        y: 40, size: 9, font: 'display', weight: 800, uppercase: true, letterSpacing: 0.05,
        enter: { preset: 'rise', duration: 0.6 }, exit: { preset: 'fade', duration: 0.4 },
      }),
      text('cta', 'SUBSCRIBE · SHARE · NEXT EPISODE', 1.1, 4.8, {
        y: 60, size: 4, color: '#101218', font: 'sans', weight: 700, uppercase: true, letterSpacing: 0.12, loop: 'pulse',
        enter: { preset: 'scale', duration: 0.4 }, exit: { preset: 'fade', duration: 0.4 },
        box: { kind: 'pill', color: '#ffcf3a', opacity: 1, padding: 0.7, radius: 1.5 },
      }),
    ],
    copy: copy(
      { title: 'End card', description: 'A title rises and a pulsing call to action lands under it while the camera drifts sideways over faint stars.', requirements: ['Title (text) and call to action (subtext)', CUTOUT_EN] },
      { title: 'Cartela final', description: 'Un título asciende y una llamada a la acción que late aterriza debajo mientras la cámara deriva de lado sobre estrellas tenues.', requirements: ['Título (text) y llamada a la acción (subtext)', CUTOUT_ES] },
    ),
  },
}

export function isTitleTemplateId(id: string): id is TitleTemplateId {
  return (TITLE_TEMPLATE_IDS as readonly string[]).includes(id)
}

function uniqueRoles(slots: Scene3DSlot[]): Scene3DSlotId[] {
  return [...new Set(slots.map(slot => slot.slot))]
}

export const TITLE_TEMPLATES = TITLE_TEMPLATE_IDS.map(id => ({
  id,
  camera: SPECS[id].camera.family,
  duration: SPECS[id].duration,
  slots: uniqueRoles(SPECS[id].slots),
}))

export const TITLE_CATEGORIES = Object.fromEntries(
  TITLE_TEMPLATE_IDS.map(id => [id, 'cinema']),
) as Record<TitleTemplateId, 'cinema'>

function bindSlot(slot: Scene3DSlot, roles: TitleApplyOptions['roles'], aliases: Record<string, string>): Scene3DSlot {
  const next = structuredClone(slot)
  if (!roles) return next
  const alias = Object.keys(aliases).find(name => aliases[name] === slot.id)
  const url = roles[slot.id] ?? (alias ? roles[alias] : undefined) ?? roles[slot.slot]
  if (url) next.sourceUrl = url
  return next
}

function chooseTexts(spec: TitleSpec, options: TitleApplyOptions): KineticText[] {
  const words = options.text?.split(/\s+/).filter(Boolean).slice(0, MAX_BEAT_WORDS) ?? []
  if (spec.beatWords && words.length) {
    const first = spec.texts[0], last = spec.texts[spec.texts.length - 1]
    return beatCues(words, BEAT_WORD, first.start, last.end)
  }
  return spec.texts.map((cue, index) => {
    const value = index === 0 ? options.text : index === 1 ? options.subtext : undefined
    return value ? { ...cue, text: value } : { ...cue }
  })
}

function buildDocument(spec: TitleSpec, id: TitleTemplateId, options: TitleApplyOptions): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  const vertical = options.orientation === 'vertical'
  doc.templateId = id
  doc.duration = spec.duration
  doc.fps = FPS
  doc.width = vertical ? 1080 : 1920
  doc.height = vertical ? 1920 : 1080
  doc.environment = { ...spec.environment }
  // Flat colours: a neutral curve at 0 EV keeps backdrop and cutout colours as authored.
  doc.look = { toneMapping: 'neutral', exposure: 0 }
  doc.light = { ...spec.light, direction: [...spec.light.direction] as Vec3 }
  doc.camera = adaptAuthoredCameraToFrame(structuredClone(spec.camera), doc.width, doc.height)
  doc.slots = spec.slots.map(slot => bindSlot(slot, options.roles, spec.aliases))
  doc.screenBackdrop = parseScreenBackdrop(spec.backdrop)
  doc.sfx = parseSceneFx(spec.sfx)
  doc.texts = chooseTexts(spec, options)
  return doc
}

export function applyTitleTemplate(id: string, options: TitleApplyOptions = {}): Scene3DDocument | null {
  if (!isTitleTemplateId(id)) return null
  return buildDocument(SPECS[id], id, options)
}

export function titleTemplateDocument(id: string): Scene3DDocument | null {
  return applyTitleTemplate(id)
}

export function titleCard(id: string, locale: 'en' | 'es' = 'en'): TitleCardCopy | undefined {
  if (!isTitleTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

/** The authored screen cue kinds before parsing, so a check can prove none was dropped as unknown. */
export function titleAuthoredCueKinds(id: string): { sfx: string[]; backdrop: string[] } {
  if (!isTitleTemplateId(id)) return { sfx: [], backdrop: [] }
  const kinds = (cues: Array<Record<string, unknown>>) => cues.map(cue => String(cue.kind))
  return { sfx: kinds(SPECS[id].sfx), backdrop: kinds(SPECS[id].backdrop.sfx) }
}

export function titleAliases(id: string): Record<string, string> {
  return isTitleTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
