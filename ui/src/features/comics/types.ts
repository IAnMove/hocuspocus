import type { LanguageIntent } from '../../lib/languageIntent'

export type ComicElementType = 'panel' | 'image' | 'text'
export type ComicBubbleType =
  | 'none' | 'speech' | 'ellipse' | 'rect' | 'thought' | 'whisper'
  | 'caption' | 'scream' | 'electric' | 'burst' | 'cloud'
export type ComicLetteringType = 'caption' | 'dialogue' | 'sound-effect'
export type ComicImageFilter = 'none' | 'bw' | 'sepia' | 'contrast' | 'posterize' | 'halftone'

export interface ComicAsset {
  id: string
  name: string
  kind: 'maestro-output' | 'upload' | 'minimax' | 'local'
  source: string
  thumbnail?: string
  prompt?: string
  provider?: string
  model?: string
  seed?: number
  characterIds?: string[]
  createdAt: string
  missing?: boolean
  metadata?: Record<string, unknown>
}

export interface ComicCharacter {
  id: string
  name: string
  description: string
  role?: string
  personality?: string
  motivation?: string
  voice?: string
  wardrobe?: string
  visualNotes?: string
  negativePrompt?: string
  referenceAssetId?: string
  referenceAssetIds?: string[]
  locked: boolean
}

export interface ComicGlossaryEntry {
  source: string
  translation: string
  note?: string
}

export interface ComicBaseElement {
  id: string
  type: ComicElementType
  x: number
  y: number
  width: number
  height: number
  rotation: number
  zIndex: number
  parentId?: string | null
  locked?: boolean
  visible?: boolean
}

export interface ComicPanelElement extends ComicBaseElement {
  type: 'panel'
  background: string
  borderColor: string
  borderWidth: number
  borderRadius: number
  points?: [number, number][]
}

export interface ComicImageElement extends ComicBaseElement {
  type: 'image'
  assetId: string
  objectFit: 'cover' | 'contain'
  filter: ComicImageFilter
  flipH?: boolean
  flipV?: boolean
  opacity?: number
}

export interface ComicTextElement extends ComicBaseElement {
  type: 'text'
  /** Semantic role is independent from the visual bubble shape. */
  letteringType?: ComicLetteringType
  content: string
  fontSize: number
  fontFamily: string
  color: string
  bold: boolean
  italic: boolean
  align: 'left' | 'center' | 'right'
  bubble: ComicBubbleType
  bubbleBackground: string
  bubbleStrokeColor: string
  bubbleStrokeWidth: number
  lineHeight?: number
  letterSpacing?: number
  autoFit?: boolean
  textFill?: 'solid' | 'gradient'
  gradientStart?: string
  gradientEnd?: string
  textStrokeWidth?: number
  textStrokeColor?: string
  textEffect?: 'none' | 'shadow' | 'extrude' | 'glow'
  textEffectColor?: string
  bubbleSecondary?: string
  bubblePadding?: number
  bubbleShadow?: boolean
  bubbleStrokeStyle?: 'solid' | 'dashed' | 'rough'
  tail?: 'none' | 'top' | 'bottom' | 'left' | 'right'
  tailWidth?: number
}

export type ComicElement = ComicPanelElement | ComicImageElement | ComicTextElement

export interface ComicPage {
  id: string
  width: number
  height: number
  background: string
  elements: ComicElement[]
}

export interface ComicStyle {
  name: string
  promptSuffix: string
  fontFamily: string
  palette: string[]
}

export interface ComicProject {
  version: 2
  id: string
  title: string
  synopsis: string
  language: string
  languageIntent: LanguageIntent
  format: {
    preset: 'a4' | 'us-comic' | 'square' | 'webtoon' | 'custom'
    width: number
    height: number
    dpi: number
  }
  style: ComicStyle
  pageNumbering: { style: 'none' | 'plain' | 'circle' }
  characters: ComicCharacter[]
  translationGlossary?: ComicGlossaryEntry[]
  pages: ComicPage[]
  assets: Record<string, ComicAsset>
  director?: {
    planId: string
    provider: 'maestro' | 'minimax'
    imageModel?: string
    input: ComicDirectorRequest
    plan: ComicPlan
    completedPanelIds: string[]
    failedPanelIds?: string[]
    scriptApprovedAt?: string
    scriptVersion?: number
    /** Maestro generation jobs keyed by planned panel ID.
     *  Kept until the resulting image has been attached so a dropped browser
     *  request can resume the same backend job instead of generating twice. */
    panelJobs?: Record<string, string>
    factualBiography?: boolean
    biographyReviewedAt?: string
  }
  createdAt: string
  updatedAt: string
}

export interface ComicDialogue {
  speakerId?: string
  text: string
  bubbleType: Exclude<ComicBubbleType, 'none'>
}

/** Film-adaptation values that the user explicitly locked on this source beat.
 * Generated storyboard hints are deliberately not overrides: Director remains
 * free to merge, omit or rewrite them until the user edits the corresponding
 * control. */
export type ComicVideoOverrideField =
  | 'included'
  | 'order'
  | 'action'
  | 'renderer'
  | 'fit'
  | 'motion_mode'
  | 'motion_level'
  | 'duration'
  | 'camera'
  | 'video_prompt'
  | 'seed'
  | 'end_frame'
  | 'test_selected'

export interface ComicPlanPanel {
  id: string
  order: number
  narrativeRole: string
  sceneDescription: string
  imagePrompt: string
  characters: string[]
  framing: string
  dialogue: ComicDialogue[]
  captions: string[]
  soundEffects: string[]
  continuityNotes: string
  /** Ready-to-render chronological I2V prompt. Storyboards generate this
   *  alongside the first-frame image instead of waiting for movie conversion. */
  videoPrompt?: string
  /** Short, editable performance/action brief for the film adaptation. Unlike
   *  sceneDescription this describes only what changes after the first frame. */
  videoAction?: string
  durationSeconds?: number
  cameraMove?: 'none' | 'push-in' | 'pull-out' | 'pan-left' | 'pan-right'
  /** Per-shot override for comic-to-video motion. "auto" follows the global
   *  conversion setting; contextual asks the LLM for restrained story acting
   *  from the panel context, living-still uses deterministic micro-motion,
   *  and action uses the authored/LLM action and camera prompt. */
  videoMotion?: 'auto' | 'contextual' | 'living-still' | 'action'
  /** Film adaptation controls are deliberately stored on the plan instead of
   *  changing comic page order or artwork. */
  videoIncluded?: boolean
  videoOrder?: number
  videoRenderer?: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
  videoFit?: 'reframe' | 'cover' | 'contain'
  videoMotionLevel?: 0 | 1 | 2 | 3
  videoTestSelected?: boolean
  videoSeed?: number
  videoSourcePanelIds?: string[]
  videoOverrideFields?: ComicVideoOverrideField[]
  /** Optional end-frame conditioning for this I2V shot. This is not an edit
   *  transition: generated clips are joined separately with hard cuts. */
  videoEndFrame?: 'auto' | 'none' | 'next-panel'
  /** @deprecated Legacy serialized name retained only for project migration. */
  videoTransition?: 'auto' | 'cut' | 'interpolate'
}

export interface ComicPlanPage {
  pageNumber: number
  layoutHint: 'grid' | 'dynamic'
  panels: ComicPlanPanel[]
}

export interface ComicPlan {
  version: 1
  id: string
  title: string
  logline: string
  synopsis: string
  storyStructure?: Array<{
    pageNumber: number
    stage: string
    goal: string
    turningPoint: string
  }>
  language: string
  styleBible: string
  characters: ComicCharacter[]
  pages: ComicPlanPage[]
}

export interface ComicSourceStory {
  id: string
  revision: number
  title: string
}

export interface ComicDirectorRequest {
  /** New comics follow the credential-free global production profile. */
  useGlobalProfile?: boolean
  premise: string
  /** Comic keeps printable lettering/layout; storyboard creates one clean,
   *  video-ready first frame and motion prompt per shot. */
  productionMode?: 'comic' | 'storyboard'
  storyboardAspect?: 'landscape' | 'portrait'
  storyboardQuality?: 'draft' | 'final'
  /** Complete, editable adaptation brief imported from Story Lab. */
  storyContext?: string
  /** Identifies the Story Lab revision used to stage this adaptation. */
  sourceStory?: ComicSourceStory
  pageCount: number
  language: string
  format: ComicProject['format']['preset']
  panelsPerPage: number
  genre: string
  tone: string
  audience: string
  artStyle: string
  /** Canonical year/era, place, architecture, technology and wardrobe. */
  worldContext?: string
  /** Visual elements the image generator must never introduce. */
  forbiddenElements?: string
  /** Reusable world/location reference assets supplied by Story Lab. */
  worldReferenceAssetIds?: string[]
  dialogueDensity: 'low' | 'medium' | 'high'
  /** LLM used only for this comic's planning, revision and translation. */
  writingProvider?: 'maestro' | 'deepseek' | 'minimax' | 'openai' | 'openai-compatible' | 'ollama' | 'grok'
  writingModel?: string
  writingBaseUrl?: string
  provider: 'maestro' | 'minimax'
  imageModel?: string
  characters: ComicCharacter[]
  ending?: string
}
