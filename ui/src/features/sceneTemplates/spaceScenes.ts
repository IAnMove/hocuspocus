import type { SceneLayer } from '../../types'
import { asset, atmosphere, camera, cycles, effect, keyframes, repeatPath, type Beat, type BuildContext, type Pose } from './sceneBuilders'
import { sampledPath } from './musicMotionBuilders'
import type { TemplateSlotName } from './catalog'

/** A picture is contained in a frame-shaped box (a 3:1 ship spans the whole box width), while a GLB draws inside a
 * .52 × .75 viewer box: a picture ship gets this share of the GLB scale, so it fits its part of the frame. */
function shipShare(c: BuildContext, slot: TemplateSlotName, picture: number): number {
  return c.bindings[slot]?.type === 'image' ? picture : 1
}
const scaledBeats = (beats: Beat[], share: number): Beat[] => beats.map(beat => beat.scale === undefined ? beat : { ...beat, scale: beat.scale * share })
function ship(c: BuildContext, slot: TemplateSlotName, pose: Pose, picture: number, beats: Beat[] = [], z = 10): SceneLayer {
  const share = shipShare(c, slot, picture)
  const item = asset(c, slot, { ...pose, scale: (pose.scale ?? 1) * share }, z)
  return beats.length ? keyframes(item, scaledBeats(beats, share)) : item
}

const HERO = { x: 28, y: 57 }
const RIVAL = { x: 72, y: 43 }
/** The beam's line: from the first ship's nose across the gap into the rival. */
const BEAM_FROM = { x: 38, y: 55.2 }
const BEAM_TO = { x: 62, y: 46.6 }
// Rotation of that line on a 16:9 frame, so the bolt points where it flies.
const BEAM_ANGLE = Math.atan2((BEAM_TO.y - BEAM_FROM.y) * 9, (BEAM_TO.x - BEAM_FROM.x) * 16) * 180 / Math.PI
const SHOTS = [0, .18, .36]

/** Seconds-based kick: a fast push away from `times` (shot fractions), then an ease back. */
function kick(at: number, times: number[], duration: number): number {
  return Math.max(0, ...times.map(time => {
    const seconds = (at - time) * duration
    if (seconds < 0) return 0
    return seconds < .06 ? seconds / .06 : Math.exp(-(seconds - .06) / .2)
  }))
}

/** When the beams leave the first ship and reach the rival, in shot fractions; a long shot fires more volleys. */
function volleys(c: BuildContext, explode: boolean) {
  const count = explode ? 1 : cycles(c)
  const shots = explode ? [0] : SHOTS
  const each = (start: number) => Array.from({ length: count }, (_, volley) => shots.map(offset => (volley + start + offset) / count)).flat()
  return { count, fires: each(.2), hits: each(.29) }
}

/** Both ships bob out of phase; the first recoils on every shot and the rival is pushed back by every hit. */
function pair(c: BuildContext, explode: boolean): SceneLayer[] {
  const { fires, hits } = volleys(c, explode)
  const samples = Math.max(48, Math.ceil(c.duration * 20))
  const bob = (at: number, phase: number) => Math.sin(2 * Math.PI * at * c.duration / 2.6 + phase)
  const hero = ship(c, 'subject_1', { ...HERO, scale: .64 }, .56, sampledPath(samples, at => ({
    x: HERO.x - 1.4 * kick(at, fires, c.duration), y: HERO.y + .8 * bob(at, 0), rotation: -.8 * kick(at, fires, c.duration),
  })))
  const rival = ship(c, 'prop_1', { ...RIVAL, scale: .52 }, .56, sampledPath(samples, at => ({
    x: RIVAL.x + 1.2 * kick(at, hits, c.duration), y: RIVAL.y + .7 * bob(at, Math.PI), rotation: .8 * kick(at, hits, c.duration),
    opacity: !explode || at < .5 ? 1 : at < .53 ? (.53 - at) / .03 : 0,
  })))
  // A GLB rival turns to face the first ship; a picture is drawn facing the way the user made it.
  if (rival.type === 'model3d') rival.transform.rotationY = 145
  return [hero, rival]
}

function salvo(c: BuildContext, explode: boolean): SceneLayer[] {
  const along = (share: number) => ({ x: BEAM_FROM.x + (BEAM_TO.x - BEAM_FROM.x) * share, y: BEAM_FROM.y + (BEAM_TO.y - BEAM_FROM.y) * share })
  const { count } = volleys(c, explode)
  return (explode ? [0] : SHOTS).map((offset, i) => effect(c, 'bolt', `beam-${i}`, repeatPath([
    { at: 0, ...along(0), opacity: 0, scale: .22, rotation: BEAM_ANGLE },
    { at: .18 + offset, ...along(0), opacity: 0, scale: .22, rotation: BEAM_ANGLE },
    { at: .2 + offset, ...along(.08), opacity: 1, scale: .24, rotation: BEAM_ANGLE },
    { at: .29 + offset, ...along(.92), opacity: 1, scale: .24, rotation: BEAM_ANGLE },
    { at: .31 + offset, ...along(1), opacity: 0, scale: .14, rotation: BEAM_ANGLE },
    { at: 1, opacity: 0 },
  ], count)))
}
const shield = (c: BuildContext) => effect(c, 'shield', 'impact-shield', repeatPath([{ at: 0, ...RIVAL, opacity: 0, scale: .7 }, { at: .28, ...RIVAL, opacity: 0, scale: .7 }, { at: .31, ...RIVAL, opacity: 1, scale: .76 }, { at: .8, ...RIVAL, opacity: .3, scale: .9 }, { at: 1, ...RIVAL, opacity: 0, scale: 1 }], cycles(c)))

function explosion(c: BuildContext): SceneLayer[] {
  return [...pair(c, true), ...salvo(c, true), effect(c, 'burst', 'explosion-flash', [{ at: 0, ...RIVAL, opacity: 0, scale: .05 }, { at: .49, ...RIVAL, opacity: 0, scale: .1 }, { at: .53, ...RIVAL, opacity: 1, scale: .5 }, { at: .68, ...RIVAL, opacity: .8, scale: 1.4 }, { at: 1, ...RIVAL, opacity: 0, scale: 2 }]), effect(c, 'debris', 'explosion-debris', [{ at: 0, ...RIVAL, opacity: 0, scale: .1 }, { at: .52, ...RIVAL, opacity: 0, scale: .1 }, { at: .56, ...RIVAL, opacity: 1, scale: .4 }, { at: 1, ...RIVAL, opacity: 0, scale: 2.3, rotation: 40 }]), camera(c, [{ at: 0, scale: 1.03 }, { at: 1, scale: 1.08 }], .18)]
}

/** The `outcome` choices of space-broadside; `shield` and `explode` are the merged space-shield and space-explosion. */
function broadside(c: BuildContext): SceneLayer[] {
  if (c.options.outcome === 'explode') return explosion(c)
  if (c.options.outcome === 'shield') return [...pair(c, false), ...salvo(c, false), shield(c), camera(c, [{ at: 0, scale: 1.03 }, { at: 1, scale: 1.08 }])]
  return [...pair(c, false), ...salvo(c, false), camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.06 }])]
}

export const spaceScenes: Record<string, (ctx: BuildContext) => SceneLayer[]> = {
  'space-cruise': c => [ship(c, 'subject_1', { scale: .7 }, .6, [{ at: 0, x: 24, y: 61, scale: .5 }, { at: 1, x: 70, y: 43, scale: .85 }]), camera(c, [{ at: 0, x: 46, scale: 1.04 }, { at: 1, x: 55, scale: 1.08 }])],
  'space-orbit': c => {
    const orbiter = ship(c, 'subject_1', { scale: .42 }, .6, [], 20)
    orbiter.animation.orbit = { targetLayerId: 'prop_1', radiusX: 24, radiusY: 12, turns: .65 * c.duration / c.base, phase: -70, facing: 'fixed' }
    return [ship(c, 'prop_1', { x: 50, y: 50, scale: 1.3 }, .5, [], 5), orbiter, camera(c, [{ at: 0, x: 46, scale: 1.1 }, { at: 1, x: 54, scale: 1 }])]
  },
  'space-docking': c => [
    ship(c, 'prop_1', { x: 70, y: 45, scale: 1.2 }, .375, [], 5),
    ship(c, 'subject_1', { scale: .7 }, .5, [{ at: 0, x: 26, y: 66, scale: .8 }, { at: .8, x: 63, y: 49, scale: .35 }, { at: 1, x: 65, y: 48, scale: .32 }]),
    camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.12, x: 54 }]),
  ],
  'space-chase': c => [
    ship(c, 'subject_1', { scale: .7 }, .6, [{ at: 0, x: 21, y: 65 }, { at: .5, x: 42, y: 38 }, { at: 1, x: 70, y: 49 }]),
    ship(c, 'prop_1', { scale: .45 }, .6, [{ at: 0, x: 46, y: 40 }, { at: .5, x: 65, y: 24 }, { at: 1, x: 87, y: 37 }]),
    camera(c, [{ at: 0, x: 44, rotation: -3 }, { at: 1, x: 60, rotation: 3 }], .12), atmosphere(c, 'speedlines'),
  ],
  'space-broadside': broadside,
  'space-warp': c => [ship(c, 'subject_1', { scale: .9 }, .6, [{ at: 0, x: 44, y: 60, scale: .9 }, { at: .4, x: 46, y: 56, scale: .9 }, { at: .58, x: 65, y: 37, scale: .3 }, { at: .7, x: 80, y: 24, scale: .01, opacity: 0 }, { at: 1, opacity: 0 }]), camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.08 }]), atmosphere(c, 'speedlines')],
}
