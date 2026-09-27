import { TEXT_FONTS, type TextAlign, type TextBox, type TextFont, type TextShadow, type TextStroke } from './types'

export type LyricWord = { text: string; start: number; end: number }
export type LyricLine = { id: string; start: number; end: number; words: LyricWord[] }
export type LyricMode = 'karaoke' | 'word-pop' | 'line-fade' | 'bounce'
export type LyricStyle = {
  font: TextFont
  size: number
  color: string
  activeColor: string
  weight?: number
  x: number
  y: number
  maxWidth: number
  align: TextAlign
  uppercase?: boolean
  stroke?: TextStroke
  shadow?: TextShadow
  box?: TextBox
  visibleLines: 1 | 2
  beatPulse?: number
}
export type SceneLyrics = {
  mode: LyricMode
  lines: LyricLine[]
  style: LyricStyle
  source?: { kind: 'timing-bundle' | 'srt' | 'lrc' | 'manual'; file?: string }
}

const MODES: LyricMode[] = ['karaoke', 'word-pop', 'line-fade', 'bounce']
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const num = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? clamp(value, min, max) : fallback
const stamp = (minutes: string, seconds: string, fraction?: string) => {
  const scale = !fraction ? 0 : fraction.length >= 3 ? 1000 : fraction.length === 2 ? 100 : 10
  return Number(minutes) * 60 + Number(seconds) + (fraction ? Number(fraction) / scale : 0)
}
const wordsOf = (text: string, start: number, end: number): LyricWord[] => {
  const parts = text.split(/\s+/).filter(Boolean)
  const weight = parts.reduce((sum, part) => sum + Math.max(1, part.length), 0)
  let cursor = start
  return parts.map(part => {
    const span = (end - start) * (Math.max(1, part.length) / weight)
    const word = { text: part, start: cursor, end: cursor + span }
    cursor += span
    return word
  })
}

function lineFrom(id: string, text: string, start: number, end: number, words?: LyricWord[]): LyricLine | undefined {
  if (!(end > start) || !text.trim()) return undefined
  const timed = words?.filter(word => word.text && word.end > word.start)
  return { id, start, end, words: timed?.length ? timed : wordsOf(text, start, end) }
}

const SECTION_TAG = /^\[[^\]]+\]$/
const LRC_STAMP = /\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/
const SRT_ARROW = /\d{2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{1,3}/

export function importPlainLyrics(text: string, duration: number, offset = 0): LyricLine[] {
  const rows = text.split(/\r?\n/).map(row => row.trim()).filter(row => row && !SECTION_TAG.test(row)).slice(0, 400)
  const span = Math.max(0.2, duration)
  return rows.flatMap((row, index) => {
    const start = offset + span * index / rows.length
    const end = offset + span * (index + 1) / rows.length
    const line = lineFrom(`line-${index + 1}`, row, Math.max(0, start), Math.max(start + 0.05, end))
    return line ? [line] : []
  }).slice(0, 400)
}

/** Paste entry used by the editor. MiniMax/Story lyrics use [Verse]/[Chorus] tags, which are not LRC stamps. */
export function importLyricsText(text: string, duration: number, offset = 0): LyricLine[] {
  const trimmed = text.trim()
  if (SRT_ARROW.test(trimmed)) {
    const lines = importSrt(trimmed, offset)
    if (lines.length) return lines
  }
  if (LRC_STAMP.test(trimmed)) {
    const lines = importLrc(trimmed, offset)
    if (lines.length) return lines
  }
  return importPlainLyrics(trimmed, duration, offset)
}

export function importLrc(text: string, offset = 0): LyricLine[] {
  const stamped = text.split(/\r?\n/).flatMap(row => {
    const marks = [...row.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)]
    if (!marks.length) return []
    const body = row.replace(/\[[^\]]+\]/g, '').trim()
    if (!body) return []
    return marks.map(mark => ({ at: stamp(mark[1], mark[2], mark[3]), body, words: markedWords(body) }))
  }).sort((a, b) => a.at - b.at)
  return stamped.flatMap((row, index) => {
    const start = row.at + offset
    const end = (stamped[index + 1]?.at ?? row.at + 4) + offset
    const words = row.words?.map(word => ({ ...word, start: word.start + offset, end: word.end + offset }))
    const line = lineFrom(`line-${index + 1}`, row.body, start, Math.max(start + 0.05, end), words)
    return line ? [line] : []
  }).slice(0, 400)
}

function markedWords(body: string): LyricWord[] | undefined {
  const marks = [...body.matchAll(/<(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?>([^<]*)/g)]
  if (!marks.length) return undefined
  return marks.flatMap((mark, index) => {
    const text = mark[4].trim()
    if (!text) return []
    const start = stamp(mark[1], mark[2], mark[3])
    const next = marks[index + 1]
    const end = next ? stamp(next[1], next[2], next[3]) : start + 0.4
    return [{ text, start, end: Math.max(start + 0.05, end) }]
  })
}

const clock = (hours: string, minutes: string, seconds: string, fraction: string) => {
  const scale = fraction.length >= 3 ? 1000 : fraction.length === 2 ? 100 : 10
  return Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds) + Number(fraction) / scale
}

export function importSrt(text: string, offset = 0): LyricLine[] {
  const blocks = text.replace(/^\uFEFF/, '').split(/\r?\n\r?\n/)
  return blocks.flatMap((block, index) => {
    const rows = block.split(/\r?\n/).map(row => row.trim()).filter(Boolean)
    const timing = rows.map(row => row.match(/(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})/)).find(Boolean)
    if (!timing) return []
    const start = clock(timing[1], timing[2], timing[3], timing[4]) + offset
    const end = clock(timing[5], timing[6], timing[7], timing[8]) + offset
    const caption = rows.filter(row => !/^\d+$/.test(row) && !row.includes('-->')).join(' ')
    const line = lineFrom(`line-${index + 1}`, caption, start, end)
    return line ? [line] : []
  }).slice(0, 400)
}

export function importTimingBundle(raw: unknown, offset = 0): LyricLine[] {
  const timeline = raw && typeof raw === 'object' && Array.isArray((raw as { timeline?: unknown }).timeline)
    ? (raw as { timeline: unknown[] }).timeline : Array.isArray(raw) ? raw : []
  return timeline.flatMap((value, index) => {
    if (!value || typeof value !== 'object') return []
    const row = value as { text?: unknown; start?: unknown; end?: unknown; words?: unknown }
    if (typeof row.text !== 'string') return []
    const start = num(row.start, 0, 0, 36000) + offset
    const end = num(row.end, start + 2, 0, 36000) + offset
    const words = Array.isArray(row.words) ? row.words.flatMap(word => {
      if (!word || typeof word !== 'object') return []
      const item = word as { text?: unknown; start?: unknown; end?: unknown }
      if (typeof item.text !== 'string') return []
      const wordStart = num(item.start, start, 0, 36000) + offset
      const wordEnd = num(item.end, wordStart + 0.2, 0, 36000) + offset
      return [{ text: item.text, start: wordStart, end: Math.max(wordStart + 0.02, wordEnd) }]
    }) : undefined
    const line = lineFrom(`line-${index + 1}`, row.text, start, Math.max(start + 0.05, end), words)
    return line ? [line] : []
  }).slice(0, 400)
}

function defaultStyle(raw: Partial<LyricStyle> | undefined): LyricStyle {
  return {
    font: TEXT_FONTS.includes(raw?.font as TextFont) ? raw!.font as TextFont : 'sans',
    size: num(raw?.size, 7, 2, 25),
    color: typeof raw?.color === 'string' && /^#[0-9a-f]{6}$/i.test(raw.color) ? raw.color : '#f4efe6',
    activeColor: typeof raw?.activeColor === 'string' && /^#[0-9a-f]{6}$/i.test(raw.activeColor) ? raw.activeColor : '#ffe08a',
    x: num(raw?.x, 50, 0, 100), y: num(raw?.y, 78, 0, 100), maxWidth: num(raw?.maxWidth, 80, 10, 100),
    align: raw?.align === 'left' || raw?.align === 'right' ? raw.align : 'center',
    visibleLines: raw?.visibleLines === 2 ? 2 : 1,
    ...(raw?.uppercase === true ? { uppercase: true } : {}),
    ...(typeof raw?.weight === 'number' ? { weight: num(raw.weight, 700, 400, 900) } : {}),
    ...(typeof raw?.beatPulse === 'number' ? { beatPulse: num(raw.beatPulse, 0, 0, 1) } : {}),
  }
}

function capWords(lines: LyricLine[]) {
  let left = 4000
  return lines.map(line => {
    const words = line.words.slice(0, left)
    left -= words.length
    return { ...line, words }
  }).filter(line => line.words.length)
}

export function parseSceneLyrics(raw: unknown): SceneLyrics | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<SceneLyrics>
  if (!Array.isArray(value.lines)) return undefined
  const lines = capWords(value.lines.flatMap((line, index) => {
    if (!line || typeof line !== 'object') return []
    const row = line as Partial<LyricLine>
    const built = lineFrom(typeof row.id === 'string' && row.id ? row.id.slice(0, 80) : `line-${index + 1}`, (row.words ?? []).map(word => word.text).join(' '), num(row.start, 0, 0, 36000), num(row.end, 0, 0, 36000), row.words)
    return built ? [built] : []
  }).slice(0, 400))
  if (!lines.length) return undefined
  return {
    mode: MODES.includes(value.mode as LyricMode) ? value.mode as LyricMode : 'karaoke',
    lines, style: defaultStyle(value.style),
    ...(value.source && typeof value.source === 'object' ? { source: value.source } : {}),
  }
}

export function lyricFields(raw: unknown): { lyrics?: SceneLyrics } {
  const lyrics = parseSceneLyrics(raw)
  return lyrics ? { lyrics } : {}
}
