import { comicId } from './model'
import type { ComicPage, ComicPanelElement, ComicTextElement } from './types'

const panel = (x: number, y: number, width: number, height: number): ComicPanelElement => ({
  id: comicId('panel'),
  type: 'panel',
  x: Math.round(x),
  y: Math.round(y),
  width: Math.round(width),
  height: Math.round(height),
  rotation: 0,
  zIndex: 1,
  parentId: null,
  visible: true,
  borderWidth: 4,
  borderColor: '#111111',
  borderRadius: 0,
  background: '#ffffff',
})

const grid = (page: ComicPage, rows: number, columns: number) => {
  const margin = 28
  const gap = 14
  const width = (page.width - margin * 2 - gap * (columns - 1)) / columns
  const height = (page.height - margin * 2 - gap * (rows - 1)) / rows
  return Array.from({ length: rows * columns }, (_, index) => {
    const row = Math.floor(index / columns)
    const column = index % columns
    return panel(margin + column * (width + gap), margin + row * (height + gap), width, height)
  })
}

const slantedPair = (page: ComicPage, y: number, height: number, top = .58, bottom = .42) => {
  const margin = 28
  const gap = 14
  const inner = page.width - margin * 2
  const leftTop = inner * top - gap / 2
  const leftBottom = inner * bottom - gap / 2
  const rightTop = inner * top + gap / 2
  const rightBottom = inner * bottom + gap / 2
  const leftWidth = Math.max(leftTop, leftBottom)
  const rightX = margin + Math.min(rightTop, rightBottom)
  const left = panel(margin, y, leftWidth, height)
  left.points = [[0, 0], [leftTop / leftWidth, 0], [leftBottom / leftWidth, 1], [0, 1]]
  const right = panel(rightX, y, page.width - margin - rightX, height)
  right.points = [
    [(margin + rightTop - rightX) / right.width, 0],
    [1, 0],
    [1, 1],
    [(margin + rightBottom - rightX) / right.width, 1],
  ]
  return [left, right]
}

export const COMIC_LAYOUTS = [
  { name: '2 × 2', build: (page: ComicPage) => grid(page, 2, 2) },
  { name: '3 rows', build: (page: ComicPage) => grid(page, 3, 1) },
  { name: '6 panels', build: (page: ComicPage) => grid(page, 3, 2) },
  {
    name: 'Hero + 2',
    build: (page: ComicPage) => {
      const margin = 28
      const gap = 14
      const width = page.width - margin * 2
      const topHeight = (page.height - margin * 2 - gap) * .56
      const bottomHeight = page.height - margin * 2 - gap - topHeight
      return [
        panel(margin, margin, width, topHeight),
        panel(margin, margin + topHeight + gap, (width - gap) / 2, bottomHeight),
        panel(margin + (width + gap) / 2, margin + topHeight + gap, (width - gap) / 2, bottomHeight),
      ]
    },
  },
  {
    name: 'Diagonal action',
    build: (page: ComicPage) => {
      const margin = 28
      const gap = 14
      const height = (page.height - margin * 2 - gap) / 2
      return [
        ...slantedPair(page, margin, height, .62, .43),
        ...slantedPair(page, margin + height + gap, height, .38, .6),
      ]
    },
  },
] as const

type EffectPreset = { name: string; values: Partial<ComicTextElement> }

const base: Partial<ComicTextElement> = {
  type: 'text',
  parentId: null,
  zIndex: 60,
  width: 250,
  height: 170,
  fontSize: 48,
  fontFamily: '"Arial Black", Impact, sans-serif',
  bold: true,
  italic: false,
  align: 'center',
  lineHeight: .9,
  letterSpacing: 1,
  textStrokeWidth: 3,
  textStrokeColor: '#111111',
  textEffect: 'shadow',
  textEffectColor: '#111111',
  bubbleStrokeColor: '#111111',
  bubbleStrokeWidth: 3,
  bubblePadding: 18,
  visible: true,
}

export const COMIC_EFFECTS: EffectPreset[] = [
  { name: 'POW!', values: { ...base, content: 'POW!', color: '#e11d48', bubble: 'burst', bubbleBackground: '#fde047', bubbleSecondary: '#f97316', rotation: -8 } },
  { name: 'BOOM!', values: { ...base, content: 'BOOM!', color: '#7e22ce', bubble: 'burst', bubbleBackground: '#fef08a', bubbleSecondary: '#ec4899', rotation: 6 } },
  { name: 'ZAP!', values: { ...base, content: 'ZAP!', color: '#dc2626', bubble: 'electric', bubbleBackground: '#fde047', rotation: -12 } },
  { name: 'CRASH!', values: { ...base, content: 'CRASH!', color: '#111111', bubble: 'burst', bubbleBackground: '#facc15', bubbleSecondary: '#f97316', rotation: 9 } },
  { name: 'POOF!', values: { ...base, content: 'POOF!', color: '#ec4899', bubble: 'cloud', bubbleBackground: '#ffffff', rotation: -5 } },
  { name: 'WHAM!', values: { ...base, content: 'WHAM!', color: '#fef08a', bubble: 'electric', bubbleBackground: '#2dd4bf', textEffect: 'extrude', textEffectColor: '#4c1d95', rotation: -7 } },
  { name: 'RUMBLE…', values: { ...base, content: 'RUMBLE…', width: 310, height: 120, color: '#f5e6c8', bubble: 'none', textEffect: 'extrude', textEffectColor: '#5b4636', rotation: 3 } },
  { name: 'SPLASH!', values: { ...base, content: 'SPLASH!', color: '#ffffff', bubble: 'burst', bubbleBackground: '#38bdf8', bubbleSecondary: '#dbeafe', rotation: -5 } },
  { name: 'SHHH…', values: { ...base, content: 'SHHH…', width: 230, height: 120, fontSize: 36, color: '#5b4b8a', bubble: 'whisper', bubbleBackground: '#f8f4ff', bubbleStrokeStyle: 'dashed', textStrokeWidth: 0, textEffect: 'none', rotation: 0 } },
  { name: 'NO!', values: { ...base, content: 'NO!', width: 180, height: 130, color: '#ffffff', bubble: 'ellipse', bubbleBackground: '#dc2626', rotation: 8 } },
]

export function createEffect(page: ComicPage, preset: EffectPreset): ComicTextElement {
  return {
    id: comicId('effect'),
    x: page.width / 2 - Number(preset.values.width ?? 250) / 2,
    y: page.height / 2 - Number(preset.values.height ?? 170) / 2,
    rotation: 0,
    zIndex: 60,
    visible: true,
    type: 'text',
    content: preset.name,
    width: 250,
    height: 170,
    fontSize: 48,
    fontFamily: '"Arial Black", Impact, sans-serif',
    color: '#111111',
    bold: true,
    italic: false,
    align: 'center',
    bubble: 'burst',
    bubbleBackground: '#fde047',
    bubbleStrokeColor: '#111111',
    bubbleStrokeWidth: 3,
    ...preset.values,
  }
}
