import type { ComicFormat } from './comicPage.ts'

/** Dark rim around the paper, then the paper's own padding. Cells are authored inside the padding. */
export const COMIC_PAGE_RIM = 32
const PAD = 28
const INSET = COMIC_PAGE_RIM + PAD

type Rect = [number, number, number, number, 0 | 1]

export type ComicCell = { x: number; y: number; w: number; h: number; hero: boolean }
export type ComicLayout = { pageW: number; pageH: number; cells: ComicCell[] }

/** Two hand-authored pages per count. The padded page stays within 6% of the frame.
 * A hero is an exact 16:9 or 9:16 cell. The others are tall strips, wide strips or an inset. */
const PAGES: Record<ComicFormat, Record<number, Rect[][]>> = {
  landscape: {
    3: [
      [[0, 0, 960, 540, 1], [976, 0, 640, 360, 1], [0, 556, 900, 289, 0]],
      [[0, 0, 800, 450, 1], [816, 0, 640, 360, 1], [1472, 0, 200, 877, 0]],
    ],
    4: [
      [[0, 0, 720, 405, 1], [736, 0, 160, 405, 0], [912, 0, 640, 360, 1], [0, 421, 1552, 389, 0]],
      [[0, 0, 800, 450, 1], [816, 80, 180, 500, 0], [1012, 0, 640, 360, 1], [0, 596, 1652, 269, 0]],
    ],
    5: [
      [[0, 0, 800, 450, 1], [816, 0, 726, 160, 0], [816, 176, 180, 500, 0], [1100, 280, 280, 140, 0], [0, 466, 640, 360, 1]],
      [[0, 40, 720, 405, 1], [736, 0, 800, 180, 0], [1280, 196, 200, 605, 0], [0, 461, 560, 315, 1], [600, 520, 400, 160, 0]],
    ],
    6: [
      [[0, 0, 640, 360, 1], [656, 0, 500, 150, 0], [1172, 0, 230, 460, 0], [700, 220, 280, 140, 0], [0, 476, 480, 270, 1], [496, 520, 600, 160, 0]],
      [[0, 0, 800, 450, 1], [816, 0, 560, 150, 0], [816, 166, 170, 450, 0], [1100, 240, 260, 140, 0], [0, 466, 560, 315, 1], [1002, 632, 516, 180, 0]],
    ],
  },
  portrait: {
    3: [
      [[0, 0, 405, 720, 1], [0, 736, 315, 560, 1], [200, 1312, 565, 160, 0]],
      [[0, 0, 360, 640, 1], [0, 656, 405, 720, 1], [421, 0, 291, 1200, 0]],
    ],
    4: [
      [[0, 0, 405, 720, 1], [421, 0, 280, 180, 0], [560, 196, 160, 900, 0], [40, 816, 315, 560, 1]],
      [[0, 0, 495, 880, 1], [511, 0, 232, 1100, 0], [60, 896, 220, 120, 0], [0, 1032, 225, 400, 1]],
    ],
    5: [
      [[0, 0, 405, 720, 1], [421, 0, 280, 160, 0], [560, 176, 199, 1000, 0], [40, 736, 220, 130, 0], [80, 900, 315, 560, 1]],
      [[40, 0, 315, 560, 1], [371, 280, 140, 110, 0], [527, 0, 200, 200, 0], [0, 576, 360, 640, 1], [380, 700, 280, 700, 0]],
    ],
    6: [
      [[0, 0, 405, 720, 1], [421, 0, 280, 160, 0], [560, 176, 199, 1000, 0], [40, 736, 200, 120, 0], [420, 736, 124, 140, 0], [80, 900, 315, 560, 1]],
      [[0, 0, 405, 720, 1], [421, 0, 300, 150, 0], [421, 166, 140, 480, 0], [577, 166, 166, 1100, 0], [200, 736, 180, 110, 0], [40, 872, 315, 560, 1]],
    ],
  },
}

export function isFrameAspect(format: ComicFormat, width: number, height: number): boolean {
  return format === 'portrait' ? width * 16 === height * 9 : width * 9 === height * 16
}

/** `seed` picks the variant. The two hero rects are swapped onto `from` and `to`, so those panels keep the frame. */
export function chooseComicLayout(format: ComicFormat, count: number, seed: number, from: number, to: number): ComicLayout {
  const variants = PAGES[format]?.[count]
  if (!variants) throw new Error('panel_count')
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= count || to >= count) throw new Error('panel_index')
  if (from === to) throw new Error('same_panel')
  if (!Number.isInteger(seed)) throw new Error('invalid_seed')
  const rects = variants[Math.abs(seed) % variants.length]
  const contentW = Math.max(...rects.map(rect => rect[0] + rect[2]))
  const contentH = Math.max(...rects.map(rect => rect[1] + rect[3]))
  const cells = rects.map(([x, y, w, h, hero]) => ({ x: x + INSET, y: y + INSET, w, h, hero: hero === 1 }))
  assignHeroes(cells, from, to)
  return { pageW: contentW + INSET * 2, pageH: contentH + INSET * 2, cells }
}

function assignHeroes(cells: ComicCell[], from: number, to: number) {
  const heroes = cells.flatMap((cell, index) => cell.hero ? [index] : [])
  const need = [from, to].filter(index => !cells[index].hero)
  const donors = heroes.filter(index => index !== from && index !== to)
  if (heroes.length !== 2 || donors.length < need.length) throw new Error('comic_layout')
  need.forEach((index, step) => {
    const donor = donors[step]
    const held = cells[index]
    cells[index] = cells[donor]
    cells[donor] = held
  })
}

/** Original paper: a warm grey, a hash grain, ink borders and a cheap offset shadow. No downloaded texture. */
export function paintComicPage(layout: ComicLayout): Uint8Array {
  const { pageW, pageH, cells } = layout
  const pixels = new Uint8Array(pageW * pageH * 4)
  fillPage(pixels, pageW, pageH)
  paintShadows(pixels, pageW, pageH, cells)
  paintBorders(pixels, pageW, pageH, cells)
  return pixels
}

function fillPage(pixels: Uint8Array, pageW: number, pageH: number) {
  const right = pageW - COMIC_PAGE_RIM
  const bottom = pageH - COMIC_PAGE_RIM
  for (let y = 0; y < pageH; y += 1) {
    for (let x = 0; x < pageW; x += 1) {
      const index = (y * pageW + x) * 4
      const paper = x >= COMIC_PAGE_RIM && x < right && y >= COMIC_PAGE_RIM && y < bottom
      if (paper) {
        const speck = grain(x, y) >> 4
        pixels[index] = 236 + speck
        pixels[index + 1] = 228 + speck
        pixels[index + 2] = 214 + speck
      } else {
        const shade = backdropShade(x, y, pageW, pageH)
        pixels[index] = shade
        pixels[index + 1] = Math.max(0, shade - 1)
        pixels[index + 2] = shade + 3
      }
      pixels[index + 3] = 255
    }
  }
}

function backdropShade(x: number, y: number, pageW: number, pageH: number): number {
  const nx = (x + 0.5) / pageW - 0.5
  const ny = (y + 0.5) / pageH - 0.5
  const falloff = Math.min(1, Math.hypot(nx * 1.7, ny * 1.7))
  return 26 - Math.round(falloff * 16)
}

function grain(x: number, y: number): number {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263)
  n = Math.imul(n ^ (n >>> 13), 1274126177)
  return ((n ^ (n >>> 16)) & 255) - 128
}

function paintShadows(pixels: Uint8Array, pageW: number, pageH: number, cells: ComicCell[]) {
  for (const cell of cells) {
    for (let dy = -10; dy < cell.h + 10; dy += 1) {
      for (let dx = -10; dx < cell.w + 10; dx += 1) {
        const x = cell.x + 6 + dx
        const y = cell.y + 8 + dy
        if (x < COMIC_PAGE_RIM || y < COMIC_PAGE_RIM || x >= pageW - COMIC_PAGE_RIM || y >= pageH - COMIC_PAGE_RIM) continue
        if (covers(cell, x, y)) continue
        const core = dx >= 0 && dy >= 0 && dx < cell.w && dy < cell.h
        darken(pixels, pageW, x, y, core ? 42 : 16)
      }
    }
  }
}

function paintBorders(pixels: Uint8Array, pageW: number, pageH: number, cells: ComicCell[]) {
  for (const cell of cells) {
    for (let y = cell.y - 5; y < cell.y + cell.h + 5; y += 1) {
      for (let x = cell.x - 5; x < cell.x + cell.w + 5; x += 1) {
        if (x < 0 || y < 0 || x >= pageW || y >= pageH || covers(cell, x, y)) continue
        const index = (y * pageW + x) * 4
        pixels[index] = 22
        pixels[index + 1] = 16
        pixels[index + 2] = 14
        pixels[index + 3] = 255
      }
    }
  }
}

function covers(cell: ComicCell, x: number, y: number): boolean {
  return x >= cell.x && y >= cell.y && x < cell.x + cell.w && y < cell.y + cell.h
}

function darken(pixels: Uint8Array, pageW: number, x: number, y: number, amount: number) {
  const index = (y * pageW + x) * 4
  pixels[index] = Math.max(0, pixels[index] - amount)
  pixels[index + 1] = Math.max(0, pixels[index + 1] - amount)
  pixels[index + 2] = Math.max(0, pixels[index + 2] - amount)
}
