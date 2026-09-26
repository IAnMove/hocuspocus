import type { SceneTemplateDefinition } from './catalog'

/**
 * Candidate-only musical motion definitions.
 *
 * This module describes the contract for the motion pack.  The choreography
 * compiler, asset picker and approval registry consume it separately; merely
 * adding an entry here must not generate an asset or approve a preview.
 */

export type MusicMotionIntensity = 'moderate' | 'high'

type MusicMotionSlotName = 'subject_1' | 'subject_2' | 'background' | 'prop_1'

type MusicMotionSlot = {
  readonly id: MusicMotionSlotName
  readonly required: boolean
  readonly kinds: readonly ['image']
  readonly description: string
}

type MusicMotionDefinition = Omit<SceneTemplateDefinition, 'slots'> & {
  readonly slots: readonly MusicMotionSlot[]
  readonly motionIntensity: MusicMotionIntensity
  readonly rhythmic?: boolean
}

const IMAGE = ['image'] as const

const slot = (
  id: MusicMotionSlotName,
  description: string,
): MusicMotionSlot => ({ id, required: true, kinds: IMAGE, description })

const composition = (
  subject: string,
  background: string,
  extras: { subject2?: string; prop1?: string } = {},
): readonly MusicMotionSlot[] => [
  slot('subject_1', subject),
  ...(extras.subject2 ? [slot('subject_2', extras.subject2)] : []),
  slot('background', background),
  ...(extras.prop1 ? [slot('prop_1', extras.prop1)] : []),
]

const COMMON_LIMITS = [
  'Uses image layers only; no GLB, rig, physics, collisions or automatic walking.',
  'The path is expressed with deterministic, editable keyframes; there is no physics simulation.',
  'subject_1, subject_2 and prop_1 must be cutouts with clean alpha when they are figures or objects; assets are not repeated to fill slots.',
  'background must be a durable, readable image plate; it is never generated or silently replaced.',
  'Does not generate AI video or audio and does not modify the attached song.',
  'Uses no strobe or deliberate white flashes. Some motions include strong spins or shifts: avoid dense repetition and review the result for motion sickness.',
  'Clean alpha is an input requirement; this catalog does not inspect pixels or guarantee that the asset meets it.',
  'Motions that declare a strip repeat the same image along the given axis; they may show seams if the asset is not tileable. They do not guarantee continuity and need an artistic review of the preview and render before approval; this catalog does not validate pixels or tileability.',
] as const

type MotionSpec = {
  id: string
  title: string
  description: string
  subject: string
  background: string
  subject2?: string
  prop1?: string
  note: string
  duration?: number
  motionIntensity?: MusicMotionIntensity
}

const makeTemplate = (spec: MotionSpec): MusicMotionDefinition => {
  const slots = composition(spec.subject, spec.background, { subject2: spec.subject2, prop1: spec.prop1 })
  const requiredSlots = slots.filter(item => item.required).map(item => item.id).join(', ')
  return {
    id: spec.id,
    version: 1,
    status: 'candidate',
    family: 'music',
    title: spec.title,
    description: spec.description,
    slots,
    limits: [
      ...COMMON_LIMITS,
      spec.note,
    ],
    promptExample: `Use the candidate music motion "${spec.id}" (${spec.title}). Fill exactly the required slots ${requiredSlots}; use only the supplied images, with subject_1 as the main focus and background as the environment plate. Respect the motion's limits and keep text and audio out of this template.`,
    defaultDuration: spec.duration ?? 4,
    motionIntensity: spec.motionIntensity ?? 'moderate',
  }
}

const DEFINITIONS = [
  makeTemplate({
    id: 'music-spiral-exit',
    title: 'Spiral exit',
    description: 'The focus shrinks and fades at the center while spinning twice, producing a compact graphic exit.',
    subject: 'Cut-out lead figure or object, readable during the spin and ready to shrink until it almost disappears.',
    background: 'Plate with a clean center and enough contrast for the spin and fade to be visible.',
    note: 'The exit is a two-turn 2D rotation and scale; it does not describe a rising spiral, orbit or 3D depth.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-speed-flight',
    title: 'Speed flight',
    description: 'The lead crosses the frame from left to right in one fast pass with a clear exit.',
    subject: 'Cut-out figure or object facing the direction of travel, without needing a locomotion cycle.',
    background: 'Plate with a lane, horizon or graphic stripes suggesting speed without relying on motion blur; it can scroll left through a horizontal strip that repeats the image and may show seams if the source is not horizontally tileable.',
    note: 'The route runs left to right and the background can use a horizontal strip scrolling left at 95 units per second; it does not guarantee continuity, needs an artistic review of preview and render, and is neither beat sync nor physical flight.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-infinite-fall',
    title: 'Endless fall',
    description: 'The lead enters from the top, descends along a finite route and shrinks until exiting at the bottom.',
    subject: 'Cut-out figure or object with a consistent orientation during the descent and a silhouette that tolerates shrinking.',
    background: 'Vertical plate or graphic field that keeps the top entry and bottom exit readable; a vertical strip repeats the image and may show seams if the source is not vertically tileable.',
    note: 'It is a single top-to-bottom route with decreasing scale; the vertical strip does not guarantee continuity and needs an artistic review of preview and render; there is no clean loop, infinite world, gravity or 3D depth.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-pinball',
    title: 'Pinball bounce',
    description: 'The focus travels through a series of angular bounces and scale accents like a graphic pinball.',
    subject: 'Cut-out object or character that acts as a moving focus and stays clearly readable on every bounce.',
    background: 'Plate with an abstract board, edges and drawn bounce zones, with no 3D parts needed.',
    note: 'The bounces are points on a scripted path; there are no collisions, flippers or pinball solver.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-boomerang',
    title: 'Boomerang',
    description: 'The subject moves away along an open curve and returns to the starting point with a recognizable visual payoff.',
    subject: 'Cut-out figure or object that stays readable on the way out and back.',
    background: 'Plate with negative space and a horizon line that makes the out-and-back arc visible.',
    note: 'The arc is keyframed and stylized; it does not simulate aerodynamics, throwing or projectile physics.',
  }),
  makeTemplate({
    id: 'music-cannon-launch',
    title: 'Cannon launch',
    description: 'The focus shoots off and leaves the frame through the top right along a fast arc.',
    subject: 'Cut-out figure or object that tolerates the exit spin and stays identifiable before leaving the frame.',
    background: 'Plate with a cannon mouth or graphic rail built into the environment, without needing an extra asset.',
    note: 'The arced route ends outside the frame; there is no landing, final pause, ballistics, forces or real impact.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-orbit-duel',
    title: 'Orbital duel',
    description: 'Two focal subjects cross on opposite arcs around a central axis to create music-video tension.',
    subject: 'First cut-out character or object, defining the first arc of the duel.',
    subject2: 'Second cut-out character or object, with a different silhouette, answering from the opposite arc.',
    background: 'Plate with a central axis and enough space to tell both paths apart.',
    note: 'The two arcs are independent 2D paths; there is no physical orbit, contact or global occlusion.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-high-five',
    title: 'High five',
    description: 'Two characters approach a common point, mark the meeting and part with a brief bounce.',
    subject: 'First cut-out character in a pose that leaves visual room for the shared gesture.',
    subject2: 'Second cut-out character facing the first, with a silhouette that is not identical by default.',
    background: 'Simple plate with a clear meeting point and enough contrast for both figures.',
    note: 'The meeting is a synchronized pose; it does not detect hands, contact or joints.',
  }),
  makeTemplate({
    id: 'music-magnet-pull',
    title: 'Magnetic pull',
    description: 'The first focus stays almost still while pulling in the second, which bounces and settles.',
    subject: 'First cut-out character or object acting as a stable visual pole.',
    subject2: 'Second cut-out character or object that approaches, bounces and stays readable next to the first pole.',
    background: 'Plate with a line or graphic field that makes the direction of the pull visible.',
    note: 'Only subject_2 performs the approach and damped bounce; no magnetic fields, masses or collisions are computed.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-ricochet-pass',
    title: 'Bounce pass',
    description: 'A cut-out object bounces between several points while the focus stays still as the reference for the pass.',
    subject: 'Cut-out character or object that stays still and serves as the reference; no walk cycle needed.',
    background: 'Plate with a corridor or path markings that keep the pass inside the frame.',
    prop1: 'Small cut-out object, such as a ball, microphone or card, that performs every bounce of the pass.',
    note: 'prop_1 is required and is the only moving element; subject_1 stays still and there are no physical collisions.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-portal-swap',
    title: 'Portal swap',
    description: 'Two focal subjects vanish and reappear in swapped positions through controlled graphic cuts.',
    subject: 'First cut-out character or object occupying the initial exit portal.',
    subject2: 'Second cut-out character or object occupying the opposite portal so the swap reads clearly.',
    background: 'Plate with two clear zones to suggest portals without adding required geometry or particles.',
    note: 'The portals are opacity and position states; there is no 3D teleport, continuous space or occlusion.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-trampoline',
    title: 'Trampoline jump',
    description: 'The lead drops, bounces and falls again with an exaggerated, readable vertical pulse.',
    subject: 'Cut-out figure or object that can take a vertical bounce without mesh deformation.',
    background: 'Plate with a visual base or stage marking the take-off and landing point.',
    note: 'The bounce uses uniform scale and layer position; there is no per-axis squash-and-stretch, bitmap deformation or real elasticity.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-pendulum',
    title: 'Musical pendulum',
    description: 'The focus swings side to side around a fixed position with a hypnotic rhythm.',
    subject: 'Cut-out figure or object that keeps a recognizable orientation while swinging.',
    background: 'Plate with a top or central reference that makes the pendulum axis readable.',
    note: 'The swing uses angular keyframes; it does not solve gravity, string, physical pivot or collisions.',
  }),
  makeTemplate({
    id: 'music-rubber-band',
    title: 'Rubber band',
    description: 'The focus pulls away from the center, builds visual tension and snaps back with a musical release.',
    subject: 'Cut-out figure or object that can change scale without losing its main silhouette.',
    background: 'Plate with two ends or graphic anchors that explain the direction of tension.',
    note: 'The tension uses X offset and rotation without scaling the layer; there is no rubber deformation or force solver.',
  }),
  makeTemplate({
    id: 'music-card-toss',
    title: 'Card throw',
    description: 'The focus enters, holds briefly and shoots out of frame with a pronounced spin.',
    subject: 'Cut-out card, object or character that stays readable and spins through layer rotation.',
    background: 'Table, stage or negative-space plate where the throw arc can be seen.',
    note: 'The entry, readable pause and propelled exit are written as 2D keyframes; there is no landing, 3D perspective or card physics.',
  }),
  makeTemplate({
    id: 'music-staircase-pop',
    title: 'Step climb',
    description: 'The lead climbs through discrete positions with scale accents reminiscent of a sampler.',
    subject: 'Cut-out figure or object that jumps between positions and does not need to walk.',
    background: 'Plate with built-in steps or graphic bands so every jump has a visual reference.',
    note: 'The steps are composition positions, not a walkable staircase or locomotion cycle.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-accordion-clones',
    title: 'Accordion clones',
    description: 'The same focus appears in an expanding and contracting set of positions, like a visual accordion.',
    subject: 'Approved cut-out figure or object that can repeat visually without changing identity.',
    background: 'Wide, clear plate so the temporary copies don\'t hide the main axis.',
    note: 'The copies are bounded instances of the same image; they do not create new characters or a crowd simulation.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-domino-wave',
    title: 'Domino wave',
    description: 'A limited number of copies of the focus tilt in sequence and recover, forming a visual wave.',
    subject: 'Cut-out figure or object that can repeat and tolerate a brief tilt without losing its pose.',
    background: 'Horizontal plate with a clear axis for reading the wave\'s progress.',
    note: 'The copies tilt and recover their orientation; they don\'t enter or leave as new characters and there are no physical dominoes or collisions.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-conveyor',
    title: 'Conveyor belt',
    description: 'The focus travels in a constant direction while the environment keeps a conveyor-like feel.',
    subject: 'Cut-out figure or object that travels horizontally without needing leg animation.',
    background: 'Plate with a band, arrows or repeatable modules suggesting a flat belt; a horizontal strip repeats the image and may show seams if the source is not horizontally tileable.',
    note: 'The conveyor is a layer offset with an optional loop; the horizontal strip does not guarantee continuity and needs an artistic review of preview and render; there is no machinery, physics or collision.',
  }),
  makeTemplate({
    id: 'music-spotlight-relay',
    title: 'Spotlight relay',
    description: 'Two presences trade the spotlight through light and scale entrances and exits.',
    subject: 'First cut-out character or object, receiving the first spotlight of the relay.',
    subject2: 'Second cut-out character or object that takes the spotlight next and keeps a separate identity.',
    background: 'Dark or stage plate with two readable spotlight zones and no white flashes.',
    note: 'The spotlight is expressed through opacity, scale and soft effects; there is no physical lighting or face tracking.',
    duration: 6,
    motionIntensity: 'moderate',
  }),
  makeTemplate({
    id: 'music-corkscrew-rise',
    title: 'Corkscrew rise',
    description: 'The lead rises with a layer rotation and a sideways drift that trace a corkscrew.',
    subject: 'Cut-out figure or object with a stable silhouette during the layer rotation.',
    background: 'Vertical plate with height markers and enough space for the helical path.',
    note: 'The corkscrew is a 2D path with rotation; it is not a 3D trajectory or an orbiting camera.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-shockwave',
    title: 'Shockwave',
    description: 'The central focus stays readable while a motion zoom marks the visual hit.',
    subject: 'Cut-out figure or object that stays at the center of the visual impact.',
    background: 'Plate with negative space around the subject so the expansion isn\'t cropped.',
    note: 'The wave is a motion and scale accent with no opacity change; it does not simulate an explosion, pressure or physical damage.',
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-satellite-swarm',
    title: 'Satellite swarm',
    description: 'The central focus is accompanied by a satellite or cloned object tracing controlled visual orbits.',
    subject: 'Cut-out figure or object acting as the stable center of the swarm.',
    background: 'Space or abstract plate with enough room to separate the center and satellites.',
    prop1: 'A satellite or small object on a transparent cutout; the compositor can clone it up to five times around the center.',
    note: 'prop_1 is required and is a single asset that can be instanced five times; there is no swarm AI, physics or 3D depth.',
    duration: 6,
    motionIntensity: 'high',
  }),
  makeTemplate({
    id: 'music-crowd-surf',
    title: 'Crowd surf',
    description: 'The lead travels over copies of an audience strip that act as visual support.',
    subject: 'Cut-out figure or object that stays clearly above the support strip.',
    background: 'Concert plate with headroom and contrast to separate the lead from the audience copies.',
    prop1: 'Strip or group of cut-out audience silhouettes copied beneath the lead as visual support.',
    note: 'prop_1 is required and its copies form the support; there is no background wave, generated bodies, hands, balance or crowd physics.',
    duration: 6,
    motionIntensity: 'high',
  }),
] as const

export const MUSIC_MOTION_TEMPLATES: readonly SceneTemplateDefinition[] = DEFINITIONS
