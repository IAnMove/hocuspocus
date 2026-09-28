// Video 2D scene documents for the four unapproved candidates. They use effect
// layers so an export does not depend on a missing example file.
import { buildTextTemplate } from '../../lib/kineticText'
import type { Scene } from '../../types'
import { FINISH_PRESETS } from '../../lib/scene2d/finish'

export type Video2dCandidateSize = { width?: number; height?: number; duration?: number; fps?: number }

function candidateFrame(id: string, size: Video2dCandidateSize) {
  const vertical = id === 'lyric-vertical'
  let width = vertical ? 1080 : 1920
  let height = vertical ? 1920 : 1080
  let duration = 6
  if (typeof size.width === 'number') width = size.width
  if (typeof size.height === 'number') height = size.height
  if (typeof size.duration === 'number') duration = size.duration
  return { start: 0, duration, width, height }
}

function candidateFps(id: string, fps: number | undefined): 24 | 30 | 60 {
  if (fps === 24 || fps === 30 || fps === 60) return fps
  return id === 'lyric-vertical' ? 30 : 24
}

/** Duration 6 keeps the authored cue times; other durations scale that timeline. */
function scaled(value: number, duration: number) {
  if (duration === 6) return value
  return value * duration / 6
}

const layer = (id: string, kind: 'dust' | 'smoke' | 'bokeh' | 'leaves', duration: number) => ({
  id, name: id, type: 'effect' as const, source: '', visible: true, z: 0,
  transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
  animation: { start: { x: 50, y: 50, scale: 1, opacity: 1 }, end: { x: 50, y: 50, scale: 1.04, opacity: 1 }, duration, curve: 'ease' as const },
  atmosphere: { kind, density: 24, speed: 0.4, size: 1.2, wind: 4, color: '#dbe7f5' },
})

export function compileVideo2dCandidate(id: string, size: Video2dCandidateSize = {}): Scene | undefined {
  const frame = candidateFrame(id, size)
  const fps = candidateFps(id, size.fps)
  if (id === 'documentary-history') return {
    version: 1, name: 'Documentary', width: frame.width, height: frame.height, fps, duration: frame.duration,
    layers: [layer('plate', 'dust', frame.duration)],
    texts: [...buildTextTemplate('lower-third-date', { date: '1968', caption: 'The harbour keeps the light' }, frame), ...buildTextTemplate('year-counter', { from: '1960', to: '1968', label: 'Year' }, frame)],
    finish: FINISH_PRESETS.oldDoc,
  }
  if (id === 'trailer-teaser') return {
    version: 1, name: 'Trailer', width: frame.width, height: frame.height, fps, duration: frame.duration,
    layers: [layer('black', 'smoke', frame.duration)],
    texts: [...buildTextTemplate('trailer-slam', { lines: 'ONE|LAST|LIGHT' }, frame), ...buildTextTemplate('title-card', { title: 'Musktopia', subtitle: 'A harbour story' }, { ...frame, start: scaled(4.2, frame.duration), duration: scaled(0.8, frame.duration) }), ...buildTextTemplate('end-card', { title: 'Coming soon', cta: '@studio' }, { ...frame, start: scaled(5.1, frame.duration), duration: scaled(0.9, frame.duration) })],
    finish: { ...FINISH_PRESETS.warmCinema, bloom: { amount: 0.4, threshold: 0.6, radius: 0.4 }, letterbox: { ratio: 2.39, color: '#000000' } },
  }
  if (id === 'lyric-vertical') return {
    version: 1, name: 'Lyric', width: frame.width, height: frame.height, fps, duration: frame.duration,
    layers: [layer('glow', 'bokeh', frame.duration)],
    lyrics: { mode: 'karaoke', lines: [{ id: 'line', start: scaled(0.2, frame.duration), end: scaled(5.5, frame.duration), words: [{ text: 'The', start: scaled(0.2, frame.duration), end: scaled(0.8, frame.duration) }, { text: 'bird', start: scaled(0.8, frame.duration), end: scaled(1.6, frame.duration) }, { text: 'is', start: scaled(1.6, frame.duration), end: scaled(2, frame.duration) }, { text: 'freed', start: scaled(2, frame.duration), end: scaled(3.4, frame.duration) }] }], style: { font: 'sans', size: 6, color: '#f4efe6', activeColor: '#9ae7ff', x: 50, y: 70, maxWidth: 76, align: 'center', visibleLines: 2, beatPulse: 0.35 }, source: { kind: 'manual' } },
    finish: FINISH_PRESETS.nightNeon,
    rhythm: { bpm: 96, beats: [0.4, 1.0, 1.6, 2.2, 2.8, 3.4].map(beat => scaled(beat, frame.duration)) },
  }
  if (id === 'city-postcard') return {
    version: 1, name: 'Postcard', width: frame.width, height: frame.height, fps, duration: frame.duration,
    layers: [{ ...layer('sky', 'leaves', frame.duration), strip: { enabled: true, count: 3, spacing: 30, direction: 'left' as const, speed: 6 }, animation: { start: { x: 20, y: 60, scale: 1, opacity: 1 }, end: { x: 80, y: 40, scale: 1, opacity: 1 }, duration: frame.duration, curve: 'ease' as const, path: { points: [{ x: 15, y: 70 }, { x: 40, y: 42 }, { x: 78, y: 58 }], orient: true } } }],
    texts: buildTextTemplate('chorus-banner', { line: 'Salt on the windows' }, frame),
    finish: { ...FINISH_PRESETS.paperComic, rays: { amount: 0.25, x: 70, y: 20, length: 0.4, threshold: 0.7 } },
  }
  return undefined
}

export const VIDEO2D_CANDIDATE_IDS = ['documentary-history', 'trailer-teaser', 'lyric-vertical', 'city-postcard'] as const
