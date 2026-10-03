import type { Scene3DClipRef, Scene3DMotion, Scene3DSlot, Vec3 } from './types'

/** A slot's path walked by a baked humanoid clip with the feet planted: the clip moves the hips, so the slot stays put. */
export type Scene3DMotionWalk = { sourceUrl: string; clip: Scene3DClipRef; key: string }

export const MAX_PATH_POINTS = 62

/** What the bake depends on. A different key means the path or its placement changed and the bake is stale. */
export function walkKey(slot: Scene3DSlot, duration: number): string {
  const motion = slot.motion
  if (!motion) return ''
  return JSON.stringify([slot.position, slot.rotationY, slot.scale, motion.to, motion.via ?? null, motion.points ?? null, duration])
}

/** The slot plays a baked walk of exactly its current path. */
export function isWalkBaked(slot: Scene3DSlot, duration: number): boolean {
  const walk = slot.motion?.walk
  return Boolean(walk && walk.key === walkKey(slot, duration) && walk.sourceUrl === slot.sourceUrl
    && slot.clip && slot.clip.index === walk.clip.index && slot.clip.name === walk.clip.name)
}

/** The path's ground points, start first: the waypoints, or a sampled curve through `via`, or a straight line. */
export function motionPathPoints(slot: Scene3DSlot): Vec3[] {
  const motion = slot.motion
  if (!motion) return []
  if (motion.points?.length) return [slot.position, ...motion.points, motion.to]
  if (!motion.via) return [slot.position, motion.to]
  const via = motion.via
  return Array.from({ length: 9 }, (_unused, index) => {
    const t = index / 8
    return slot.position.map((start, axis) => (1 - t) ** 2 * start + 2 * (1 - t) * t * via[axis] + t * t * motion.to[axis]) as unknown as Vec3
  })
}

/** Scene points into the model's own space, as the server bakes it: undo the slot's position, turn and scale. */
export function toModelSpace(points: readonly Vec3[], placement: { position: Vec3; rotationY: number; scale: number }): [number, number][] {
  const cos = Math.cos(-placement.rotationY), sin = Math.sin(-placement.rotationY)
  const scale = Math.max(1e-6, placement.scale)
  return points.map(point => {
    const x = point[0] - placement.position[0], z = point[2] - placement.position[2]
    return [(x * cos + z * sin) / scale, (-x * sin + z * cos) / scale]
  })
}

/** Centripetal Catmull-Rom through the points, sampled densely, with arc lengths; the same curve the server walks. */
export function catmullRomPath(points: readonly Vec3[], perSegment = 24) {
  const flat = points.map(point => [point[0], point[2]] as [number, number])
  const samples: [number, number][] = [flat[0]]
  if (flat.length === 2) {
    for (let i = 1; i <= perSegment; i++) samples.push(lerp2(flat[0], flat[1], i / perSegment))
  } else {
    const padded = [mirror(flat[0], flat[1]), ...flat, mirror(flat[flat.length - 1], flat[flat.length - 2])]
    for (let i = 1; i < padded.length - 2; i++) {
      const [p0, p1, p2, p3] = padded.slice(i - 1, i + 3)
      const t1 = Math.max(Math.sqrt(dist(p0, p1)), 1e-6), t2 = t1 + Math.max(Math.sqrt(dist(p1, p2)), 1e-6), t3 = t2 + Math.max(Math.sqrt(dist(p2, p3)), 1e-6)
      for (let k = 1; k <= perSegment; k++) samples.push(centripetal(p0, p1, p2, p3, t1, t2, t3, t1 + (t2 - t1) * k / perSegment))
    }
  }
  const arc = [0]
  for (let i = 1; i < samples.length; i++) arc.push(arc[i - 1] + dist(samples[i - 1], samples[i]))
  return { samples, arc, length: arc[arc.length - 1] }
}

/** Position and travel direction at a fraction 0..1 of the path's length. */
export function pathAt(path: ReturnType<typeof catmullRomPath>, fraction: number): { x: number; z: number; heading: number } {
  const target = Math.max(0, Math.min(1, fraction)) * path.length
  let index = 1
  while (index < path.arc.length - 1 && path.arc[index] < target) index++
  const span = Math.max(1e-9, path.arc[index] - path.arc[index - 1])
  const [x, z] = lerp2(path.samples[index - 1], path.samples[index], (target - path.arc[index - 1]) / span)
  const dx = path.samples[index][0] - path.samples[index - 1][0], dz = path.samples[index][1] - path.samples[index - 1][1]
  return { x, z, heading: Math.atan2(dx, dz) }
}

export function parseMotionPoints(raw: unknown): Vec3[] | undefined {
  if (!Array.isArray(raw) || !raw.length || raw.length > MAX_PATH_POINTS) return undefined
  const points = raw.filter(item => Array.isArray(item) && item.length === 3 && item.every(Number.isFinite)) as Vec3[]
  return points.length === raw.length ? points.map(point => [...point] as unknown as Vec3) : undefined
}

export function parseMotionWalk(raw: unknown): Scene3DMotion['walk'] {
  const value = raw as Partial<Scene3DMotionWalk> | undefined
  const clip = value?.clip
  if (!value || typeof value.sourceUrl !== 'string' || !value.sourceUrl || value.sourceUrl.length > 2000) return undefined
  if (typeof value.key !== 'string' || !value.key || value.key.length > 20000) return undefined
  if (!clip || !Number.isInteger(clip.index) || clip.index < 0 || typeof clip.name !== 'string') return undefined
  return { sourceUrl: value.sourceUrl, clip: { index: clip.index, name: clip.name }, key: value.key }
}

function centripetal(p0: [number, number], p1: [number, number], p2: [number, number], p3: [number, number], t1: number, t2: number, t3: number, t: number): [number, number] {
  const a1 = mix(p0, p1, t / t1), a2 = mix(p1, p2, (t - t1) / (t2 - t1)), a3 = mix(p2, p3, (t - t2) / (t3 - t2))
  const b1 = mix(a1, a2, t / t2), b2 = mix(a2, a3, (t - t1) / (t3 - t1))
  return mix(b1, b2, (t - t1) / (t2 - t1))
}

function mix(a: [number, number], b: [number, number], t: number): [number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

const lerp2 = mix

function mirror(edge: [number, number], inner: [number, number]): [number, number] {
  return [2 * edge[0] - inner[0], 2 * edge[1] - inner[1]]
}

function dist(a: [number, number], b: [number, number]): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1])
}
