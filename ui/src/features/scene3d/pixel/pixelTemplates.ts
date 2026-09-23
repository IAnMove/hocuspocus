import { createDefaultScene3DDocument } from '../document'
import { defaultMediaScreen } from '../mediaScreen'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from '../types'
import { fxRandom } from '../../sceneFx/types'
import { defaultPixelWorld, type PixelWorld } from './pixelWorld'
import { isPixelTemplate, PIXEL_TEMPLATE_IDS } from './pixelTemplateIds'
import type { Scene3DTemplate } from '../templates'

/** The recording every TV starts with; replace it on one TV or all of them. */
export const PIXEL_TV_CLIP = '/examples/moving-cutouts/skate-neon.mp4'

export const PIXEL_TEMPLATES: Scene3DTemplate[] = PIXEL_TEMPLATE_IDS.map(id => ({
  id, camera: 'establishment', duration: id === 'pixel-tv-wall' ? 10 : 24,
  // Landscapes start empty: a placeholder actor would stand in the lake.
  slots: id === 'pixel-moon-lake' || id === 'pixel-aurora-peaks' ? [] : ['prop'],
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
  const peaks = id === 'pixel-aurora-peaks'
  const doc = pixelDocument(id, peaks ? 'pixel-peaks' : 'pixel-lake', peaks
    ? { palettes: ['aurora', 'polar', 'midnight'], hold: 7, meteors: .3 }
    : { palettes: ['midnight', 'aurora', 'dawn', 'sunset'], hold: 6, meteors: .6 }, 24)
  doc.camera = { family: 'establishment', eye: [0, 1.6, 8], look: [0, 3.2, -40], fov: 45 }
  return doc
}
