import type { AudioAnalysisResult, SceneKeyframe, SceneLayer } from '../types'
import {
  evaluateSceneLayer,
  getSceneEvents,
  getSceneKeyframes,
  layerTimeToSceneTime,
  sceneTimeToLayerTime,
} from './sceneTimeline'

export type SceneRhythmCueSource = 'beats' | 'downbeats'
export type SceneRhythmProfile = 'pulse' | 'bounce' | 'peek' | 'camera-punch'

export interface SceneRhythmCue {
  /** Time on the scene timeline after applying the audio track offset. */
  time: number
  /** Time in the analyzed audio file. */
  sourceTime: number
  strength: number
  downbeat: boolean
}
export interface SceneRhythmMap {
  bpm: number
  sourceDuration: number
  trackStartTime: number
  cueSource: SceneRhythmCueSource
  cues: SceneRhythmCue[]
}

export interface ApplySceneRhythmOptions {
  profile: SceneRhythmProfile
  sceneDuration: number
  /** Normalized author control. Zero is deliberately still visible. */
  intensity?: number
  /** Avoid pathological timelines for long/high-BPM tracks. */
  maxCues?: number
}

const bounded = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const finite = (value: unknown, fallback = 0) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const roundedTime = (value: number) => Math.round(value * 1_000_000) / 1_000_000

const downbeatTolerance = (analysis: AudioAnalysisResult) => {
  const beatSeconds = analysis.bpm > 0 ? 60 / analysis.bpm : .5
  return Math.max(.025, Math.min(.12, beatSeconds * .22))
}

const isDownbeat = (time: number, analysis: AudioAnalysisResult) => {
  const tolerance = downbeatTolerance(analysis)
  return analysis.downbeats.some(candidate => Math.abs(candidate - time) <= tolerance)
}

const limitCues = (cues: SceneRhythmCue[], maxCues: number) => {
  if (cues.length <= maxCues) return cues
  const stride = cues.length / maxCues
  return Array.from({ length: maxCues }, (_, index) => cues[Math.min(cues.length - 1, Math.floor(index * stride))])
}

/** Convert the existing analyzer response into scene-relative rhythmic cues. */
export const buildSceneRhythmMap = (
  analysis: AudioAnalysisResult,
  trackStartTime: number,
  sceneDuration: number,
  cueSource: SceneRhythmCueSource = 'beats',
  maxCues = 160,
): SceneRhythmMap => {
  const safeStart = Math.max(0, finite(trackStartTime))
  const safeDuration = Math.max(.1, finite(sceneDuration, .1))
  const raw = cueSource === 'downbeats'
    ? analysis.downbeats.map(time => {
      const nearest = analysis.beats.reduce((best, beat) => Math.abs(beat.time - time) < Math.abs(best.time - time) ? beat : best, analysis.beats[0] ?? { time, strength: 1 })
      return { time, strength: nearest.strength }
    })
    : analysis.beats
  const seen = new Set<number>()
  const cues = raw.flatMap(beat => {
    const sourceTime = finite(beat.time, -1)
    const time = roundedTime(safeStart + sourceTime)
    if (sourceTime < 0 || time < 0 || time > safeDuration || seen.has(time)) return []
    seen.add(time)
    return [{
      time,
      sourceTime,
      strength: bounded(finite(beat.strength, .5), 0, 1),
      downbeat: cueSource === 'downbeats' || isDownbeat(sourceTime, analysis),
    }]
  }).sort((left, right) => left.time - right.time)

  return {
    bpm: Math.max(0, finite(analysis.bpm)),
    sourceDuration: Math.max(0, finite(analysis.duration)),
    trackStartTime: safeStart,
    cueSource,
    cues: limitCues(cues, Math.max(1, Math.floor(maxCues))),
  }
}

const framePoint = (layer: SceneLayer, sceneTime: number) => {
  const point = evaluateSceneLayer(layer, sceneTimeToLayerTime(layer, sceneTime))
  return { x: point.x, y: point.y, scale: point.scale, opacity: point.opacity, rotation: point.rotation }
}

const rhythmFrame = (
  layer: SceneLayer,
  sceneTime: number,
  suffix: string,
  mutate: (point: ReturnType<typeof framePoint>) => ReturnType<typeof framePoint>,
  curve: SceneKeyframe['curve'] = 'ease',
): SceneKeyframe => ({
  id: `rhythm-${suffix}-${roundedTime(sceneTime)}`,
  time: roundedTime(sceneTime),
  ...mutate(framePoint(layer, sceneTime)),
  curve,
})

const addFrame = (frames: Map<number, SceneKeyframe>, frame: SceneKeyframe) => {
  frames.set(roundedTime(frame.time), frame)
}

const restFrame = (layer: SceneLayer, time: number, suffix: string) => rhythmFrame(layer, time, suffix, point => point)

/**
 * Bake the layer's current motion plus beat reactions into ordinary editable
 * keyframes. Preview, capture and exported scene JSON therefore share exactly
 * the same deterministic animation path.
 */
export const applySceneRhythmToLayer = (
  layer: SceneLayer,
  rhythm: SceneRhythmMap,
  options: ApplySceneRhythmOptions,
): SceneLayer => {
  const duration = Math.max(.1, finite(options.sceneDuration, .1))
  const intensity = bounded(finite(options.intensity, .65), 0, 1)
  const maxCues = Math.max(1, Math.floor(options.maxCues ?? 160))
  const cues = limitCues(rhythm.cues.filter(cue => cue.time >= 0 && cue.time <= duration), maxCues)
  if (!cues.length) throw new Error('No rhythmic cues overlap this scene.')

  const frames = new Map<number, SceneKeyframe>()
  if (options.profile !== 'peek') {
    for (const frame of getSceneKeyframes(layer)) {
      const sceneTime = roundedTime(layerTimeToSceneTime(layer, frame.time))
      if (sceneTime >= 0 && sceneTime <= duration) {
        addFrame(frames, { ...frame, id: `rhythm-base-${frame.id}`, time: sceneTime })
      }
    }
    addFrame(frames, restFrame(layer, 0, 'scene-start'))
    addFrame(frames, restFrame(layer, duration, 'scene-end'))
  }

  cues.forEach((cue, index) => {
    const previousGap = index > 0 ? cue.time - cues[index - 1].time : .5
    const nextGap = index + 1 < cues.length ? cues[index + 1].time - cue.time : .5
    const attack = Math.max(.025, Math.min(.1, previousGap * .28, cue.time))
    const release = Math.max(.04, Math.min(.2, nextGap * .36, duration - cue.time))
    const accent = (cue.downbeat ? 1.28 : 1) * (.35 + cue.strength * .65)
    const attackTime = Math.max(0, cue.time - attack)
    const releaseTime = Math.min(duration, cue.time + release)

    if (options.profile === 'peek') {
      const hide = (point: ReturnType<typeof framePoint>) => {
        const direction = point.x <= 50 ? -1 : 1
        return { ...point, x: point.x + direction * (8 + intensity * 18), opacity: 0 }
      }
      addFrame(frames, rhythmFrame(layer, attackTime, `peek-hidden-${index}`, hide, 'hold'))
      addFrame(frames, rhythmFrame(layer, cue.time, `peek-visible-${index}`, point => ({
        ...point,
        scale: point.scale * (1 + intensity * accent * .08),
      }), 'dramatic'))
      addFrame(frames, rhythmFrame(layer, releaseTime, `peek-release-${index}`, hide, 'ease'))
      return
    }

    addFrame(frames, restFrame(layer, attackTime, `attack-${index}`))
    addFrame(frames, rhythmFrame(layer, cue.time, `peak-${index}`, point => {
      if (options.profile === 'bounce') {
        return {
          ...point,
          y: point.y - intensity * accent * 7,
          scale: point.scale * (1 + intensity * accent * .1),
        }
      }
      const scaleGain = options.profile === 'camera-punch' ? .09 : .2
      return { ...point, scale: point.scale * (1 + intensity * accent * scaleGain) }
    }, options.profile === 'bounce' ? 'bounce' : 'dramatic'))
    addFrame(frames, restFrame(layer, releaseTime, `release-${index}`))
  })

  if (options.profile === 'peek') {
    const hide = (point: ReturnType<typeof framePoint>) => {
      const direction = point.x <= 50 ? -1 : 1
      return { ...point, x: point.x + direction * (8 + intensity * 18), opacity: 0 }
    }
    addFrame(frames, rhythmFrame(layer, 0, 'peek-scene-start', hide, 'hold'))
    addFrame(frames, rhythmFrame(layer, duration, 'peek-scene-end', hide, 'hold'))
  }

  const keyframes = [...frames.values()].sort((left, right) => left.time - right.time)
  const first = keyframes[0]
  const last = keyframes[keyframes.length - 1]
  const mappedEvents = getSceneEvents(layer).map(event => ({
    ...event,
    time: bounded(layerTimeToSceneTime(layer, event.time), 0, duration),
  }))
  return {
    ...layer,
    transform: {
      ...layer.transform,
      x: first.x,
      y: first.y,
      scale: first.scale,
      opacity: first.opacity,
      rotation: first.rotation,
    },
    animation: {
      ...layer.animation,
      start: { x: first.x, y: first.y, scale: first.scale, opacity: first.opacity, rotation: first.rotation },
      end: { x: last.x, y: last.y, scale: last.scale, opacity: last.opacity, rotation: last.rotation },
      keyframes,
      events: mappedEvents,
      duration,
      curve: first.curve,
      offset: 0,
      speed: 1,
      loop: false,
      trimStart: 0,
      trimEnd: duration,
    },
  }
}
