/** Video JS: a video is an ordered list of scenes whose pixels come from code.
 *  Code is data authored by a person or an LLM. It only runs inside the
 *  isolated sandbox (see sandbox.ts); the app never evaluates it. */

export const VIDEOJS_SCHEMA = 'hocuspocus.videojs/v1'

export type VideoJsSceneKind = '2d' | '3d'

export const VIDEOJS_TRANSITIONS = ['none', 'fade', 'slide-left', 'slide-up', 'zoom', 'wipe'] as const
export type VideoJsTransition = typeof VIDEOJS_TRANSITIONS[number]

export interface VideoJsTheme {
  background: string
  surface: string
  primary: string
  secondary: string
  accent: string
  text: string
  muted: string
  font: string
  display: string
}

export interface VideoJsScene {
  id: string
  title: string
  kind: VideoJsSceneKind
  /** Seconds. */
  duration: number
  /** Entry transition from the previous scene. Ignored on the first scene. */
  transition: VideoJsTransition
  transitionDuration: number
  /** Function body that returns `{ setup?, render, overlay? }`. */
  code: string
  notes?: string
}

export interface VideoJsDocument {
  schema: typeof VIDEOJS_SCHEMA
  id: string
  title: string
  width: number
  height: number
  /** The MP4 publisher transcodes to 30 or 60 fps only. */
  fps: 30 | 60
  theme: VideoJsTheme
  scenes: VideoJsScene[]
  /** Last free-text request used to create the video, kept for provenance. */
  prompt: string
  updatedAt: string
}

export interface VideoJsSceneError {
  sceneId: string
  phase: 'compile' | 'setup' | 'render' | 'timeout' | 'runtime'
  message: string
  line?: number
}
