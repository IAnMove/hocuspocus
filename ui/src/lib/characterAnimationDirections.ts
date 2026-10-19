/** The five directions of a character and the data contract the 3D engine reads from a Character Kit's animations.
 * The same rules as app/services/character_animation_directions.py (read its docstring for the whole contract).
 *
 * Each animation of `kit.animations` may carry `motion` ('walk' | 'idle') and `dir` ('side' | 'front' | 'front34' | 'back34' | 'back').
 * When they are missing, `dir` is the animation's `view` (side, front, front34, back34, back; a bust has none) and `motion` is deduced
 * from `group: cycle` plus an id that starts with `walk` or `idle`. The directions that look left are the same sheets mirrored when
 * they are rendered (never generated). `walkSheet` is the sheet a Series entrance plays: the approved `walk-12`, else `walk`. */
import { animationDef, type KitAnimation } from './characterAnimations'

export const MOTIONS = ['walk', 'idle'] as const
export const DIRS = ['side', 'front', 'front34', 'back34', 'back'] as const
export type AnimationMotion = (typeof MOTIONS)[number]
export type AnimationDir = (typeof DIRS)[number]
export type AnimationContract = { motion?: AnimationMotion; dir?: AnimationDir }
/** Sheets an entrance walks with, best first. */
export const WALK_SHEETS = ['walk-12', 'walk'] as const

const listed = <T extends string>(value: unknown, allowed: readonly T[]): T | undefined => allowed.find(item => item === value)

type Described = Partial<Pick<KitAnimation, 'motion' | 'dir' | 'view' | 'group'>>

/** `{motion?, dir?}` of an animation: what its entry stores, else what its view, group and id say, else what the catalog says about
 * that id. A key that cannot be told is left out. */
export function contractOf(id: string, entry?: Described): AnimationContract {
  const catalogued: Described = animationDef(id) ?? {}
  const stored = entry ?? {}
  const dir = listed(stored.dir, DIRS) ?? listed(stored.view ?? catalogued.view, DIRS)
  const group = stored.group ?? catalogued.group
  const motion = listed(stored.motion, MOTIONS) ?? MOTIONS.find(name => group === 'cycle' && id.startsWith(name)) ?? listed(catalogued.motion, MOTIONS)
  return { ...(motion ? { motion } : {}), ...(dir ? { dir } : {}) }
}

/** The sheets of a kit that do `motion` facing `dir`, best first: more cells, then the kit's own order. Only approved ones unless asked. */
export function sheetsFor(animations: Record<string, KitAnimation> | undefined, motion: AnimationMotion, dir: AnimationDir, approvedOnly = true): Array<[string, KitAnimation]> {
  return Object.entries(animations ?? {})
    .filter(([id, made]) => (!approvedOnly || made.reviewState === 'approved') && contractOf(id, made).motion === motion && contractOf(id, made).dir === dir)
    .sort((a, b) => (b[1].sheet?.count ?? 0) - (a[1].sheet?.count ?? 0))
}

/** The approved sheet an entrance walks with (`walk-12` first, then `walk`); undefined when neither is approved. */
export function walkSheet(animations: Record<string, KitAnimation> | undefined): { id: string; animation: KitAnimation } | undefined {
  for (const id of WALK_SHEETS) {
    const animation = animations?.[id]
    if (animation?.reviewState === 'approved') return { id, animation }
  }
  return undefined
}
