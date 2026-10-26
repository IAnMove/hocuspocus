import type { ComicFormat } from './comicPage.ts'

/** Dark rim around the paper, then the paper's own padding. Cells are authored inside the padding. */
const BACKDROP = 32
const PAD = 28
const INSET = BACKDROP + PAD

type Rect = [number, number, number, number, 0 | 1]

export type ComicCell = { x: number; y: number; w: number; h: number; hero: boolean }
export type ComicLayout = { pageW: number; pageH: number; cells: ComicCell[] }

/** Two hand-authored pages per count. A hero is an exact 16:9 or 9:16 cell; the others are not. */
const PAGES: Record<ComicFormat, Record<number, Rect[][]>> = {
  landscape: {
    3: [
      [[0, 0, 960, 540, 1], [0, 556, 464, 300, 0], [480, 556, 480, 270, 1]],
      [[0, 0, 640, 360, 1], [656, 0, 480, 270, 1], [0, 376, 1136, 200, 0]],
    ],
    4: [
      [[0, 0, 960, 540, 1], [0, 556, 220, 180, 0], [236, 556, 480, 270, 1], [732, 556, 228, 240, 0]],
      [[0, 0, 640, 360, 1], [656, 0, 280, 150, 0], [656, 166, 280, 194, 0], [0, 376, 480, 270, 1]],
    ],
    5: [
      [[0, 0, 960, 540, 1], [0, 556, 200, 160, 0], [216, 556, 480, 270, 1], [712, 556, 120, 200, 0], [848, 556, 112, 240, 0]],
      [[0, 0, 480, 270, 1], [496, 0, 200, 180, 0], [712, 0, 480, 270, 1], [0, 286, 680, 200, 0], [696, 286, 496, 220, 0]],
    ],
    6: [
      [[0, 0, 800, 450, 1], [816, 0, 240, 210, 0], [816, 226, 240, 224, 0], [0, 466, 250, 180, 0], [266, 466, 480, 270, 1], [762, 466, 294, 200, 0]],
      [[0, 0, 640, 360, 1], [656, 0, 360, 190, 0], [1032, 0, 200, 360, 0], [656, 206, 360, 154, 0], [0, 376, 480, 270, 1], [496, 376, 736, 180, 0]],
    ],
  },
  portrait: {
    3: [
      [[0, 0, 360, 640, 1], [376, 0, 270, 480, 1], [376, 496, 270, 144, 0]],
      [[0, 0, 450, 800, 1], [0, 816, 164, 220, 0], [180, 816, 270, 480, 1]],
    ],
    4: [
      [[0, 0, 360, 640, 1], [376, 0, 270, 480, 1], [376, 496, 120, 144, 0], [512, 496, 134, 144, 0]],
      [[0, 0, 270, 480, 1], [286, 0, 180, 320, 1], [286, 336, 180, 144, 0], [0, 496, 466, 200, 0]],
    ],
    5: [
      [[0, 0, 450, 800, 1], [0, 816, 210, 180, 0], [226, 816, 224, 200, 0], [0, 1032, 180, 320, 1], [196, 1032, 254, 200, 0]],
      [[0, 0, 270, 480, 1], [286, 0, 180, 320, 1], [482, 0, 160, 200, 0], [482, 216, 160, 264, 0], [0, 496, 642, 180, 0]],
    ],
    6: [
      [[0, 0, 360, 640, 1], [376, 0, 180, 320, 1], [572, 0, 140, 300, 0], [572, 316, 140, 324, 0], [376, 336, 180, 144, 0], [376, 496, 180, 144, 0]],
      [[0, 0, 270, 480, 1], [286, 0, 180, 320, 1], [286, 336, 180, 144, 0], [482, 0, 160, 220, 0], [482, 236, 160, 244, 0], [0, 496, 642, 180, 0]],
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
  const right = pageW - BACKDROP
  const bottom = pageH - BACKDROP
  for (let y = 0; y < pageH; y += 1) {
    for (let x = 0; x < pageW; x += 1) {
      const index = (y * pageW + x) * 4
      const paper = x >= BACKDROP && x < right && y >= BACKDROP && y < bottom
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
        if (x < BACKDROP || y < BACKDROP || x >= pageW - BACKDROP || y >= pageH - BACKDROP) continue
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
