// Shared Video 2D scene types for the Scene Animator and the headless renderer.
import type { Scene, SceneLayer, SceneLayerType } from '../../types'
import type { SeamOccluderKind } from '../seamOccluder'

export type Point = { x: number; y: number; scale: number; opacity?: number; rotation?: number }
export type AnimatorLayerType = SceneLayerType
export type VisualLayerType = Exclude<SceneLayerType, 'camera'>
export type AnimatorLayer = Omit<SceneLayer, 'type' | 'animation'> & {
  type: AnimatorLayerType
  /** Camera-pan response. Distant layers move less; foreground layers move more. */
  parallax?: number
  animation: Omit<SceneLayer['animation'], 'start' | 'end'> & { start: Point; end: Point }
}
export type AnimatorScene = Omit<Scene, 'layers'> & { layers: AnimatorLayer[] }
export type VisualAnimatorLayer = AnimatorLayer & { type: VisualLayerType }
export type LayerState = { x: number; y: number; scale: number; opacity: number; rotation: number; z: number; modelYaw?: number }
export type LayerEffects = Required<NonNullable<SceneLayer['effects']>>
export type LayerStrip = Required<Omit<NonNullable<SceneLayer['strip']>, 'seamOccluder'>> & {
  seamOccluder: { enabled: boolean; kind: SeamOccluderKind; scale: number; opacity: number }
}
export type Atmosphere = Required<Omit<NonNullable<SceneLayer['atmosphere']>, 'emitter'>> & Pick<NonNullable<SceneLayer['atmosphere']>, 'emitter'>
