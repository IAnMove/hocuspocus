import { CINEMATIC_TEMPLATE_IDS } from './cinematicTemplateIds'
import { SPEECH_TEMPLATE_IDS } from './speech/templateIds'
import type { Scene3DSpeech, Scene3DSoundtrack } from './speech/types'
import { MEDIA_TEMPLATE_IDS } from './mediaTemplateIds'

export type Vec3 = readonly [number, number, number]

export type Scene3DCameraFamily =
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
  ...MEDIA_TEMPLATE_IDS,
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
  faceTravel?: boolean
  turnTo?: number
  easing?: 'linear' | 'smooth'
}

export type Scene3DSlotMedia = 'model3d' | 'image' | 'screen'

export type Scene3DLoop = {
  cylinder: boolean
  speed: number
}

export type Scene3DDressing = 'none' | 'street' | 'space' | 'treadmill' | 'cafe' | 'drive-city' | 'drive-coast' | 'drive-tunnel' | 'citadel' | 'workshop' | 'chase-street' | 'retro-lab' | 'observatory' | 'broadcast-plaza' | 'open-sea' | 'lunar' | 'rooftop' | 'hangar' | 'desert' | 'train' | 'space-lane' | 'jungle' | 'snow' | 'casino'

export type Scene3DSourceRef = {
  workspaceId: string
  filename: string
  url: string
  assetId?: string
}

export type Scene3DSlot = {
  character?: { id: string; name: string; kitRef?: import('../../lib/characterVoice').CharacterKitRef;
    libraryRevision?: number; voice?: import('../../lib/characterVoice').CharacterVoice }
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
  surface?: 'wall' | 'floor' | 'environment'
  appearance?: { start: number; duration: number; color: string }
  textureRepeat?: number
  performance?: 'typing' | 'idle'
  grounded?: boolean
  clip: Scene3DClipRef | null
  clipPlayback?: Scene3DClipPlayback
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
  relativeToFacing?: boolean
}

export type Scene3DLight = {
  kind: 'directional'
  direction: Vec3
  intensity: number
  color: string
}

export type Scene3DDocument = {
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
  /** Spatial effects in world meters. Screen overlays stay on `sfx`. */
  worldSfx?: import('../sceneFx/world').WorldSfx[]
  texts?: import('../../lib/kineticText').KineticText[]
  /** Timeline rate; exported duration is duration / playbackSpeed. */
  playbackSpeed?: number
  templateId: Scene3DTemplateId
  camera: Scene3DCamera
  light: Scene3DLight
  environment?: { reflectiveFloor: boolean; platform: boolean; bloom: number }
  dressing?: Scene3DDressing
  workshopScreen?: 'code' | 'error' | 'success'
  slots: Scene3DSlot[]
}

export type Scene3DClipCatalogEntry = {
  index: number
  name: string
  durationSeconds: number | null
}

export type Scene3DClipError = {
  code: 'clip_missing' | 'clip_name_mismatch'
  message: string
}
