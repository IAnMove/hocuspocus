import type { ImageFade } from './imageFade.ts'
import type { Scene3DSlot, Vec3 } from './types.ts'

/** A printed twin sits this far in front of its clean picture (metres): enough to sort, too little to see. */
export const COMIC_PRINT_AHEAD = 0.003
/** The sticker's shadow lies on the panel, in front of the panel's printed twin. */
export const COMIC_SHADOW_AHEAD = 0.006
/** The desk is this far behind the page, and this many times its size (scene3d_comic_paper.DESK_SPAN). */
export const COMIC_DESK_BEHIND = 0.02
export const COMIC_DESK_SPAN = 2.4

export type ComicLive = { url: string; lines: number; fadeStart: number; fadeEnd: number }
export type ComicDressPanel = { print?: string; printCutout?: string; shadow?: string; live?: ComicLive }
type Window = { duration: number; moveStart: number; moveEnd: number }
export type ComicDressInput = {
  panels: readonly ComicDressPanel[]
  fromPanel: number
  toPanel: number
  pageScale: number
  fov: number
  deskUrl?: string
  exit: Window
  enter: Window
}

/** Exit: the leaving panel turns into print as the camera pulls away. Enter: the arriving panel turns back into
 * its picture (a playing clip when it has one) during the flight. The two documents agree at the wide pose. */
export function dressComicSlots(base: Scene3DSlot[], input: ComicDressInput): { exit: Scene3DSlot[]; enter: Scene3DSlot[] } {
  const desk = input.deskUrl ? [deskSlot(input.deskUrl, input.pageScale)] : []
  const pull = within(input.exit, 0.15, 0.65)
  const arrive = input.panels[input.toPanel]?.live
  const land = arrive ? { start: arrive.fadeStart, end: arrive.fadeEnd } : within(input.enter, 0.1, 0.5)
  // On newsprint the page keeps its mipmaps, like the other printed layers.
  const paged = input.deskUrl ? base.map(slot => slot.id === 'page' ? { ...slot, imageLook: { unlit: true } } : slot) : base
  const exit = [...desk, ...paged, ...twins(paged, input, input.fromPanel, { from: 0, to: 1, ...pull })]
  const enter = [...desk, ...live(paged, input), ...twins(paged, input, input.toPanel, { from: 1, to: 0, ...land })]
  return { exit, enter }
}

function within(window: Window, from: number, to: number): { start: number; end: number } {
  const start = window.moveStart * window.duration, span = (window.moveEnd - window.moveStart) * window.duration
  return { start: start + span * from, end: start + span * to }
}

function deskSlot(url: string, pageScale: number): Scene3DSlot {
  const scale = pageScale * COMIC_DESK_SPAN
  return printed('desk', [0, pageScale - scale, -COMIC_DESK_BEHIND], scale, url)
}

function live(base: Scene3DSlot[], input: ComicDressInput): Scene3DSlot[] {
  const clip = input.panels[input.toPanel]?.live
  if (!clip) return base
  return base.map(slot => slot.id !== `panel-${input.toPanel}` ? slot : {
    ...slot,
    screen: {
      sourceUrl: clip.url, media: 'video', mode: 'plane', targetMesh: '', anchor: '', offset: [0, 0, 0], pitch: 0, yaw: 0, roll: 0,
      width: 1, height: 1, style: 'frameless', fit: 'cover', start: 0, speed: 1, loop: false, flipY: false, transparent: true, lines: clip.lines,
    },
  })
}

/** Printed twins of every panel. The fading one is `fading`; the other cut panel stays printed; fillers are printed already. */
function twins(base: Scene3DSlot[], input: ComicDressInput, fading: number, fade: ImageFade): Scene3DSlot[] {
  return input.panels.flatMap((panel, index) => {
    const picture = base.find(slot => slot.id === `panel-${index}`)
    if (!picture) return []
    const own = index === fading ? fade : undefined
    const out: Scene3DSlot[] = []
    if (panel.print) out.push(printed(`print-${index}`, ahead(picture.position, COMIC_PRINT_AHEAD), picture.scale, panel.print, own))
    if (panel.shadow) out.push(printed(`shadow-${index}`, ahead(picture.position, COMIC_SHADOW_AHEAD), picture.scale, panel.shadow, own))
    const sticker = base.find(slot => slot.id === `cutout-${index}`)
    if (sticker && panel.printCutout) out.push(printedSticker(index, sticker, picture, panel.printCutout, input.fov, own))
    return out
  })
}

/** The printed sticker sits just in front of the clean one, scaled so both project the same from the fill pose. */
function printedSticker(index: number, sticker: Scene3DSlot, picture: Scene3DSlot, url: string, fov: number, fade?: ImageFade): Scene3DSlot {
  const centreY = picture.position[1] + picture.scale
  const distance = picture.scale / Math.tan((fov * Math.PI) / 360)
  const nearer = (distance - (sticker.position[2] - picture.position[2]) - COMIC_PRINT_AHEAD) / (distance - (sticker.position[2] - picture.position[2]))
  const scale = sticker.scale * nearer
  return printed(`print-cutout-${index}`, [sticker.position[0], centreY - scale, sticker.position[2] + COMIC_PRINT_AHEAD], scale, url, fade)
}

function ahead(position: Vec3, metres: number): Vec3 {
  return [position[0], position[1], position[2] + metres]
}

/** Printed layers keep mipmaps (no `sharp`), so the halftone does not shimmer when the page is small on screen. */
function printed(id: string, position: Vec3, scale: number, url: string, fade?: ImageFade): Scene3DSlot {
  return {
    id, slot: 'prop', media: 'image', surface: 'cutout', imageLook: { unlit: true, ...(fade ? { fade } : {}) },
    sourceUrl: url, clip: null, position, rotationY: 0, scale,
  }
}
