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

function v2State(cue: KineticText, seconds: number, text: string): TextMotion {
  const elapsed = seconds - cue.start
  const span = cue.end - cue.start
  const derived = derivedTextMotion(cue.preset)
  const enterPreset: TextEnter = cue.enter?.preset ?? derived.enter
  const exitPreset: TextExit = cue.exit?.preset ?? derived.exit
  const enterDuration = cue.enter?.duration ?? (enterPreset === 'typewriter' || enterPreset === 'letters' || enterPreset === 'words' ? Math.min(1.7, span * .65) : Math.min(.65, span / 3))
  const exitDuration = cue.exit?.duration ?? Math.min(.3, span / 3)
  const enterT = clamp(elapsed / Math.max(.05, enterDuration), 0, 1)
  const exitT = clamp((cue.end - seconds) / Math.max(.05, exitDuration), 0, 1)
  const enter = enterShift(enterPreset, enterT)
  const exit = exitShift(exitPreset, exitT)
  const loop = loopShift(cue, elapsed)
  const reveal = enterPreset === 'typewriter' || enterPreset === 'letters' || enterPreset === 'words'
  const letters = reveal ? revealCount(text, elapsed, enterDuration, enterPreset === 'words') : Array.from(text).length
  return {
    elapsed,
    opacity: (enter.opacity ?? 1) * (exit.opacity ?? 1) * (loop.opacity ?? 1),
    scale: (enter.scale ?? 1) * (exit.scale ?? 1) * (loop.scale ?? 1),
    dy: (enter.dy ?? 0) + (exit.dy ?? 0) + (loop.dy ?? 0),
    dx: (enter.dx ?? 0) + (exit.dx ?? 0) + (loop.dx ?? 0),
    letters, blur: (enter.blur ?? 0) + (exit.blur ?? 0),
    clip: (enter.clip ?? 1) * (exit.clip ?? 1),
    wave: (cue.loop ?? derived.loop) === 'wave',
  }
}

/** Pure time sampling. Seeking backwards never depends on the last painted frame. */
export function kineticTextState(cue: KineticText, seconds: number): TextMotion | ReturnType<typeof legacyTextState> | null {
  if (seconds < cue.start || seconds >= cue.end) return null
  if (isLegacyKineticText(cue)) return legacyTextState(cue, seconds)
  return v2State(cue, seconds, displayedKineticText(cue, seconds))
}
