import type { AnimationClip, Object3D } from 'three'

const FLATTENED = new WeakSet<AnimationClip>()

/** The clip played on the spot: the top-most bone that moves keeps its height (a bob, a jump) but not its travel
 * across the floor, so a run or a dash brought with a model stays under a camera that follows it. Done once per clip,
 * in place: every slot loads its own copy of a model's clips. */
export function flattenRootMotion(root: Object3D, clip: AnimationClip): AnimationClip {
  if (FLATTENED.has(clip)) return clip
  FLATTENED.add(clip)
  let best: { values: ArrayLike<number> & { [index: number]: number }; depth: number } | null = null
  for (const track of clip.tracks) {
    if (!track.name.endsWith('.position')) continue
    const node = root.getObjectByName(track.name.slice(0, -'.position'.length))
    if (!node) continue
    let depth = 0
    for (let parent = node.parent; parent && parent !== root; parent = parent.parent) depth += 1
    if (!best || depth < best.depth) best = { values: track.values as never, depth }
  }
  if (!best || best.values.length < 3) return clip
  const [x, z] = [best.values[0], best.values[2]]
  for (let index = 0; index + 2 < best.values.length; index += 3) {
    best.values[index] = x
    best.values[index + 2] = z
  }
  return clip
}
