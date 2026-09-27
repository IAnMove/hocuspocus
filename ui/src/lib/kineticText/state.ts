import { legacyTextState } from './legacy'
import { displayedKineticText } from './layout'
import { derivedTextMotion, isLegacyKineticText } from './parse'
import type { KineticText, TextEnter, TextExit, TextMotion } from './types'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

function revealCount(text: string, elapsed: number, duration: number, words: boolean) {
  const units = words ? text.split(/\s+/).filter(Boolean) : Array.from(text)
  const progress = clamp(elapsed / Math.max(0.05, duration), 0, 1)
  return Math.ceil(units.length * progress)
}

function enterShift(preset: TextEnter, enter: number) {
  const left = 1 - enter
  if (preset === 'impact') return { scale: 1 + .65 * left ** 2 * Math.cos(enter * Math.PI * 3), opacity: Math.min(1, enter * 5) }
  if (preset === 'rise') return { dy: left ** 3 * .22, opacity: Math.min(1, enter * 5) }
  if (preset === 'drop') return { dy: -(left ** 3) * .22, opacity: Math.min(1, enter * 5) }
  if (preset === 'slide-left') return { dx: -left * .18, opacity: Math.min(1, enter * 5) }
  if (preset === 'slide-right') return { dx: left * .18, opacity: Math.min(1, enter * 5) }
  if (preset === 'scale') return { scale: .6 + .4 * enter, opacity: Math.min(1, enter * 5) }
  if (preset === 'blur') return { blur: left * 14, opacity: Math.min(1, enter * 5) }
  if (preset === 'wipe') return { clip: enter, opacity: 1 }
  if (preset === 'fade') return { opacity: enter }
  if (preset === 'none') return { opacity: 1 }
  return { opacity: Math.min(1, enter * 5) }
}

function exitShift(preset: TextExit, exit: number) {
  const left = 1 - exit
  if (preset === 'none') return { opacity: 1 }
  if (preset === 'fall') return { dy: left * .2, opacity: exit }
  if (preset === 'blur') return { blur: left * 14, opacity: exit }
  if (preset === 'wipe') return { clip: exit, opacity: 1 }
  if (preset === 'scale') return { scale: .6 + .4 * exit, opacity: exit }
  if (preset === 'slide-left') return { dx: -left * .18, opacity: exit }
  if (preset === 'slide-right') return { dx: left * .18, opacity: exit }
  return { opacity: exit }
}

function loopShift(cue: KineticText, elapsed: number) {
  if (cue.loop === 'pulse') return { scale: 1 + .045 * Math.sin(elapsed * 6) }
  if (cue.loop === 'shake') return { dx: Math.sin(elapsed * 40) * .006, dy: Math.cos(elapsed * 37) * .004 }
  if (cue.loop === 'float') return { dy: Math.sin(elapsed * 2) * .015 }
  if (cue.loop === 'flicker') return { opacity: .72 + .28 * (.5 + .5 * Math.sin(elapsed * 28)) }
  return {}
}

type Shift = { opacity?: number; scale?: number; dy?: number; dx?: number; blur?: number; clip?: number }
const pick = (value: number | undefined, fallback: number) => value == null ? fallback : value

function typedEntrance(preset: TextEnter) {
  return preset === 'typewriter' || preset === 'letters' || preset === 'words'
}

function enterSeconds(cue: KineticText, span: number, preset: TextEnter) {
  if (cue.enter) return cue.enter.duration
  return typedEntrance(preset) ? Math.min(1.7, span * .65) : Math.min(.65, span / 3)
}

function letterCount(text: string, elapsed: number, duration: number, preset: TextEnter) {
  if (preset === 'words') return revealCount(text, elapsed, duration, true)
  if (preset === 'typewriter' || preset === 'letters') return revealCount(text, elapsed, duration, false)
  return Array.from(text).length
}

function combine(elapsed: number, enter: Shift, exit: Shift, loop: Shift, letters: number, wave: boolean): TextMotion {
  return {
    elapsed,
    opacity: pick(enter.opacity, 1) * pick(exit.opacity, 1) * pick(loop.opacity, 1),
    scale: pick(enter.scale, 1) * pick(exit.scale, 1) * pick(loop.scale, 1),
    dy: pick(enter.dy, 0) + pick(exit.dy, 0) + pick(loop.dy, 0),
    dx: pick(enter.dx, 0) + pick(exit.dx, 0) + pick(loop.dx, 0),
    letters,
    blur: pick(enter.blur, 0) + pick(exit.blur, 0),
    clip: pick(enter.clip, 1) * pick(exit.clip, 1),
    wave,
  }
}

function v2State(cue: KineticText, seconds: number, text: string): TextMotion {
  const elapsed = seconds - cue.start
  const span = cue.end - cue.start
  const derived = derivedTextMotion(cue.preset)
  const enterPreset = cue.enter?.preset ?? derived.enter
  const exitPreset = cue.exit?.preset ?? derived.exit
  const enterDuration = enterSeconds(cue, span, enterPreset)
  const exitDuration = cue.exit?.duration ?? Math.min(.3, span / 3)
  return combine(
    elapsed,
    enterShift(enterPreset, clamp(elapsed / Math.max(.05, enterDuration), 0, 1)),
    exitShift(exitPreset, clamp((cue.end - seconds) / Math.max(.05, exitDuration), 0, 1)),
    loopShift(cue, elapsed),
    letterCount(text, elapsed, enterDuration, enterPreset),
    (cue.loop ?? derived.loop) === 'wave',
  )
}

/** Pure time sampling. Seeking backwards never depends on the last painted frame. */
export function kineticTextState(cue: KineticText, seconds: number): TextMotion | ReturnType<typeof legacyTextState> | null {
  if (seconds < cue.start || seconds >= cue.end) return null
  if (isLegacyKineticText(cue)) return legacyTextState(cue, seconds)
  return v2State(cue, seconds, displayedKineticText(cue, seconds))
}
