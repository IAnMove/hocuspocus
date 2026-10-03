import type { Scene3DClipRef, Scene3DFootContact } from './types'

/** One clip in a slot's sequence. Times are in scene seconds; the clip plays from `offset` at `speed`.
 *
 * A cue lasts until the next cue starts (or the shot ends); `duration` stops its clock earlier and holds
 * the last pose. The next cue fades in over its own first `fade` seconds while this one keeps playing.
 */
export type Scene3DClipCue = {
  clip: Scene3DClipRef
  start: number
  duration?: number
  fade?: number
  speed?: number
  offset?: number
  loop?: boolean
}

export type CueWeight = { cueIndex: number; weight: number; localTime: number }
export type CueClipDuration = (clip: Scene3DClipRef) => number | null | undefined

export const MAX_CLIP_CUES = 32
export const DEFAULT_CUE_FADE = 0.3
const MAX_SECONDS = 600

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function parseCueClip(raw: unknown): Scene3DClipRef | null {
  const clip = raw as Partial<Scene3DClipRef> | null | undefined
  if (!clip || !Number.isInteger(clip.index) || (clip.index as number) < 0 || typeof clip.name !== 'string' || clip.name.length > 200) return null
  return { index: clip.index as number, name: clip.name }
}

/** The optional fields, each kept only when usable and clamped to its range. */
function cueOptions(value: Partial<Scene3DClipCue>): Partial<Scene3DClipCue> {
  const options: Partial<Scene3DClipCue> = {}
  if (finite(value.duration) && value.duration > 0) options.duration = Math.min(MAX_SECONDS, value.duration)
  if (finite(value.fade) && value.fade >= 0) options.fade = Math.min(10, value.fade)
  if (finite(value.speed)) options.speed = Math.max(0.1, Math.min(4, value.speed))
  if (finite(value.offset) && value.offset >= 0) options.offset = Math.min(MAX_SECONDS, value.offset)
  if (typeof value.loop === 'boolean') options.loop = value.loop
  return options
}

function parseCue(raw: unknown): Scene3DClipCue | null {
  const value = raw as Partial<Scene3DClipCue> | null
  const clip = parseCueClip(value?.clip)
  if (!value || !clip || !finite(value.start) || value.start < 0 || value.start > MAX_SECONDS) return null
  return { clip, start: value.start, ...cueOptions(value) }
}

/** A stored sequence, bounded: invalid cues are dropped, the rest sorted by start (at most 32). */
export function parseClipCues(raw: unknown): Scene3DClipCue[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const cues = raw.slice(0, MAX_CLIP_CUES * 4).map(parseCue).filter((cue): cue is Scene3DClipCue => cue !== null)
    .map((cue, order) => ({ cue, order }))
    .sort((a, b) => a.cue.start - b.cue.start || a.order - b.order)
    .slice(0, MAX_CLIP_CUES)
    .map(item => item.cue)
  return cues.length ? cues : undefined
}

/** The clip time a cue shows at scene time `t`: its clock stops at `duration`, then loops or clamps to the clip. */
export function cueLocalTime(cue: Scene3DClipCue, t: number, clipDuration?: number | null): number {
  const elapsed = Math.min(Math.max(0, t - cue.start), cue.duration ?? Number.POSITIVE_INFINITY)
  const time = (cue.offset ?? 0) + elapsed * (cue.speed ?? 1)
  if (!(clipDuration && clipDuration > 0)) return time
  return cue.loop === false ? Math.min(time, clipDuration) : time % clipDuration
}

function smoothstep(value: number): number {
  const s = Math.max(0, Math.min(1, value))
  return s * s * (3 - 2 * s)
}

/** Which cues show at scene time `t`, with weights summing to 1. A pure function of time: the export
 * averages subframes at fractional times, so nothing may depend on earlier paints.
 * Before the first cue, the first cue holds its start pose. */
export function clipWeightsAt(cues: readonly Scene3DClipCue[], sceneSeconds: number, shotDuration: number, clipDuration?: CueClipDuration): CueWeight[] {
  if (!cues.length) return []
  const t = Math.max(0, Math.min(Math.max(0, shotDuration), sceneSeconds))
  const duration = (index: number) => clipDuration?.(cues[index].clip) ?? null
  let active = -1
  for (let index = 0; index < cues.length && cues[index].start <= t; index++) active = index
  if (active < 0) return [{ cueIndex: 0, weight: 1, localTime: cueLocalTime(cues[0], cues[0].start, duration(0)) }]
  const cue = cues[active]
  const fade = cue.fade ?? DEFAULT_CUE_FADE
  const incoming = active > 0 && fade > 0 ? smoothstep((t - cue.start) / fade) : 1
  const current = { cueIndex: active, weight: incoming, localTime: cueLocalTime(cue, t, duration(active)) }
  if (incoming >= 1) return [{ ...current, weight: 1 }]
  return [{ cueIndex: active - 1, weight: 1 - incoming, localTime: cueLocalTime(cues[active - 1], t, duration(active - 1)) }, current]
}

/** The scene time a cue's clip stops being shown: the next cue's start plus its fade, or the shot end. */
function cueEnd(cues: readonly Scene3DClipCue[], index: number, shotDuration: number): number {
  const next = cues[index + 1]
  const end = next ? next.start + (next.fade ?? DEFAULT_CUE_FADE) : shotDuration
  const own = cues[index].duration
  return Math.min(shotDuration, end, own == null ? Number.POSITIVE_INFINITY : cues[index].start + own)
}

function landingTimes(cue: Scene3DClipCue, contact: Scene3DFootContact, clipDuration: number, end: number): number[] {
  const speed = cue.speed ?? 1, offset = cue.offset ?? 0
  if (cue.loop === false) {
    const at = cue.start + (contact.t - offset) / speed
    return contact.t >= offset && contact.t <= clipDuration && at <= end ? [at] : []
  }
  const first = ((contact.t - offset) % clipDuration + clipDuration) % clipDuration
  const times: number[] = []
  for (let at = cue.start + first / speed; at <= end; at += clipDuration / speed) times.push(at)
  return times
}

/** Foot landings of a sequence in scene time, for footsteps. A landing counts while its cue weighs at least half. */
export function cueContactsInScene(
  cues: readonly Scene3DClipCue[],
  catalogOf: (clip: Scene3DClipRef) => { durationSeconds: number | null; contacts?: Scene3DFootContact[] } | undefined,
  shotDuration: number,
): Array<Scene3DFootContact & { sceneTime: number; cueIndex: number }> {
  const clipDuration: CueClipDuration = clip => catalogOf(clip)?.durationSeconds ?? null
  const found: Array<Scene3DFootContact & { sceneTime: number; cueIndex: number }> = []
  cues.forEach((cue, cueIndex) => {
    const entry = catalogOf(cue.clip)
    const length = entry?.durationSeconds
    if (!entry?.contacts?.length || !length || length <= 0) return
    const end = cueEnd(cues, cueIndex, shotDuration)
    for (const contact of entry.contacts) {
      for (const sceneTime of landingTimes(cue, contact, length, end)) {
        const weight = clipWeightsAt(cues, sceneTime, shotDuration, clipDuration).find(item => item.cueIndex === cueIndex)?.weight ?? 0
        if (weight >= 0.5) found.push({ ...contact, sceneTime, cueIndex })
      }
    }
  })
  return found.sort((a, b) => a.sceneTime - b.sceneTime || a.foot.localeCompare(b.foot))
}
