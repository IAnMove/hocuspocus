import tables from '../../../../app/shared/world3d_modifiers.json' with { type: 'json' }
import { fromPortraitCamera, toPortraitCamera } from './frameFormat.ts'
import type { Scene3DLook } from './look.ts'
import type { SceneFx } from '../sceneFx/types.ts'
import type { Scene3DCamera, Scene3DDocument, Scene3DLight, Vec3 } from './types.ts'

/** Named modifiers of a shot (`light`, `grade`, `lens`, `camera_template`). The tables are shared with
 * `app/services/world3d_modifiers.py` and `world3d_grades.py`, so the production compiler and
 * `world3d.scene.patch` resolve a name to the same numbers. */
export type NamedLight = { direction: Vec3; intensity: number; color: string; ambient: number; source?: string }
export type GradeFx = { kind: string; intensity: number }
export type Grade = { look: Scene3DLook; tint?: string; fx: GradeFx[] }
export type Lens = { fov: number; source: string }
export type ModifierTables = {
  lights: Record<string, NamedLight>
  grades: Record<string, Grade>
  lenses: Record<string, Lens>
  cameraFamilies: string[]
}

export const MODIFIERS = tables as unknown as ModifierTables
export const LIGHT_NAMES: readonly string[] = Object.keys(MODIFIERS.lights)
export const GRADE_NAMES: readonly string[] = Object.keys(MODIFIERS.grades)
export const LENS_NAMES: readonly string[] = Object.keys(MODIFIERS.lenses)
/** The technique families whose cards are cameras: their camera and framing can be copied onto any shot. */
export const CAMERA_FAMILIES: ReadonlySet<string> = new Set(MODIFIERS.cameraFamilies)
export const GRADE_FX_PREFIX = 'grade-'
/** A scaled framing fov stays inside the framing parser's 8-140 bounds with room to spare. */
export const LENS_FOV_RANGE: readonly [number, number] = [10, 130]

type Lit = Pick<Scene3DDocument, 'light' | 'lighting'>
type Graded = Pick<Scene3DDocument, 'light' | 'look' | 'sfx' | 'duration'>
type Framed = Pick<Scene3DDocument, 'camera' | 'width' | 'height'>
/** A lamp remembers its ungraded colour so the next grade tints the lamp and not the earlier tint. */
type TintedLight = Scene3DLight & { untinted?: string }

/** A named light replaces the document's sun and sets the ambient share; the rest of the lighting stays. */
export function applyNamedLight(document: Lit, name: string): void {
  const preset = MODIFIERS.lights[name]
  if (!preset) throw new Error(`unknown_light:${name}`)
  document.light = { kind: 'directional', direction: [...preset.direction], intensity: preset.intensity, color: preset.color }
  const environment = { source: 'room' as const, rotation: 0, background: 'set' as const, blur: 0, ...document.lighting?.environment, intensity: preset.ambient }
  document.lighting = { ...document.lighting, environment }
}

/** The grade's screen effects over the whole document. The parser fills each cue's preset position, size, colour and seed. */
export function gradeCues(name: string, duration: number): SceneFx[] {
  const grade = MODIFIERS.grades[name]
  if (!grade) throw new Error(`unknown_grade:${name}`)
  return grade.fx.map(cue => ({ id: `${GRADE_FX_PREFIX}${cue.kind}`, kind: cue.kind, start: 0, end: duration, intensity: cue.intensity }) as SceneFx)
}

/** The look, the lamp's gel and the grade's effects; `grade-*` effects of an earlier grade go, every other effect stays. */
export function applyGrade(document: Graded, name: string): void {
  const grade = MODIFIERS.grades[name]
  if (!grade) throw new Error(`unknown_grade:${name}`)
  document.look = { ...grade.look }
  const { untinted, ...light } = (document.light ?? {}) as TintedLight
  const base = untinted || light.color
  if (grade.tint && base) document.light = { ...light, color: tinted(base, grade.tint), untinted: base } as Scene3DLight
  else if (base) document.light = { ...light, color: base }
  const kept = (document.sfx ?? []).filter(cue => !String(cue.id ?? '').startsWith(GRADE_FX_PREFIX))
  document.sfx = [...kept, ...gradeCues(name, document.duration)]
}

export function lensFov(name: string): number {
  const lens = MODIFIERS.lenses[name]
  if (!lens) throw new Error(`unknown_lens:${name}`)
  return lens.fov
}

/** A lens sets the camera's fov; a framing's fovFrom/fovTo keep their move, scaled by the same ratio. */
export function applyLens(document: Pick<Scene3DDocument, 'camera'>, name: string): void {
  const fov = lensFov(name)
  const camera = structuredClone(document.camera)
  const ratio = camera.fov > 0 ? fov / camera.fov : 1
  camera.fov = fov
  const [low, high] = LENS_FOV_RANGE
  if (camera.framing) {
    for (const key of ['fovFrom', 'fovTo'] as const) {
      const value = camera.framing[key]
      if (typeof value === 'number') camera.framing[key] = Math.min(high, Math.max(low, value * ratio))
    }
  }
  document.camera = camera
}

/** The technique's camera and framing on this document, adapted when the two frame formats differ. The document keeps
 * its duration, cast and place; the caller re-targets the framing to its own subject. */
export function copyCamera(document: Framed, technique: Framed): void {
  const portrait = document.height > document.width
  let camera: Scene3DCamera = structuredClone(technique.camera)
  if (portrait && camera.frameFormat !== 'portrait') camera = toPortraitCamera(camera)
  else if (!portrait && camera.frameFormat === 'portrait') camera = fromPortraitCamera(camera)
  document.camera = camera
}

/** #rrggbb or #rgb as channels; anything else is null. */
function rgb(color: string): [number, number, number] | null {
  if (typeof color !== 'string' || !color.startsWith('#') || ![4, 7].includes(color.length)) return null
  const digits = color.length === 4 ? [...color.slice(1)].map(ch => ch + ch).join('') : color.slice(1)
  const channels = [0, 2, 4].map(at => parseInt(digits.slice(at, at + 2), 16))
  return channels.every(Number.isFinite) ? channels as [number, number, number] : null
}

/** A gel over the lamp: each channel multiplied. An unreadable colour is kept as it is. */
export function tinted(color: string, tint: string): string {
  const base = rgb(color), gel = rgb(tint)
  if (!base || !gel) return color
  return '#' + base.map((c, index) => Math.round(c * gel[index] / 255).toString(16).padStart(2, '0')).join('')
}
