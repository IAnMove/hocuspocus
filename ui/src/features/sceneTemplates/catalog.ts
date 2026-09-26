/**
 * Candidate-only scene templates for the Video3D review gallery.
 *
 * This registry is deliberately separate from `sceneNarrative.ts`: adding a
 * candidate here must not add it to the recipe grammar or to the approved
 * narrative-template selector. A candidate can be previewed and opened in
 * the editor while it remains explicitly unapproved.
 */

import { MUSIC_MOTION_TEMPLATES } from './musicMotionCatalog'

export const CATALOG_VERSION = '2026-09-review-1' as const
export const EXPANDED_CATALOG_VERSION = '2026-09-music-motion-1' as const

export type TemplateFamily = 'cinema' | 'music' | 'space'

export type TemplateSlotName = 'hero' | 'plate' | 'prop' | 'foreground' | 'subject_1' | 'subject_2' | 'background' | 'prop_1'

export type SceneTemplateSlot = {
  readonly id: TemplateSlotName
  readonly required: boolean
  readonly kinds: readonly ('image' | 'model3d')[]
  readonly description: string
}

export type SceneTemplateDefinition = {
  readonly id: string
  readonly version: 1
  readonly status: 'candidate'
  readonly family: TemplateFamily
  readonly title: string
  readonly description: string
  readonly slots: readonly SceneTemplateSlot[]
  readonly limits: readonly string[]
  readonly promptExample: string
  readonly defaultDuration: number
  readonly motionIntensity?: 'moderate' | 'high'
  readonly rhythmic?: boolean
}

const IMAGE = ['image'] as const
const IMAGE_OR_MODEL3D = ['image', 'model3d'] as const
const MODEL3D = ['model3d'] as const

const COMMON_LIMITS = [
  'At most 2 GLB, no repeats.',
  'Uses only supplied assets.',
  'No AI-generated video.',
  'No dialogue included.',
  'BPM does not imply real music or audio in previews.',
] as const

const CINEMA_LIMITS = [
  '2.5D cinema; only the GLB object adds depth.',
  ...COMMON_LIMITS,
] as const

const MUSIC_LIMITS = [
  '2.5D music; only the GLB object adds depth.',
  ...COMMON_LIMITS,
] as const

const SPACE_LIMITS = [
  'Space composed of GLB layers; no physics, collisions or global occlusion.',
  ...COMMON_LIMITS,
] as const

const SPACE_ORBIT_LIMITS = [
  ...SPACE_LIMITS,
  'The orbit is a layer relationship: it does not create global occlusion even when the objects stay on the same composition layer.',
] as const

type PropSlot = {
  required: boolean
  kinds: readonly ('image' | 'model3d')[]
  description: string
}

const makeSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
  heroKinds: readonly ('image' | 'model3d')[] = IMAGE_OR_MODEL3D,
): readonly SceneTemplateSlot[] => [
  {
    id: 'hero',
    required: true,
    kinds: heroKinds,
    description: hero,
  },
  {
    id: 'plate',
    required: true,
    kinds: IMAGE,
    description: plate,
  },
  ...(prop
    ? [{
        id: 'prop' as const,
        required: prop.required,
        kinds: prop.kinds,
        description: prop.description,
      }]
    : []),
  {
    id: 'foreground',
    required: false,
    kinds: IMAGE,
    description: foreground,
  },
]

const makeTemplate = (
  id: string,
  family: TemplateFamily,
  title: string,
  description: string,
  slots: readonly SceneTemplateSlot[],
  limits: readonly string[],
): SceneTemplateDefinition => ({
  id,
  version: 1,
  status: 'candidate',
  family,
  title,
  description,
  slots,
  limits,
  promptExample: `Use the candidate template "${id}" to create an editable cinematic shot, respecting its slots, limits and supplied assets.`,
  defaultDuration: 4,
})

const cinemaSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop)

const musicSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop)

const spaceSlots = (
  hero: string,
  plate: string,
  foreground: string,
  prop?: PropSlot,
) => makeSlots(hero, plate, foreground, prop, MODEL3D)

export const CANDIDATE_SCENE_TEMPLATES = [
  makeTemplate(
    'cinema-establishing',
    'cinema',
    'Establishing shot',
    'Introduces subject and environment with a wide, readable camera entrance.',
    cinemaSlots(
      'Main subject that sets the shot\'s scale and point of attention.',
      'Environment plate that places the action and allows a 2.5D move.',
      'Optional visual layer to create foreground depth.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-reveal',
    'cinema',
    'Cinematic reveal',
    'Gradually reveals the subject from a plate with restrained movement.',
    cinemaSlots(
      'Subject that appears late or is partly hidden at the start of the reveal.',
      'Plate that holds the camera entrance and space before the subject is revealed.',
      'Optional layer that can hide and reveal the subject without inventing 3D occlusion.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-closeup',
    'cinema',
    'Cinematic close-up',
    'Focuses attention on a subject at close scale with minimal movement.',
    cinemaSlots(
      'Main subject ready for close scale and a detailed read.',
      'De-emphasized background plate that keeps context without competing with the face or object.',
      'Optional texture or silhouette to soften the close-up\'s edge.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-two-shot',
    'cinema',
    'Cinematic two-shot',
    'Frames two presences in a conversation or shared-tension composition.',
    cinemaSlots(
      'First subject, anchoring the axis and scale of the conversation.',
      'Shared plate that keeps the frame spatially continuous.',
      'Optional foreground element to separate the two subjects.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Second subject or interaction object; completes the two-shot and accepts an image or GLB.',
      },
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-detail',
    'cinema',
    'Cinematic detail',
    'Isolates a small visual clue to turn it into a clear story beat.',
    cinemaSlots(
      'Main object or gesture that must stay readable in the detail.',
      'Supporting plate that gives the insert scale and contrast.',
      'Optional edge, shadow or texture framing the detail.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-hero',
    'cinema',
    'Hero entrance',
    'Gives the subject a frontal entrance with presence and cinematic direction.',
    cinemaSlots(
      'Visual hero that receives the camera move and the shot\'s top priority.',
      'Plate that provides horizon, contrast and direction for the entrance.',
      'Optional particle, frame or silhouette layer to reinforce scale.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-isolation',
    'cinema',
    'Cinematic isolation',
    'Separates the subject from the environment with negative space and a restrained move.',
    cinemaSlots(
      'Isolated subject that keeps a clear silhouette against negative space.',
      'Simple plate that leaves room around the subject and avoids competing with it.',
      'Optional veil or shadow layer to heighten the sense of isolation.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'cinema-tracking',
    'cinema',
    'Cinematic tracking',
    'Follows the subject with a steady sideways drift and a continuous plate.',
    cinemaSlots(
      'Subject that stays centered while the frame simulates a lateral tracking shot.',
      'Scrollable plate that keeps a sense of travel without building a 3D world.',
      'Optional layer that passes close to camera to emphasize movement.',
    ),
    CINEMA_LIMITS,
  ),
  makeTemplate(
    'music-pulse',
    'music',
    'Musical pulse',
    'Turns a visual pulse into rhythmic changes of scale, contrast and position.',
    musicSlots(
      'Main subject that receives scale pulses and small energy variations.',
      'Plate with enough contrast for the pulse to read without generated audio.',
      'Optional texture or light that responds visually to the shot\'s pulse.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-duet',
    'music',
    'Musical duet',
    'Alternates two presences in a music-video composition with a shared visual response.',
    musicSlots(
      'First presence, setting the duet\'s axis and base rhythm.',
      'Stage or environment plate that holds the alternation between the presences.',
      'Optional light, graphic smoke or texture layer to connect both positions.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Second presence of the duet; accepts a supplied portrait, object or GLB.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-chorus',
    'music',
    'Musical chorus',
    'Amplifies a main gesture with a layered cadence and chorus framing.',
    musicSlots(
      'Main figure or motif carrying the chorus\'s repeatable gesture.',
      'Stage plate that allows scale changes and gentle parallax.',
      'Optional shapes or lights layer that multiplies the chorus feel.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-orbit',
    'music',
    'Musical orbit',
    'Orbits a prop around the main motif through a 2.5D layer relationship.',
    musicSlots(
      'Main motif that stays at the center of the prop layer\'s orbit.',
      'Plate that offers reference lines to read the rotation without global 3D geometry.',
      'Optional layer crossing the frame edge to reinforce the orbital motion.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Prop or second motif orbiting the hero via keyframes; accepts an image or GLB.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-parallax',
    'music',
    'Musical parallax',
    'Builds rhythmic depth through differential movement of flat layers.',
    musicSlots(
      'Main motif setting the visual rhythm over the parallax layers.',
      'Plate with enough texture or architecture to make the movement visible.',
      'Optional near layer that widens the separation between planes.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-stage',
    'music',
    'Musical stage',
    'Places the motif on a graphic stage prepared for a music-video entrance.',
    musicSlots(
      'Artist, object or motif occupying the stage\'s compositional center.',
      'Stage plate defining the background, visual floor and motif contrast.',
      'Optional curtain, graphic smoke or rim-light layer.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-product',
    'music',
    'Musical product',
    'Presents a product or object with music-video energy and a controlled visual spin.',
    musicSlots(
      'Main product or motif receiving the focus and camera move.',
      'Studio or stage plate that keeps a clean read of the product.',
      'Optional reflection, texture or graphic-light layer around the object.',
      {
        required: false,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Optional brand prop or second object; accepts a supplied image or GLB.',
      },
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'music-finale',
    'music',
    'Musical finale',
    'Closes the music video with a wide, readable composition of sustained energy.',
    musicSlots(
      'Main motif holding the final image and receiving the last visual accent.',
      'Closing plate that allows a wide exit without needing real audio.',
      'Optional sparkle, shape or frame layer to mark the ending.',
    ),
    MUSIC_LIMITS,
  ),
  makeTemplate(
    'space-cruise',
    'space',
    'Space cruise',
    'Follows a ship through a starfield with a sense of continuous travel.',
    spaceSlots(
      'Main GLB ship defining the cruise\'s direction, scale and read.',
      'Star or deep-space plate that scrolls as the visual background.',
      'Optional image layer of near stars, dust or speed lines.',
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-orbit',
    'space',
    'Space orbit',
    'Orbits the hero ship around a prop planet or station via layer keyframes.',
    spaceSlots(
      'Main GLB ship orbiting the prop planet or station; it is not a real orbiting camera.',
      'Space plate providing stars, a planet or a reference visual field.',
      'Optional foreground particle or stardust layer.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Planet or station at the center of the orbit; accepts an image or GLB without global occlusion.',
      },
    ),
    SPACE_ORBIT_LIMITS,
  ),
  makeTemplate(
    'space-docking',
    'space',
    'Space docking',
    'Simulates a ship approaching a station through layers and controlled movement.',
    spaceSlots(
      'GLB ship that performs the approach and keeps a stable silhouette.',
      'Space or hangar plate setting the docking direction.',
      'Optional foreground lights, dust or hatch-frame layer.',
      {
        required: true,
        kinds: IMAGE_OR_MODEL3D,
        description: 'Destination station or hatch; accepts an image or GLB without resolving collisions.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-chase',
    'space',
    'Space chase',
    'Composes a ship chase with parallel movement, without collision physics.',
    spaceSlots(
      'Pursuing GLB ship carrying the chase\'s movement and direction.',
      'Star or nebula plate giving continuity to the movement.',
      'Optional foreground dust, streak or light layer.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Pursued or escort GLB ship; moves by keyframes, without collisions.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-broadside',
    'space',
    'Space broadside',
    'Presents two ship profiles as a layered visual confrontation.',
    spaceSlots(
      'Main GLB ship shown in profile to define the confrontation\'s axis.',
      'Starfield plate keeping negative space between the ships.',
      'Optional image layer of flashes, graphic smoke or particles.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Rival GLB ship for the opposing profile; there is no collision or global occlusion.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-shield',
    'space',
    'Space shield',
    'Visualizes an impact or shield as a graphic accent on a composited ship.',
    spaceSlots(
      'Attacking GLB ship marking the direction of impact and staying as a spatial reference.',
      'Starfield plate that contrasts with the shield flash.',
      'Optional image layer of energy, smoke or particles.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Target GLB ship receiving the shield; the impact is animated without physics.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-explosion',
    'space',
    'Space explosion',
    'Depicts a graphic explosion around a ship through layers and keyframes.',
    spaceSlots(
      'Attacking GLB ship setting the visual origin of the attack.',
      'Space plate giving contrast and scale to the flash.',
      'Optional image layer of smoke, fire or debris.',
      {
        required: true,
        kinds: MODEL3D,
        description: 'Target GLB ship that disappears when it explodes; no physical fragmentation is simulated.',
      },
    ),
    SPACE_LIMITS,
  ),
  makeTemplate(
    'space-warp',
    'space',
    'Space warp',
    'Accelerates a ship into a visual jump with streaks and controlled depth layers.',
    spaceSlots(
      'GLB ship that stays readable while accelerating into the jump.',
      'Star or space-tunnel plate that allows continuous movement.',
      'Optional image layer of speed lines, dust or flashes.',
    ),
    SPACE_LIMITS,
  ),
] as const satisfies readonly SceneTemplateDefinition[]

/** Original references stay versioned separately: never rewrite their hashes or
 * infer that a new choreography has an approved reference because it compiles. */
export const ALL_SCENE_TEMPLATES: readonly SceneTemplateDefinition[] = [...CANDIDATE_SCENE_TEMPLATES, ...MUSIC_MOTION_TEMPLATES]

// Membership is explicit: the legacy catalogue contains a few `music-*`
// IDs of its own, and a slot name alone must not move one of those templates
// into the expanded review version.
const EXPANDED_TEMPLATE_IDS = new Set(MUSIC_MOTION_TEMPLATES.map(template => template.id))

export function templateCatalogVersion(template: SceneTemplateDefinition): string {
  return EXPANDED_TEMPLATE_IDS.has(template.id) ? EXPANDED_CATALOG_VERSION : CATALOG_VERSION
}

export function getCandidateSceneTemplate(id: string): SceneTemplateDefinition {
  const template = ALL_SCENE_TEMPLATES.find(candidate => candidate.id === id)
  if (!template) {
    throw new Error(`Unknown candidate scene template: ${id}`)
  }
  return template
}
