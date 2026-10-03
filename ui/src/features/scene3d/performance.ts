import type { Scene3DClipPlayback, Scene3DFootContact, Scene3DMotion, Scene3DSlot, Vec3 } from './types.ts'
import { catmullRomPath, isWalkBaked, motionPathPoints, parseMotionPoints, parseMotionWalk, pathAt } from './walkPath.ts'

export function parseClipPlayback(raw: unknown): Scene3DClipPlayback | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Scene3DClipPlayback
  return {
    speed: typeof value.speed === 'number' && Number.isFinite(value.speed) ? Math.max(0.1, Math.min(4, value.speed)) : 1,
    start: typeof value.start === 'number' && Number.isFinite(value.start) ? Math.max(0, value.start) : 0,
    loop: value.loop !== false,
  }
}

/** Fit the remaining source animation once into the current shot, without wrapping. */
export function fitClipPlayback(duration: number | null | undefined, shotDuration: number, raw?: Scene3DClipPlayback): Scene3DClipPlayback | undefined {
  if (duration == null || !Number.isFinite(duration) || duration <= 0 || !Number.isFinite(shotDuration) || shotDuration <= 0) return undefined
  const start = parseClipPlayback(raw)?.start ?? 0
  const speed = (duration - start) / shotDuration
  const tolerance = 16 * Number.EPSILON
  if (speed < 0.1 - tolerance || speed > 4 + tolerance) return undefined
  return { start, speed: Math.max(0.1, Math.min(4, speed)), loop: false }
}

export function parseMotion(raw: unknown): Scene3DMotion | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Scene3DMotion
  if (!Array.isArray(value.to) || value.to.length !== 3 || !value.to.every(Number.isFinite)) return undefined
  return {
    to: [...value.to] as unknown as Vec3,
    via: Array.isArray(value.via) && value.via.length === 3 && value.via.every(Number.isFinite) ? [...value.via] as unknown as Vec3 : undefined,
    faceTravel: value.faceTravel === true,
    turnTo: typeof value.turnTo === 'number' && Number.isFinite(value.turnTo) ? value.turnTo : undefined,
    easing: value.easing === 'smooth' ? 'smooth' : 'linear',
    ...optionalField('points', parseMotionPoints(value.points)),
    ...optionalField('walk', parseMotionWalk(value.walk)),
  }
}

function optionalField<K extends string, V>(key: K, value: V | undefined): { [P in K]?: V } {
  return (value === undefined ? {} : { [key]: value }) as { [P in K]?: V }
}

export function slotPoseAtTime(slot: Scene3DSlot, seconds: number, duration: number) {
  // A baked walk moves the hips itself; the slot stays at its start.
  if (!slot.motion || isWalkBaked(slot, duration)) return { position: slot.position, rotationY: slot.rotationY }
  const progress = Math.max(0, Math.min(1, seconds / Math.max(0.001, duration)))
  const t = slot.motion.easing === 'smooth' ? progress * progress * (3 - 2 * progress) : progress
  if (slot.motion.points?.length) return waypointPose(slot, t)
  const via = slot.motion.via
  const position = slot.position.map((v, i) => via
    ? (1 - t) ** 2 * v + 2 * (1 - t) * t * via[i] + t * t * slot.motion!.to[i]
    : v + (slot.motion!.to[i] - v) * t) as unknown as Vec3
  const tangent = slot.position.map((v, i) => via
    ? 2 * (1 - t) * (via[i] - v) + 2 * t * (slot.motion!.to[i] - via[i])
    : slot.motion!.to[i] - v)
  const facing = slot.motion.faceTravel && Math.hypot(tangent[0], tangent[2]) > .0001
    ? Math.atan2(tangent[0], tangent[2]) : slot.rotationY + ((slot.motion.turnTo ?? slot.rotationY) - slot.rotationY) * t
  return {
    position,
    rotationY: facing,
  }
}

function waypointPose(slot: Scene3DSlot, t: number) {
  const motion = slot.motion!
  const at = pathAt(catmullRomPath(motionPathPoints(slot)), t)
  const height = slot.position[1] + (motion.to[1] - slot.position[1]) * t
  const rotationY = motion.faceTravel ? at.heading : slot.rotationY + ((motion.turnTo ?? slot.rotationY) - slot.rotationY) * t
  return { position: [at.x, height, at.z] as unknown as Vec3, rotationY }
}

/** Start is a source-clip seek, independent of the scene's clock and speed. */
export function performanceClipTime(seconds: number, duration: number | null, raw?: Scene3DClipPlayback): number | null {
  if (duration == null || !Number.isFinite(duration) || duration <= 0) return null
  const playback = parseClipPlayback(raw)
  const time = (playback?.start ?? 0) + Math.max(0, seconds) * (playback?.speed ?? 1)
  return playback?.loop === false ? Math.min(duration, time) : time % duration
}

const MAX_CONTACTS = 256

/** Foot landings from an animation's `userData.hocuspocus_contacts`; anything malformed is dropped. */
export function parseFootContacts(raw: unknown): Scene3DFootContact[] {
  if (!Array.isArray(raw)) return []
  const found: Scene3DFootContact[] = []
  for (const item of raw.slice(0, MAX_CONTACTS)) {
    const value = item as Partial<Scene3DFootContact> | null
    if (!value || typeof value.t !== 'number' || !Number.isFinite(value.t) || value.t < 0) continue
    if (value.foot !== 'left' && value.foot !== 'right') continue
    const strength = typeof value.strength === 'number' && Number.isFinite(value.strength) ? Math.max(0, Math.min(1, value.strength)) : 0.5
    found.push({ t: value.t, foot: value.foot, strength })
  }
  return found.sort((a, b) => a.t - b.t || a.foot.localeCompare(b.foot))
}

type ContactClock = { clipDuration: number; sceneDuration: number; start: number; speed: number }

function playedOnce(contact: Scene3DFootContact, clock: ContactClock): number[] {
  const at = (contact.t - clock.start) / clock.speed
  return contact.t <= clock.clipDuration && at >= 0 && at <= clock.sceneDuration ? [at] : []
}

function playedLooping(contact: Scene3DFootContact, clock: ContactClock): number[] {
  const { clipDuration, sceneDuration, start, speed } = clock
  const offset = ((contact.t % clipDuration) - (start % clipDuration) + clipDuration) % clipDuration
  const times: number[] = []
  for (let at = offset / speed; at <= sceneDuration; at += clipDuration / speed) times.push(at)
  return times
}

/** Scene times of a clip's foot landings, with the same clock as `performanceClipTime`: the clip plays from
 * `start` at `speed`, wrapping when it loops and holding its last frame when it does not. A slot whose
 * performance is idle holds frame 0 and has no landings; callers skip it. */
export function footContactsInScene(
  contacts: readonly Scene3DFootContact[],
  clipDuration: number | null,
  sceneDuration: number,
  raw?: Scene3DClipPlayback,
): Array<Scene3DFootContact & { sceneTime: number }> {
  if (clipDuration == null || !Number.isFinite(clipDuration) || clipDuration <= 0 || !(sceneDuration > 0)) return []
  const playback = parseClipPlayback(raw)
  const clock = { clipDuration, sceneDuration, start: playback?.start ?? 0, speed: playback?.speed ?? 1 }
  const timesOf = playback?.loop === false ? playedOnce : playedLooping
  return contacts
    .flatMap(contact => timesOf(contact, clock).map(sceneTime => ({ ...contact, sceneTime })))
    .sort((a, b) => a.sceneTime - b.sceneTime || a.foot.localeCompare(b.foot))
}

export function reviewClipNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined
}

export function paintClipNumber(context: CanvasRenderingContext2D, width: number, height: number, number?: number) {
  if (!reviewClipNumber(number)) return
  const unit = height / 720
  const text = `CLIP ${String(number).padStart(2, '0')}`
  context.save()
  context.font = `600 ${Math.round(19 * unit)}px monospace`
  const boxWidth = context.measureText(text).width + 28 * unit
  const x = width - boxWidth - 24 * unit
  context.fillStyle = 'rgba(5, 10, 18, 0.82)'
  context.fillRect(x, 22 * unit, boxWidth, 38 * unit)
  context.fillStyle = '#e7faff'
  context.textBaseline = 'middle'
  context.fillText(text, x + 14 * unit, 41 * unit)
  context.restore()
}
