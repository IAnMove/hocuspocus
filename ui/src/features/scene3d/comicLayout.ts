import type { ComicFormat } from './comicPage.ts'

/** Dark rim around the paper, then the paper's own padding. Cells tile the rectangle inside that padding. */
export const COMIC_PAGE_RIM = 32
export const COMIC_PAD = 28
/** One gutter width between every pair of cells. Nothing else is left on the paper. */
export const COMIC_GUTTER = 18
/** Each window is this many pixels larger than its cell, so the cut frame shows picture rather than ink. */
export const COMIC_HOLE = 3
const INSET = COMIC_PAGE_RIM + COMIC_PAD

export type ComicCell = { x: number; y: number; w: number; h: number; hero: boolean }
export type ComicLayout = { pageW: number; pageH: number; cells: ComicCell[] }

type Raw = { x: number; y: number; w: number; h: number; hero: boolean }
type Sheet = { w: number; h: number; cells: Raw[] }

/** Two sizes per count. `side` is the first piece when a strip is split for a fifth or sixth panel. */
const ROWS = [
  { kA: 52, kB: 40, width: 1600, side: [300, 400] },
  { kA: 60, kB: 44, width: 1800, side: [340, 460] },
]
const THREES = [
  { kBig: 100, kSmall: 10, bigLeft: true },
  { kBig: 92, kSmall: 10, bigLeft: false },
]

export function isFrameAspect(format: ComicFormat, width: number, height: number): boolean {
  return format === 'portrait' ? width * 16 === height * 9 : width * 9 === height * 16
}

/** `seed` picks the variant. The two hero rects are swapped onto `from` and `to`, so those panels keep the frame. */
export function chooseComicLayout(format: ComicFormat, count: number, seed: number, from: number, to: number): ComicLayout {
  if (!Number.isInteger(count) || count < 3 || count > 6) throw new Error('panel_count')
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= count || to >= count) throw new Error('panel_index')
  if (from === to) throw new Error('same_panel')
  if (!Number.isInteger(seed)) throw new Error('invalid_seed')
  const sheet = orient(format, count === 3 ? threeLayout(Math.abs(seed) % 2) : rowLayout(count, Math.abs(seed) % 2))
  const cells = sheet.cells.map(cell => ({ ...cell, x: cell.x + INSET, y: cell.y + INSET }))
  assignHeroes(cells, from, to)
  return { pageW: sheet.w + INSET * 2, pageH: sheet.h + INSET * 2, cells }
}

function heroBox(k: number) {
  return { w: 16 * k, h: 9 * k }
}

/** Landscape content. Portrait swaps the axes, which turns each 16:9 hero into 9:16. */
function orient(format: ComicFormat, sheet: Sheet): Sheet {
  if (format !== 'portrait') return sheet
  return {
    w: sheet.h, h: sheet.w,
    cells: sheet.cells.map(cell => ({ x: cell.y, y: cell.x, w: cell.h, h: cell.w, hero: cell.hero })),
  }
}

function threeLayout(variant: number): Sheet {
  const spec = THREES[variant]
  const big = heroBox(spec.kBig)
  const small = heroBox(spec.kSmall)
  const stripH = big.h - small.h - COMIC_GUTTER
  const xSide = spec.bigLeft ? big.w + COMIC_GUTTER : 0
  const xBig = spec.bigLeft ? 0 : small.w + COMIC_GUTTER
  return {
    w: big.w + COMIC_GUTTER + small.w, h: big.h,
    cells: [
      { x: xBig, y: 0, w: big.w, h: big.h, hero: true },
      { x: xSide, y: spec.bigLeft ? small.h + COMIC_GUTTER : 0, w: small.w, h: stripH, hero: false },
      { x: xSide, y: spec.bigLeft ? 0 : stripH + COMIC_GUTTER, w: small.w, h: small.h, hero: true },
    ],
  }
}

function rowLayout(count: number, variant: number): Sheet {
  const spec = ROWS[variant]
  const top = heroBox(spec.kA)
  const bottom = heroBox(spec.kB)
  const yBottom = top.h + COMIC_GUTTER
  const cells: Raw[] = [{ x: 0, y: 0, w: top.w, h: top.h, hero: true }]
  lay(cells, top.w + COMIC_GUTTER, 0, top.h, pieces(spec.width - top.w - COMIC_GUTTER, count >= 5 ? spec.side[0] : 0))
  lay(cells, 0, yBottom, bottom.h, pieces(spec.width - bottom.w - COMIC_GUTTER, count >= 6 ? spec.side[1] : 0))
  cells.push({ x: spec.width - bottom.w, y: yBottom, w: bottom.w, h: bottom.h, hero: true })
  return { w: spec.width, h: top.h + COMIC_GUTTER + bottom.h, cells }
}

function pieces(total: number, left: number): number[] {
  if (!(left > 0)) return [total]
  return [left, total - COMIC_GUTTER - left]
}

function lay(cells: Raw[], x: number, y: number, height: number, widths: number[]) {
  let cursor = x
  for (const width of widths) {
    cells.push({ x: cursor, y, w: width, h: height, hero: false })
    cursor += width + COMIC_GUTTER
  }
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
  punchHoles(pixels, pageW, pageH, cells)
  return pixels
}

/** Clear a window a few pixels larger than the cell. The ink border stays on the paper around it. */
function punchHoles(pixels: Uint8Array, pageW: number, pageH: number, cells: ComicCell[]) {
  for (const cell of cells) {
    const x0 = Math.max(0, cell.x - COMIC_HOLE)
    const y0 = Math.max(0, cell.y - COMIC_HOLE)
    const x1 = Math.min(pageW, cell.x + cell.w + COMIC_HOLE)
    const y1 = Math.min(pageH, cell.y + cell.h + COMIC_HOLE)
    for (let y = y0; y < y1; y += 1) {
      for (let x = x0; x < x1; x += 1) pixels[(y * pageW + x) * 4 + 3] = 0
    }
  }
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
