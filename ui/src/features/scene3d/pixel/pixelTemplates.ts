import { createDefaultScene3DDocument } from '../document'
import { defaultMediaScreen } from '../mediaScreen'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from '../types'
import { fxRandom } from '../../sceneFx/types'
import { defaultPixelWorld, type PixelWorld } from './pixelWorld'
import { isPixelTemplate, PIXEL_TEMPLATE_IDS } from './pixelTemplateIds'
import type { Scene3DTemplate } from '../templates'
import { parseWorldSfx } from '../../sceneFx/world'
import { LAUNCH, VILLAGE, VOLCANO_CENTER } from './pixelWorlds'
import { paintVillage } from './pixelPaintWorlds'
import { INDEX } from './pixelPaint'
import { PIXEL_SCENE_DEFAULTS } from './pixelScene'

/** The recording every TV starts with; replace it on one TV or all of them. */
export const PIXEL_TV_CLIP = '/examples/moving-cutouts/skate-neon.mp4'

export const PIXEL_TEMPLATES: Scene3DTemplate[] = PIXEL_TEMPLATE_IDS.map(id => ({
  id, camera: 'establishment', duration: id === 'pixel-tv-wall' ? 10 : 24,
  // Landscapes start empty: a placeholder actor would stand in the lake.
  slots: id === 'pixel-tv-wall' || id === 'pixel-tv-lake' || id === 'pixel-drive-in' ? ['prop'] : [],
  tags: ['pixel', 'animated'],
}))
export const PIXEL_CATEGORIES = Object.fromEntries(PIXEL_TEMPLATE_IDS.map(id => [id, 'cinema'])) as Record<typeof PIXEL_TEMPLATE_IDS[number], 'cinema'>

/** A CRT television standing at `position`, facing `rotationY`. */
export function crtSlot(id: string, position: Vec3, rotationY: number, width: number, hue = 0, sourceUrl = PIXEL_TV_CLIP): Scene3DSlot {
  return {
    id, slot: 'prop', media: 'screen', position, rotationY, scale: 1, sourceUrl: '', clip: null,
    screen: { ...defaultMediaScreen(), sourceUrl, media: 'video', style: 'crt', fit: 'cover', width, height: width * .75, ...(hue ? { hue } : {}) },
  }
}

/** Front height of a CRT built by `screenGeometry`, to stack one on another. */
function crtHeight(width: number) {
  const height = width * .75
  return height + Math.min(width, height) * .22 + height * .2
}

/** Columns of TVs of mixed sizes along a wall, stacked three to four high. */
function bank(prefix: string, from: [number, number], to: [number, number], columns: number, seed: number): Scene3DSlot[] {
  const slots: Scene3DSlot[] = []
  const angle = Math.atan2(to[1] - from[1], to[0] - from[0])
  for (let c = 0; c < columns; c++) {
    const t = (c + .5) / columns
    const x = from[0] + (to[0] - from[0]) * t, z = from[1] + (to[1] - from[1]) * t
    let y = 0
    const rows = 3 + (fxRandom(seed, c) > .45 ? 1 : 0)
    for (let r = 0; r < rows; r++) {
      const width = r === 0 ? 1.05 + fxRandom(seed, c * 9 + r) * .25 : .75 + fxRandom(seed, c * 9 + r) * .4
      // Most sets agree; a few drift to other colours, like real old tubes.
      const hue = fxRandom(seed, c * 9 + r + 400) > .7 ? Math.round((fxRandom(seed, c * 9 + r + 500) - .5) * 220) : 0
      slots.push(crtSlot(`${prefix}-${c}-${r}`, [x, y, z], -angle, width, hue))
      y += crtHeight(width) + .01
    }
  }
  return slots
}

function pixelDocument(id: string, dressing: Scene3DDocument['dressing'], pixel: Partial<PixelWorld>, duration: number): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  doc.templateId = id as Scene3DDocument['templateId']
  doc.dressing = dressing
  doc.duration = duration
  doc.pixelWorld = { ...defaultPixelWorld(), ...pixel }
  doc.environment = { reflectiveFloor: false, platform: false, bloom: .55 }
  doc.slots = []
  return doc
}

/** Smoke and embers rising from the crater, which stands on the far plane
 *  at 60% of its height (see the volcano world). */
function eruptionCues() {
  const crater = { x: (VOLCANO_CENTER - .5) * 130, y: 16.2, z: -45 }
  return parseWorldSfx([
    { id: 'volcano-smoke', kind: 'smoke', start: 0, end: 24, position: crater, scale: 6, intensity: 1.4, color: '#8a7a84', seed: 3, sound: false, volume: 0 },
    { id: 'volcano-embers', kind: 'sparks', start: 0, end: 24, position: crater, scale: 3.2, intensity: 1.2, color: '#ff8a3a', seed: 9, sound: true, volume: .18 },
  ])
}

/** Snowfall, and smoke from the village's real chimneys: the painter
 *  reports where it drew them and they are mapped into the world here. */
function villageCues() {
  const [w, h] = VILLAGE.texture
  const scene = PIXEL_SCENE_DEFAULTS['pixel-village']
  const { chimneys } = paintVillage(w, h, { body: INDEX.near, rim: INDEX.nearRim, lightFrom: .2 + .6 * scene.bodyX, seed: scene.seed + 6, houses: 9 })
  const smoke = chimneys.filter((_, i) => i % 3 === 0).slice(0, 4).map(([x, y], i) => ({
    id: `chimney-${i + 1}`, kind: 'smoke', start: 0, end: 24, scale: .9, intensity: .8, color: '#c8d4e4', seed: 30 + i, sound: false, volume: 0,
    position: { x: (x / w - .5) * VILLAGE.width, y: VILLAGE.bottom + (1 - y / h) * VILLAGE.height, z: VILLAGE.z + .2 },
  }))
  return parseWorldSfx([
    { id: 'snowfall', kind: 'snow', start: 0, end: 24, position: { x: 0, y: -.5, z: 1 }, scale: 3.6, intensity: 1, color: '#f4f8ff', seed: 12, sound: true, volume: .14 },
    ...smoke,
  ])
}

/** Ignition: a shockwave and a boiling cloud of smoke and sparks at the pad,
 *  with the rumble and crackle of the engines. */
function launchCues() {
  const pad = { x: LAUNCH.x * (30 / 39), y: 0, z: -29 }
  return parseWorldSfx([
    { id: 'ignition', kind: 'shockwave', start: LAUNCH.at - 1.2, end: LAUNCH.at + 2, position: pad, scale: 6, intensity: 1.2, color: '#ffd8a0', seed: 7, sound: true, volume: .45 },
    { id: 'plume', kind: 'smoke', start: LAUNCH.at - 1, end: 20, position: pad, scale: 9, intensity: 1.5, color: '#d8d0c8', seed: 11, sound: true, volume: .35 },
    { id: 'sparks', kind: 'sparks', start: LAUNCH.at - 1, end: LAUNCH.at + 5, position: pad, scale: 3, intensity: 1.4, color: '#ffc070', seed: 13, sound: true, volume: .25 },
  ])
}

/** Rain around the camera and single strikes on the far ranges, each with
 *  its thunder; the painted world flashes with every strike. */
function stormCues() {
  const strikes: [number, number, number][] = [[1.4, -14, 11], [4.9, 9, 23], [8.2, -4, 37], [11.6, 17, 41], [14.8, -22, 53]]
  return parseWorldSfx([
    { id: 'storm-rain', kind: 'rain', start: 0, end: 18, position: { x: 0, y: -1, z: 3 }, scale: 4.2, intensity: 1, color: '#9fb4d8', seed: 7, sound: true, volume: .35 },
    ...strikes.map(([at, x, seed], i) => ({
      id: `storm-bolt-${i + 1}`, kind: 'lightning', start: at, end: at + 1.1, seed, sound: true, volume: .55, intensity: 1.4, scale: 3.2, color: '#d8e4ff',
      position: { x, y: 24, z: -44 }, targetPosition: { x: x + 3, y: 2, z: -40 },
    })),
  ])
}

/** Landscapes: a painted world and the moods its light moves through. */
const LANDSCAPES: Record<Exclude<typeof PIXEL_TEMPLATE_IDS[number], 'pixel-tv-wall' | 'pixel-tv-lake'>, [Scene3DDocument['dressing'], Partial<PixelWorld>]> = {
  'pixel-moon-lake': ['pixel-lake', { palettes: ['midnight', 'aurora', 'dawn', 'sunset'], hold: 6, meteors: .6 }],
  'pixel-aurora-peaks': ['pixel-peaks', { palettes: ['aurora', 'polar', 'midnight'], hold: 7, meteors: .3 }],
  'pixel-neon-city': ['pixel-city', { palettes: ['harbor', 'vapor', 'eclipse'], hold: 6, meteors: .3 }],
  'pixel-desert-sun': ['pixel-desert', { palettes: ['dusk', 'sunset', 'midnight'], hold: 7, meteors: .4 }],
  'pixel-lighthouse': ['pixel-coast', { palettes: ['storm', 'midnight', 'dawn'], hold: 6, meteors: .3 }],
  'pixel-firefly-forest': ['pixel-forest', { palettes: ['forest', 'midnight', 'aurora'], hold: 7, meteors: .4 }],
  // Four moods of 6 s each: dawn at sunrise, day at noon, sunset, night under the moon.
  // A year in 24 s: moods follow the seasons in step with the foliage and snow.
  'pixel-fjord': ['pixel-fjord', { palettes: ['aurora', 'polar'], hold: 12, meteors: .4 }],
  'pixel-cloud-shadows': ['pixel-meadow', { palettes: ['jungle', 'sunset'], hold: 12, meteors: 0 }],
  'pixel-mirage': ['pixel-mirage', { palettes: ['noon', 'sunset'], hold: 12, meteors: 0 }],
  'pixel-tidal-abbey': ['pixel-tidal', { palettes: ['sunset', 'midnight'], hold: 12, meteors: .3 }],
  'pixel-roadside-motel': ['pixel-motel', { palettes: ['midnight', 'dusk'], hold: 12, meteors: .5, screenGlow: 0 }],
  'pixel-mist-rising': ['pixel-dawnmist', { palettes: ['dawn', 'jungle'], hold: 10, meteors: 0 }],
  'pixel-starry-night': ['pixel-starry', { palettes: ['starry'], hold: 20, meteors: 0 }],
  'pixel-crystal-cave': ['pixel-grotto', { palettes: ['grotto'], hold: 20, meteors: 0 }],
  'pixel-night-launch': ['pixel-launch', { palettes: ['midnight', 'dawn'], hold: 12, meteors: .3 }],
  'pixel-murmuration': ['pixel-marsh', { palettes: ['sunset', 'dusk'], hold: 12, meteors: 0 }],
  'pixel-monsoon': ['pixel-monsoon', { palettes: ['storm', 'jungle'], hold: 12, meteors: 0 }],
  'pixel-synthwave': ['pixel-synthwave', { palettes: ['vapor', 'neon'], hold: 10, meteors: .4 }],
  'pixel-moon-caravan': ['pixel-caravan', { palettes: ['dusk', 'midnight'], hold: 12, meteors: .4 }],
  'pixel-koi-pond': ['pixel-koi', { palettes: ['jungle', 'midnight'], hold: 12, meteors: 0 }],
  'pixel-cathedral': ['pixel-cathedral', { palettes: ['nave'], hold: 20, meteors: 0 }],
  'pixel-four-seasons': ['pixel-seasons', { palettes: ['dawn', 'jungle', 'sunset', 'polar'], hold: 6, meteors: 0 }],
  'pixel-eclipse': ['pixel-eclipse', { palettes: ['noon'], hold: 20, meteors: 0 }],
  'pixel-whole-day': ['pixel-daycycle', { palettes: ['dawn', 'jungle', 'sunset', 'midnight'], hold: 6, meteors: .3 }],
  'pixel-night-express': ['pixel-express', { palettes: ['dusk', 'midnight', 'aurora'], hold: 9, meteors: .5 }],
  'pixel-rainy-window': ['pixel-window', { palettes: ['harbor', 'storm'], hold: 12, meteors: 0 }],
  'pixel-lantern-festival': ['pixel-lanterns', { palettes: ['dusk', 'midnight'], hold: 12, meteors: 0 }],
  'pixel-glow-tide': ['pixel-beach', { palettes: ['midnight', 'harbor'], hold: 12, meteors: .5 }],
  'pixel-castle-fireworks': ['pixel-castle', { palettes: ['midnight', 'harbor'], hold: 10, meteors: 0 }],
  'pixel-neon-alley': ['pixel-alley', { palettes: ['neon', 'vapor'], hold: 10, meteors: 0 }],
  'pixel-tulip-fields': ['pixel-tulips', { palettes: ['sunset', 'dusk', 'dawn'], hold: 8, meteors: .2 }],
  'pixel-orbit': ['pixel-orbit', { palettes: ['cosmos', 'vapor'], hold: 10, meteors: .15 }],
  'pixel-waterfall': ['pixel-falls', { palettes: ['jungle', 'dusk', 'forest'], hold: 8, meteors: .2 }],
  'pixel-snow-village': ['pixel-village', { palettes: ['polar', 'midnight'], hold: 10, meteors: .3 }],
  'pixel-night-fair': ['pixel-fair', { palettes: ['harbor', 'vapor'], hold: 10, meteors: .3 }],
  'pixel-balloons': ['pixel-valley', { palettes: ['dawn', 'sunset'], hold: 10, meteors: 0 }],
  'pixel-coral-reef': ['pixel-reef', { palettes: ['lagoon', 'abyss'], hold: 9, meteors: 0 }],
  'pixel-cherry-garden': ['pixel-garden', { palettes: ['sakura', 'midnight'], hold: 10, meteors: .2 }],
  'pixel-drive-in': ['pixel-drivein', { palettes: ['midnight', 'vapor'], hold: 10, meteors: .5, screenGlow: 1.6 }],
  'pixel-volcano': ['pixel-volcano', { palettes: ['eclipse', 'dusk'], hold: 9, meteors: .3 }],
  'pixel-storm-lake': ['pixel-lake', { palettes: ['storm'], hold: 20, meteors: 0,
    scene: { body: 'none', stars: 0, mountains: .62, roughness: .6, trees: .9, ripple: 1, reeds: true } }],
  'pixel-night-train': ['pixel-viaduct', { palettes: ['midnight', 'dawn'], hold: 9, meteors: .4 }],
  'pixel-planet-rise': ['pixel-peaks', { palettes: ['alien', 'vapor'], hold: 8, meteors: .5,
    scene: { body: 'planet', bodyX: .62, bodyY: .5, bodySize: 2.1, crescent: .35, mountains: .55, roughness: .95, snow: 0, hills: .4, stars: .8, reeds: false, ripple: .35 } }],
}

type Landscape = keyof typeof LANDSCAPES
const DURATIONS: Partial<Record<Landscape, number>> = { 'pixel-storm-lake': 18, 'pixel-eclipse': 20 }

/** Shots that differ from the standard landscape view. */
const SHOTS: Partial<Record<Landscape, Scene3DDocument['camera']>> = {
  'pixel-drive-in': { family: 'establishment', eye: [0, 1.5, 6.5], look: [0, 3.2, -14], fov: 46 },
  // The storm low and wide over the water, the planet looked up to.
  'pixel-storm-lake': { family: 'establishment', eye: [0, 1.2, 9], look: [0, 3.6, -40], fov: 50 },
  'pixel-planet-rise': { family: 'establishment', eye: [0, 1.8, 8], look: [0, 5, -40], fov: 44 },
  // A long lens: the moon looms and the caravan fills its disc.
  'pixel-moon-caravan': { family: 'fixed', eye: [0, 1.4, 9], look: [0, 2.5, -40], fov: 20 },
  // The camera glides round a point down the fjord: the walls slide by faster
  // than the far peaks, showing the world's depth.
  'pixel-fjord': { family: 'orbit', eye: [0, 1.6, 8], look: [0, 4, -16], fov: 52, orbitRadius: 24, orbitHeight: -2.4, orbitTurns: .07 },
  'pixel-cloud-shadows': { family: 'fixed', eye: [0, 5, 14], look: [0, 3, -40], fov: 50 },
  'pixel-mirage': { family: 'fixed', eye: [0, 1.3, 9], look: [0, 1.6, -40], fov: 50 },
  'pixel-tidal-abbey': { family: 'fixed', eye: [0, 1.6, 9], look: [0, 2.6, -30], fov: 46 },
  'pixel-roadside-motel': { family: 'fixed', eye: [-2.5, 1.4, 0], look: [-4, 3.4, -16], fov: 52 },
  'pixel-mist-rising': { family: 'establishment', eye: [0, 2.2, 9], look: [0, 3.6, -40], fov: 46 },
  'pixel-starry-night': { family: 'fixed', eye: [0, 2, 9], look: [0, 5.5, -40], fov: 50 },
  'pixel-crystal-cave': { family: 'fixed', eye: [0, 1.4, 9], look: [0, 2.2, -30], fov: 55 },
  'pixel-night-launch': { family: 'fixed', eye: [0, 1.5, 9], look: [3, 7.5, -30], fov: 38 },
  'pixel-murmuration': { family: 'establishment', eye: [0, 1.3, 9], look: [0, 4.5, -40], fov: 50 },
  'pixel-monsoon': { family: 'establishment', eye: [0, 1.1, 9], look: [0, 1.8, -40], fov: 50 },
  'pixel-synthwave': { family: 'fixed', eye: [0, 2.2, 9], look: [0, 3, -40], fov: 52 },
  // Looking down on the pond from above.
  'pixel-koi-pond': { family: 'fixed', eye: [0, 13.5, 3.2], look: [0, 0, 0], fov: 50 },
  'pixel-cathedral': { family: 'establishment', eye: [0, 1.7, 8], look: [0, 6, -20], fov: 56 },
  'pixel-night-express': { family: 'fixed', eye: [0, 1.75, 8.4], look: [0, 2.1, -40], fov: 50 },
  'pixel-rainy-window': { family: 'fixed', eye: [0, 1.7, 8.4], look: [0, 1.95, -40], fov: 50 },
  'pixel-glow-tide': { family: 'establishment', eye: [0, 1.5, 10.5], look: [0, 2.2, -40], fov: 48 },
  'pixel-neon-alley': { family: 'establishment', eye: [0, 1.7, 8], look: [0, 3.4, -30], fov: 56 },
  // Underwater the camera sits low and looks up into the light.
  'pixel-coral-reef': { family: 'establishment', eye: [0, .9, 8], look: [0, 6, -40], fov: 50 },
}

/** A drift of the 3D snow effect, recoloured: petals, leaves, motes or snow. */
const drift = (id: string, color: string, intensity: number, extra: Record<string, unknown> = {}) =>
  ({ id, kind: 'snow', start: 0, end: 24, position: { x: 0, y: -.5, z: 1 }, scale: 3.4, intensity, color, seed: 5, sound: false, volume: 0, ...extra })
const rain = (id: string, color: string, z: number, seed: number) =>
  ({ id, kind: 'rain', start: 0, end: 24, position: { x: 0, y: -1, z }, scale: 3.4, intensity: 1, color, seed, sound: true, volume: .3 })

/** Effects each landscape plays over its world. */
const CUES: Partial<Record<Landscape, () => ReturnType<typeof parseWorldSfx>>> = {
  'pixel-storm-lake': stormCues,
  'pixel-night-launch': launchCues,
  // Warm heavy rain, and now and then lightning beyond the hills.
  'pixel-monsoon': () => parseWorldSfx([rain('monsoon-rain', '#b8c8d8', 2, 31), ...stormCues().filter(cue => cue.kind === 'lightning').slice(0, 2).map(cue => ({ ...cue, intensity: .9, start: cue.start + 5, end: cue.end + 5 }))]),
  'pixel-volcano': eruptionCues,
  'pixel-snow-village': villageCues,
  'pixel-koi-pond': () => parseWorldSfx([drift('petals', '#ffc2dc', .4, { position: { x: 0, y: 1, z: 0 }, seed: 71 })]),
  // Dust motes turning slowly in the light.
  'pixel-cathedral': () => parseWorldSfx([drift('motes', '#ffe0a0', .35, { position: { x: 0, y: 1, z: -6 }, scale: 2.4, seed: 61 })]),
  // Petals in spring, leaves in autumn, snow in winter.
  'pixel-four-seasons': () => parseWorldSfx(([['petals', 0, 6, '#ffc2dc', .7], ['leaves', 12, 18, '#e0702a', .8], ['snow', 18, 24, '#f4f8ff', 1]] as const)
    .map(([name, start, end, color, intensity], i) => drift(`season-${name}`, color, intensity, { start, end, seed: 40 + i, sound: name === 'snow', volume: .12 }))),
  'pixel-rainy-window': () => parseWorldSfx([rain('city-rain', '#a8b8e0', -2, 23)]),
  'pixel-neon-alley': () => parseWorldSfx([rain('alley-rain', '#b4a8e8', 2, 19)]),
  'pixel-cherry-garden': () => parseWorldSfx([drift('petals', '#ffc2dc', .7, { sound: true, volume: .12 })]),
}

export function pixelTemplateDocument(id: string): Scene3DDocument | null {
  if (!isPixelTemplate(id)) return null
  if (id === 'pixel-tv-wall') {
    const doc = pixelDocument(id, 'pixel-gallery', { palettes: ['storm', 'vapor'], hold: 5, meteors: 0, levels: 40, dither: .3, screenGlow: 1.4 }, 10)
    doc.slots = [...bank('tv-left', [-7.4, 1.2], [-1.1, -2.9], 6, 3), ...bank('tv-right', [-.6, -3], [6.8, -1.6], 7, 8)]
    doc.camera = { family: 'establishment', eye: [1, 1.9, 6.6], look: [-.2, 1.75, -2], fov: 48 }
    return doc
  }
  if (id === 'pixel-tv-lake') {
    const doc = pixelDocument(id, 'pixel-lake', { palettes: ['midnight', 'vapor', 'eclipse'], hold: 5, meteors: .4, screenGlow: 1.6 }, 24)
    doc.slots = [
      crtSlot('tv-1', [-3.2, 0, -3], .45, 1.3), crtSlot('tv-2', [-3.25, crtHeight(1.3), -3], .42, 1),
      crtSlot('tv-3', [-1.6, 0, -4.4], .2, 1.1, 40), crtSlot('tv-4', [2.2, 0, -3.6], -.35, 1.4),
      crtSlot('tv-5', [2.25, crtHeight(1.4), -3.6], -.38, .9, -60), crtSlot('tv-6', [3.9, 0, -2.2], -.6, 1),
    ]
    doc.camera = { family: 'establishment', eye: [0, 1.4, 6.5], look: [0, 1.6, -30], fov: 48 }
    return doc
  }
  const [dressing, pixel] = LANDSCAPES[id]
  const doc = pixelDocument(id, dressing, pixel, DURATIONS[id] ?? 24)
  const cues = CUES[id]?.()
  if (cues) doc.worldSfx = cues
  doc.camera = SHOTS[id] ?? { family: 'establishment', eye: [0, 1.6, 8], look: [0, 3.2, -40], fov: 45 }
  if (id === 'pixel-drive-in') {
    // The big screen plays your recording; its light washes over cars and sand.
    doc.slots = [{ id: 'drive-in-screen', slot: 'prop', media: 'screen', position: [0, 0, -14], rotationY: 0, scale: 1, sourceUrl: '', clip: null,
      screen: { ...defaultMediaScreen(), sourceUrl: PIXEL_TV_CLIP, media: 'video', style: 'billboard', fit: 'cover', width: 11, height: 6.2 } }]
  }
  return doc
}
