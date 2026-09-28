export const KINETIC_PRESETS = ['impact', 'rise', 'typewriter', 'wave'] as const
export const TEXT_FONTS = ['sans', 'mono', 'display', 'condensed', 'serif', 'hand', 'marker'] as const
export const TEXT_ENTERS = ['none', 'fade', 'impact', 'rise', 'drop', 'typewriter', 'letters', 'words', 'blur', 'wipe', 'scale', 'slide-left', 'slide-right'] as const
export const TEXT_EXITS = ['none', 'fade', 'fall', 'blur', 'wipe', 'scale', 'slide-left', 'slide-right'] as const
export const TEXT_LOOPS = ['none', 'wave', 'pulse', 'shake', 'float', 'flicker'] as const
export const TEXT_WEIGHTS = [400, 500, 600, 700, 800, 900] as const
export const TEXT_ALIGNS = ['left', 'center', 'right'] as const
export const TEXT_BOX_KINDS = ['none', 'solid', 'paper', 'pill', 'bar', 'underline', 'plate'] as const

export type TextFont = (typeof TEXT_FONTS)[number]
export type TextEnter = (typeof TEXT_ENTERS)[number]
export type TextExit = (typeof TEXT_EXITS)[number]
export type TextLoop = (typeof TEXT_LOOPS)[number]
export type TextWeight = (typeof TEXT_WEIGHTS)[number]
export type TextAlign = (typeof TEXT_ALIGNS)[number]
export type TextBoxKind = (typeof TEXT_BOX_KINDS)[number]

export type TextStroke = { color: string; width: number }
export type TextShadow = { color: string; blur: number; x: number; y: number }
export type TextFill = { kind: 'solid' } | { kind: 'gradient'; from: string; to: string; angle: number }
export type TextBox = { kind: TextBoxKind; color: string; opacity: number; padding: number; radius?: number }
export type TextCounter = { from: number; to: number; decimals: number; ease: 'linear' | 'ease' }
export type TextGraphic = { id: string; params?: Record<string, number | string> }
export type TextSpan = { preset: TextEnter | TextExit; duration: number }

export type KineticText = {
  id: string
  text: string
  start: number
  end: number
  preset: (typeof KINETIC_PRESETS)[number]
  x: number
  y: number
  size: number
  color: string
  rotation: number
  font?: TextFont
  enter?: { preset: TextEnter; duration: number }
  exit?: { preset: TextExit; duration: number }
  loop?: TextLoop
  weight?: TextWeight
  align?: TextAlign
  maxWidth?: number
  lineHeight?: number
  letterSpacing?: number
  uppercase?: boolean
  italic?: boolean
  stroke?: TextStroke
  shadow?: TextShadow
  fill?: TextFill
  box?: TextBox
  counter?: TextCounter
  /** Catalog drawing from scene_graphics.json. Absent cues paint text only. */
  graphic?: TextGraphic
  /** Provenance for a template. It does not change painting. */
  template?: string
  /** Live scale added on stored beats. Absent means the cue does not pulse. */
  beatPulse?: number
}

export type TextMotion = {
  elapsed: number
  opacity: number
  scale: number
  dy: number
  dx: number
  letters: number
  blur: number
  clip: number
  wave: boolean
}
