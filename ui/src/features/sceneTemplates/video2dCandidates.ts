// Video 2D scene documents for the four unapproved candidates. They use effect
// layers so an export does not depend on a missing example file.
import { buildTextTemplate } from '../../lib/kineticText'
import type { Scene } from '../../types'
import { FINISH_PRESETS } from '../../lib/scene2d/finish'

const layer = (id: string, kind: 'dust' | 'smoke' | 'bokeh' | 'leaves') => ({
  id, name: id, type: 'effect' as const, source: '', visible: true, z: 0,
  transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
  animation: { start: { x: 50, y: 50, scale: 1, opacity: 1 }, end: { x: 50, y: 50, scale: 1.04, opacity: 1 }, duration: 6, curve: 'ease' as const },
  atmosphere: { kind, density: 24, speed: 0.4, size: 1.2, wind: 4, color: '#dbe7f5' },
})

export function compileVideo2dCandidate(id: string): Scene | undefined {
  const frame = { start: 0, duration: 6, width: id === 'lyric-vertical' ? 1080 : 1920, height: id === 'lyric-vertical' ? 1920 : 1080 }
  if (id === 'documentary-history') return {
    version: 1, name: 'Documentary', width: frame.width, height: frame.height, fps: 24, duration: 6,
    layers: [layer('plate', 'dust')],
    texts: [...buildTextTemplate('lower-third-date', { date: '1968', caption: 'The harbour keeps the light' }, frame), ...buildTextTemplate('year-counter', { from: '1960', to: '1968', label: 'Year' }, frame)],
    finish: FINISH_PRESETS.oldDoc,
  }
  if (id === 'trailer-teaser') return {
    version: 1, name: 'Trailer', width: frame.width, height: frame.height, fps: 24, duration: 6,
    layers: [layer('black', 'smoke')],
    texts: [...buildTextTemplate('trailer-slam', { lines: 'ONE|LAST|LIGHT' }, frame), ...buildTextTemplate('title-card', { title: 'Musktopia', subtitle: 'A harbour story' }, { ...frame, start: 4.2, duration: 0.8 }), ...buildTextTemplate('end-card', { title: 'Coming soon', cta: '@studio' }, { ...frame, start: 5.1, duration: 0.9 })],
    finish: { ...FINISH_PRESETS.warmCinema, bloom: { amount: 0.4, threshold: 0.6, radius: 0.4 }, letterbox: { ratio: 2.39, color: '#000000' } },
  }
  if (id === 'lyric-vertical') return {
    version: 1, name: 'Lyric', width: frame.width, height: frame.height, fps: 30, duration: 6,
    layers: [layer('glow', 'bokeh')],
    lyrics: { mode: 'karaoke', lines: [{ id: 'line', start: 0.2, end: 5.5, words: [{ text: 'The', start: 0.2, end: 0.8 }, { text: 'bird', start: 0.8, end: 1.6 }, { text: 'is', start: 1.6, end: 2 }, { text: 'freed', start: 2, end: 3.4 }] }], style: { font: 'sans', size: 6, color: '#f4efe6', activeColor: '#9ae7ff', x: 50, y: 70, maxWidth: 76, align: 'center', visibleLines: 2, beatPulse: 0.35 }, source: { kind: 'manual' } },
    finish: FINISH_PRESETS.nightNeon,
    rhythm: { bpm: 96, beats: [0.4, 1.0, 1.6, 2.2, 2.8, 3.4] },
  }
  if (id === 'city-postcard') return {
    version: 1, name: 'Postcard', width: frame.width, height: frame.height, fps: 24, duration: 6,
    layers: [{ ...layer('sky', 'leaves'), strip: { enabled: true, count: 3, spacing: 30, direction: 'left' as const, speed: 6 }, animation: { start: { x: 20, y: 60, scale: 1, opacity: 1 }, end: { x: 80, y: 40, scale: 1, opacity: 1 }, duration: 6, curve: 'ease' as const, path: { points: [{ x: 15, y: 70 }, { x: 40, y: 42 }, { x: 78, y: 58 }], orient: true } } }],
    texts: buildTextTemplate('chorus-banner', { line: 'Salt on the windows' }, frame),
    finish: { ...FINISH_PRESETS.paperComic, rays: { amount: 0.25, x: 70, y: 20, length: 0.4, threshold: 0.7 } },
  }
  return undefined
}

export const VIDEO2D_CANDIDATE_IDS = ['documentary-history', 'trailer-teaser', 'lyric-vertical', 'city-postcard'] as const
