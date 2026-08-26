import type { SceneLayer } from '../types'

export type SceneGradeMood = 'calm' | 'tense' | 'dreamy' | 'heroic'
export type SceneGradePalette = 'natural' | 'cool' | 'warm' | 'neon'
export type SceneGradeIntensity = 1 | 2 | 3

type EffectsPatch = Partial<NonNullable<SceneLayer['effects']>>

export type SceneGrade = {
  /** Colour temperature of the whole frame. Belongs on every visual layer. */
  palettePatch: EffectsPatch
  /** Emotional temperature. Callers decide which layers carry it. */
  moodPatch: EffectsPatch
}

/**
 * The one place the look of a scene is decided.
 *
 * These numbers were hand-tuned inside the narrative templates and are what
 * separates a shot that reads as graded from one that renders through flat
 * neutral defaults. They existed in two copies — `applyNarrativeSceneControls`
 * and the copilot's `set_scene_grade` — and, contrary to how they look at a
 * glance, those copies were never identical:
 *
 *   - Building a scene from scratch, a neutral palette means "write nothing".
 *   - Editing an existing scene, it must mean "write explicit neutral values",
 *     or asking for a natural palette could never undo a previous grade.
 *
 * `neutral` is that difference, and the only one. Every non-neutral value is
 * reproduced verbatim from the originals: changing one here changes the look
 * of every template, every copilot edit and every compiled recipe at once,
 * which is the point of having a single copy.
 */
export const resolveSceneGrade = (input: {
  mood?: SceneGradeMood
  palette?: SceneGradePalette
  intensity?: SceneGradeIntensity
  neutral?: 'omit' | 'reset'
}): SceneGrade => {
  const intensity = input.intensity ?? 2
  const reset = input.neutral === 'reset'
  const palettePatch: EffectsPatch = input.palette === 'cool' ? { hue: 12, saturation: .9 }
    : input.palette === 'warm' ? { hue: -10, saturation: 1.08 }
      : input.palette === 'neon' ? { hue: 42, saturation: 1.35, contrast: 1.12 }
        : reset ? { hue: 0, saturation: 1 } : {}
  const moodPatch: EffectsPatch = input.mood === 'tense' ? { contrast: 1.15, saturation: .82 }
    : input.mood === 'dreamy' ? { glow: .65 + intensity * .25, saturation: 1.12 }
      : input.mood === 'heroic' ? { glow: .35 + intensity * .18, contrast: 1.13, saturation: 1.12 }
        : input.mood === 'calm' ? { brightness: .98 + intensity * .02 } : {}
  return { palettePatch, moodPatch }
}
