export type ComicElementType = 'panel' | 'image' | 'text'
export type ComicBubbleType =
  | 'none' | 'speech' | 'ellipse' | 'rect' | 'thought' | 'whisper'
  | 'caption' | 'scream' | 'electric' | 'burst' | 'cloud'
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
  wardrobe?: string
  referenceAssetId?: string
  locked: boolean
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
  format: {
    preset: 'a4' | 'us-comic' | 'square' | 'webtoon' | 'custom'
    width: number
    height: number
    dpi: number
  }
  style: ComicStyle
  pageNumbering: { style: 'none' | 'plain' | 'circle' }
  characters: ComicCharacter[]
  pages: ComicPage[]
  assets: Record<string, ComicAsset>
  director?: {
    planId: string
    provider: 'maestro' | 'minimax'
    imageModel?: string
    input: ComicDirectorRequest
    plan: ComicPlan
    completedPanelIds: string[]
    /** Maestro generation jobs keyed by planned panel ID.
     *  Kept until the resulting image has been attached so a dropped browser
     *  request can resume the same backend job instead of generating twice. */
    panelJobs?: Record<string, string>
  }
  createdAt: string
  updatedAt: string
}

export interface ComicDialogue {
  speakerId?: string
  text: string
  bubbleType: Exclude<ComicBubbleType, 'none'>
}

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

export interface ComicDirectorRequest {
  premise: string
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
  dialogueDensity: 'low' | 'medium' | 'high'
  provider: 'maestro' | 'minimax'
  imageModel?: string
  characters: ComicCharacter[]
  ending?: string
}
