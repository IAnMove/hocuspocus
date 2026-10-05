import { CINEMATIC_TEMPLATE_IDS } from './cinematicTemplateIds'
import { DARK_FANTASY_IDS } from './darkFantasyIds'
import { CREATIVE_TEMPLATE_IDS } from './creativeTemplateIds'
import { SPEECH_TEMPLATE_IDS } from './speech/templateIds'
import type { Scene3DSpeech, Scene3DSoundtrack } from './speech/types'
import { MEDIA_TEMPLATE_IDS } from './mediaTemplateIds'
import { PIXEL_TEMPLATE_IDS } from './pixel/pixelTemplateIds'
import { ATMOS_TEMPLATE_IDS } from './atmos/registryIds.ts'
import { TECHNIQUE_TEMPLATE_IDS } from './techniqueTemplateIds'
import type { AtmosSetId } from './atmos/registryIds.ts'
import type { AtmosSettings } from './atmos/params.ts'

export type Vec3 = readonly [number, number, number]

export type Scene3DCameraFamily =
  | 'fixed'
  | 'establishment'
  | 'follow'
  | 'orbit'
  | 'reveal'
  | 'encounter'
  | 'pursuit'
  | 'product'
  | 'musical'
  | 'side'
  | 'front'
  | 'chase'
  | 'hood'
  | 'wing'

export type Scene3DSlotId = 'subject_1' | 'subject_2' | 'background' | 'prop'

export const SCENE3D_TEMPLATE_IDS = [
  'topdown-dragon-portals',
  'topdown-cliff-flight',
  ...SPEECH_TEMPLATE_IDS,
  'two-shot',
  'product-orbit',
  'hero-push',
  'over-shoulder',
  'tracking',
  'crane-reveal',
  'establishing',
  'run-loop',
  'neon-run',
  'block-street',
  'space-float',
  'walk-void',
  'dance-orbit',
  'dance-stage',
  'cafe-dance',
  'drive-chase',
  'drive-hood',
  'drive-wing',
  'drive-orbit',
  'drive-tunnel',
  'drive-hero',
  'portrait-arc',
  'duo-diagonal',
  'high-angle',
  'wide-tableau',
  'product-detail',
  'product-pair',
  'product-pedestal',
  'duet-stage',
  'cafe-duet',
  'stage-crane',
  'space-encounter',
  'space-survey',
  'drive-coast-reveal',
  'drive-city-wide',
  'drive-tunnel-wing',
  'siege-ring',
  'spell-duel',
  'victory-circle',
  'coder-room',
  'clone-chase',
  ...CINEMATIC_TEMPLATE_IDS,
  ...DARK_FANTASY_IDS,
  ...CREATIVE_TEMPLATE_IDS,
  ...MEDIA_TEMPLATE_IDS,
  ...PIXEL_TEMPLATE_IDS,
  'reflective-stage',
  'character-materialization',
  'blast-stage',
  'server-inspection',
  'coding-desk',
  'tracking-chase',
  'character-presentation',
  'screen-alert',
  'product-comparison',
  'topic-travelling',
  'heroic-close',
  'sea-deck',
  'lunar-outpost',
  'car-chase',
  'ship-chase',
  'rooftop-run',
  'alley-motorcycle',
  'hangar-standoff',
  'train-roof',
  'desert-convoy',
  'night-rain-pursuit',
  'dock-ambush',
  'bridge-standoff',
  'cockpit-pursuit',
  'helicopter-extract',
  'warehouse-breach',
  'canyon-run',
  'jungle-ambush',
  'snow-compound',
  'casino-heist',
  'bank-vault',
  'skyscraper-ledge',
  'oil-rig',
  'subway-brawl',
  'freeway-overpass',
  'prison-break',
  'arctic-chase',
  'clock-tower',
  'mansion-infil',
  'cargo-hold',
  'jungle-river',
  'red-carpet',
  'volcano-ridge',
  'hangar-talk',
  'sea-talk',
  'voxel-talk',
  ...ATMOS_TEMPLATE_IDS,
  ...TECHNIQUE_TEMPLATE_IDS,
] as const

export type Scene3DTemplateId = (typeof SCENE3D_TEMPLATE_IDS)[number]

export type Scene3DClipRef = {
  index: number
  name: string
}

export type Scene3DClipPlayback = {
  speed?: number
  start?: number
  loop?: boolean
}

export type Scene3DMotion = {
  to: Vec3
  via?: Vec3
  /** Waypoints between the start and `to`, walked on a centripetal Catmull-Rom curve. */
  points?: Vec3[]
  faceTravel?: boolean
  turnTo?: number
  easing?: 'linear' | 'smooth'
  /** A baked humanoid walk of this path with planted feet; while it matches, the clip moves the model. */
  walk?: import('./walkPath').Scene3DMotionWalk
}

export type Scene3DSlotMedia = 'model3d' | 'image' | 'screen'

export type Scene3DLoop = {
  cylinder: boolean
  speed: number
}

export type Scene3DDressing = 'none' | 'street' | 'space' | 'treadmill' | 'cafe' | 'drive-city' | 'drive-coast' | 'drive-tunnel' | 'citadel' | 'workshop' | 'chase-street' | 'retro-lab' | 'observatory' | 'broadcast-plaza' | 'open-sea' | 'lunar' | 'rooftop' | 'hangar' | 'desert' | 'train' | 'space-lane' | 'jungle' | 'snow' | 'casino' | 'pixel-lake' | 'pixel-peaks' | 'pixel-gallery' | 'pixel-city' | 'pixel-desert' | 'pixel-coast' | 'pixel-forest' | 'pixel-viaduct' | 'pixel-volcano' | 'pixel-drivein' | 'pixel-garden' | 'pixel-reef' | 'pixel-valley' | 'pixel-fair' | 'pixel-village' | 'pixel-falls' | 'pixel-orbit' | 'pixel-tulips' | 'pixel-alley' | 'pixel-castle' | 'pixel-beach' | 'pixel-lanterns' | 'pixel-window' | 'pixel-express' | 'pixel-daycycle' | 'pixel-eclipse' | 'pixel-seasons' | 'pixel-cathedral' | 'pixel-koi' | 'pixel-caravan' | 'pixel-synthwave' | 'pixel-monsoon' | 'pixel-marsh' | 'pixel-launch' | 'pixel-grotto' | 'pixel-starry' | 'pixel-dawnmist' | 'pixel-motel' | 'pixel-tidal' | 'pixel-mirage' | 'pixel-meadow' | 'pixel-fjord' | 'pixel-clockwork' | 'pixel-orrery' | 'pixel-rainbow' | 'pixel-risingcity' | 'pixel-abyss' | 'pixel-blizzard' | 'pixel-lantern' | 'pixel-empire' | 'pixel-startrails' | 'pixel-wheat' | 'pixel-pool' | 'pixel-piazza' | AtmosSetId

export type Scene3DSourceRef = {
  workspaceId: string
  filename: string
  url: string
  assetId?: string
}

export type Scene3DSlot = {
  rhythm?: import('./rhythm').Scene3DSlotRhythm
  character?: { id: string; name: string; kitRef?: import('../../lib/characterVoice').CharacterKitRef;
    libraryRevision?: number; voice?: import('../../lib/characterVoice').CharacterVoice
    voicesByLanguage?: import('../../lib/characterVoice').CharacterVoicesByLanguage }
  id: string
  slot: Scene3DSlotId
  position: Vec3
  rotationY: number
  scale: number
  sourceUrl: string
  sourceRef?: Scene3DSourceRef
  speech?: Scene3DSpeech
  media: Scene3DSlotMedia
  screen?: import('./mediaScreen').MediaScreen
  surface?: 'wall' | 'floor' | 'environment' | 'cutout'
  imageLook?: import('./imageLook').ImageLook
  appearance?: { start: number; duration: number; color: string }
  textureRepeat?: number
  performance?: 'typing' | 'idle'
  grounded?: boolean
  clip: Scene3DClipRef | null
  clipPlayback?: Scene3DClipPlayback
  /** A sequence of clips with crossfades. When present it drives the model; `clip` and `clipPlayback` are ignored. */
  clips?: import('./clipCues').Scene3DClipCue[]
  /** This prop is carried in another slot's whole hand. Absent means the slot stays where it was placed. */
  hold?: import('./handHold').Scene3DHold
  motion?: Scene3DMotion
  loop?: Scene3DLoop
}

export type Scene3DCamera = {
  family: Scene3DCameraFamily
  eye: Vec3
  look: Vec3
  fov: number
  orbitRadius?: number
  orbitHeight?: number
  orbitTurns?: number
  targetOffset?: Vec3
  eyeOffset?: Vec3
  framing?: Scene3DFraming
  /** Authored cameras are landscape; portrait shots store the adapted camera. */
  frameFormat?: 'landscape' | 'portrait'
}

export type Scene3DFraming = {
  targetSlot: string
  anchor: 'head' | 'center' | 'feet'
  from: Vec3
  to: Vec3
  lookFrom?: Vec3
  lookTo?: Vec3
  orbitTurns?: number
  rollFrom?: number
  rollTo?: number
  /** Lens size at the start and end of the move. Omitted values keep `camera.fov`. */
  fovFrom?: number
  fovTo?: number
  relativeToFacing?: boolean
}

export type Scene3DLight = {
  kind: 'directional'
  direction: Vec3
  intensity: number
  color: string
}

/** Whole-frame render presets. `n64`: low resolution, flat shading and close fog. `toon`: cel shading and ink outlines on model slots. */
export const SCENE3D_RENDER_LOOKS = ['n64', 'toon'] as const
export type Scene3DRenderLook = (typeof SCENE3D_RENDER_LOOKS)[number]

/** Settings of the `toon` render look; missing values use `DEFAULT_TOON` (`toonLook.ts`). */
export type Scene3DToon = {
  /** Light bands of the cel shading, 2 to 4. */
  steps?: number
  /** Ink line width in pixels of a 1080-pixel-high frame, 0 to 8; 0 draws no line. */
  outline?: number
  /** Ink colour, `#rrggbb`. */
  ink?: string
}

export type Scene3DDocument = {
  rhythm?: import('./rhythm').Scene3DRhythm
  renderLook?: Scene3DRenderLook
  /** Used while `renderLook` is `toon`; kept when another look is chosen. */
  toon?: Scene3DToon
  soundtrack?: Scene3DSoundtrack[]
  production?: { kind: 'song' | 'dialogue' | 'episode' | 'trailer'; title: string; sourceId?: string; workspace: string }
  version: 1
  units: 'meters'
  up: 'y'
  width: number
  height: number
  fps: 24 | 30 | 60
  duration: number
  /** Stable review number, baked into exported frames when present. */
  clipNumber?: number
  sfx?: import('../sceneFx/types').SceneFx[]
  /** Palette-cycled lighting and the pixel-art look over the whole frame. */
  pixelWorld?: import('./pixel/pixelWorld').PixelWorld
  /** Spatial effects in world meters. Screen overlays stay on `sfx`. */
  worldSfx?: import('../sceneFx/world').WorldSfx[]
  texts?: import('../../lib/kineticText').KineticText[]
  lyrics?: import('../../lib/kineticText').SceneLyrics
  /** Timeline rate; exported duration is duration / playbackSpeed. */
  playbackSpeed?: number
  templateId: Scene3DTemplateId
  camera: Scene3DCamera
  light: Scene3DLight
  environment?: { reflectiveFloor: boolean; platform: boolean; bloom: number; floorStyle?: 'tiles' | 'mirror' | 'none' | 'backdrop' | 'road'; road?: import('./endlessRoad').EndlessRoadSettings; floorColor?: string; floorSourceHeight?: number }
  dressing?: Scene3DDressing
  atmos?: AtmosSettings
  /** Light from the environment (reflections, soft fill). New scenes get a generated room. */
  lighting?: import('./look').Scene3DLighting
  /** Tone mapping, exposure and an optional LUT. Absent: the renderer's previous behaviour. */
  look?: import('./look').Scene3DLook
  workshopScreen?: 'code' | 'error' | 'success'
  slots: Scene3DSlot[]
}

/** A foot landing inside a clip, in clip seconds, written by the humanoid rig as
 * `animations[i].extras.hocuspocus_contacts`. */
export type Scene3DFootContact = {
  t: number
  foot: 'left' | 'right'
  strength: number
}

export type Scene3DClipCatalogEntry = {
  index: number
  name: string
  durationSeconds: number | null
  /** Foot landings, when the GLB records them. */
  contacts?: Scene3DFootContact[]
}

export type Scene3DClipError = {
  code: 'clip_missing' | 'clip_name_mismatch'
  message: string
}
