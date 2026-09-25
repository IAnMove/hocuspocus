import { fxRandom } from './types'

/** One polyline of a bolt in unit space: y runs from the source (0) to the
 *  strike point (1); x and z are sideways offsets in the same units. `order`
 *  is how far along the stroke each point lights up, so a leader can creep
 *  down the channel before the return stroke fills it. */
export type BoltChannel = {
  points: [number, number, number][]
  order: number[]
  width: number
}

/** Brightness of one moment of a strike. `leader` is the lit fraction of the
 *  channel, `flash` the sky/scene illumination it throws. */
export type StrikeState = { strike: number; brightness: number; leader: number; flash: number }

type Vec = [number, number, number]

/** Midpoint displacement: jagged at every scale, like a real discharge. */
function displace(from: Vec, to: Vec, seed: number, salt: number, levels: number, roughness: number): Vec[] {
  let points: Vec[] = [from, to]
  for (let level = 0; level < levels; level++) {
    const next: Vec[] = [points[0]]
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i]
      const length = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2])
      const key = salt * 131 + level * 1009 + i * 7
      const spread = length * roughness
      next.push([
        (a[0] + b[0]) / 2 + (fxRandom(seed, key) - .5) * spread,
        (a[1] + b[1]) / 2 + (fxRandom(seed, key + 1) - .5) * spread * .35,
        (a[2] + b[2]) / 2 + (fxRandom(seed, key + 2) - .5) * spread,
      ], b)
    }
    points = next
  }
  return points
}

function arcOrder(points: Vec[], start: number, span: number): number[] {
  const lengths = [0]
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i]
    lengths.push(lengths[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]))
  }
  const total = lengths.at(-1) || 1
  return lengths.map(length => start + span * length / total)
}

/** The same seed always yields the same bolt, so scrubbing and export agree. */
export function boltChannels(seed: number, options: { branches?: number; detail?: number; roughness?: number } = {}): BoltChannel[] {
  const detail = options.detail ?? 6, roughness = options.roughness ?? .42
  const lean = (fxRandom(seed, 3) - .5) * .5
  const main = displace([0, 0, 0], [lean, 1, (fxRandom(seed, 4) - .5) * .3], seed, 1, detail, roughness)
  const channels: BoltChannel[] = [{ points: main, order: arcOrder(main, 0, 1), width: 1 }]
  const branches = options.branches ?? 7
  for (let b = 0; b < branches; b++) {
    const at = Math.floor((.08 + fxRandom(seed, 40 + b) * .72) * (main.length - 1))
    const origin = main[at]
    const side = fxRandom(seed, 60 + b) < .5 ? -1 : 1
    const reach = (.14 + fxRandom(seed, 80 + b) * .3) * (1 - origin[1] * .55)
    const angle = side * (.35 + fxRandom(seed, 100 + b) * .6)
    const tip: Vec = [origin[0] + Math.sin(angle) * reach, origin[1] + Math.cos(angle) * reach, origin[2] + (fxRandom(seed, 120 + b) - .5) * reach]
    const path = displace(origin, tip, seed, 10 + b, 4, roughness * 1.1)
    const startOrder = at / (main.length - 1)
    channels.push({ points: path, order: arcOrder(path, startOrder, reach * .9), width: .5 - b * .02 })
    if (reach > .22) {
      const twigAt = path[Math.floor(path.length * .45)]
      const twigAngle = angle + side * (.4 + fxRandom(seed, 140 + b) * .4)
      const twigReach = reach * (.35 + fxRandom(seed, 160 + b) * .25)
      const twigTip: Vec = [twigAt[0] + Math.sin(twigAngle) * twigReach, twigAt[1] + Math.cos(twigAngle) * twigReach, twigAt[2]]
      const twig = displace(twigAt, twigTip, seed, 30 + b, 3, roughness * 1.2)
      const twigStart = startOrder + reach * .4
      channels.push({ points: twig, order: arcOrder(twig, twigStart, twigReach * .9), width: .26 })
    }
  }
  return channels
}

const LEADER = .07
const STRIKE_LENGTH = 1.05

/** Seconds of each strike's start within a cue. Long cues re-strike at
 *  irregular intervals; each strike gets its own channel shape. */
export function strikeTimes(seed: number, span: number, gap: [number, number] = [.55, 1.6]): number[] {
  const times = [0]
  for (let i = 1; times.length < 2000; i++) {
    const next = times[i - 1] + gap[0] + fxRandom(seed, 500 + i) * (gap[1] - gap[0])
    if (next > span - .2) break
    times.push(next)
  }
  return times
}

/** Leader, return stroke, restrike flicker and afterglow of the strike that
 *  is live at `time` seconds into the cue. */
export function strikeState(seed: number, time: number, span: number, gap?: [number, number]): StrikeState {
  const times = strikeTimes(seed, span, gap)
  let strike = 0
  for (let i = times.length - 1; i >= 0; i--) if (time >= times[i]) { strike = i; break }
  const local = time - times[strike]
  const tail = Math.max(0, Math.min(1, (span - time) * 8))
  if (local < 0 || local > STRIKE_LENGTH) return { strike, brightness: 0, leader: 0, flash: 0 }
  if (local < LEADER) {
    const leader = Math.pow(local / LEADER, .7)
    return { strike, brightness: .45 * tail, leader, flash: .05 * tail }
  }
  const after = local - LEADER
  let brightness = 1.6 * Math.exp(-after / .075)
  // Most strikes re-illuminate the same channel two or three times.
  for (let pulse = 0; pulse < 3; pulse++) {
    const at = .09 + pulse * .085 + fxRandom(seed, 900 + strike * 7 + pulse) * .05
    const power = fxRandom(seed, 950 + strike * 7 + pulse)
    if (power < .3 || after < at) continue
    brightness += (.5 + power * .7) * Math.exp(-(after - at) / .045)
  }
  brightness += .16 * Math.exp(-after / .4)
  brightness *= tail
  return { strike, brightness, leader: 1, flash: Math.max(0, brightness - .25) * .6 }
}

/** Seconds of each strike's return stroke, for the thunder that follows. */
export function strokeTimes(seed: number, span: number, gap?: [number, number]) {
  return strikeTimes(seed, span, gap).map(time => time + LEADER)
}
