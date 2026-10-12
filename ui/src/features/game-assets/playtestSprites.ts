import { atlasFrames, type AtlasFrame } from './reviewModel'
import { PLAY_WIDTH, WORLD_WIDTH, type Anchor, type Body, type PlayInput, type PlaySprite } from './playtestScene'

export interface Pivot {
  x: number
  y: number
}

/** The frames of one tag with the timing, loop, mirror and pivot its atlas declares. */
export interface SheetClip {
  frames: AtlasFrame[]
  loop: boolean
  mirror: boolean
  pivot: Pivot
}

export interface PlayKeys extends PlayInput {
  attack: boolean
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** Bottom centre for feet (``{w//2, h-1}``), centre for effects (``{w//2, h//2}``), as ``pack_rows`` writes. */
export function anchorPivot(width: number, height: number, anchor: Anchor): Pivot {
  return { x: Math.floor(width / 2), y: anchor === 'bottom' ? Math.max(0, height - 1) : Math.floor(height / 2) }
}

interface Tag { name: string; from: number; to: number }

function readTags(meta: Record<string, unknown>): Tag[] {
  const raw = Array.isArray(meta.frameTags) ? meta.frameTags : []
  return raw.map(record).flatMap(tag => {
    const from = finite(tag.from)
    const to = finite(tag.to)
    return typeof tag.name === 'string' && from !== null && to !== null && to >= from ? [{ name: tag.name, from, to }] : []
  })
}

function tagLoop(meta: Record<string, unknown>, tag: string, fallback: boolean): boolean {
  const loop = meta.loop
  if (typeof loop === 'boolean') return loop
  const own = record(loop)[tag]
  return typeof own === 'boolean' ? own : fallback
}

function readPivot(meta: Record<string, unknown>, frame: AtlasFrame, anchor: Anchor): Pivot {
  const pivot = record(meta.pivot)
  const x = finite(pivot.x)
  const y = finite(pivot.y)
  return x !== null && y !== null ? { x, y } : anchorPivot(frame.w, frame.h, anchor)
}

/** The clip ``sprite.tag`` names in ``atlas`` (else its first tag, else every frame); ``null`` when it has no frames. */
export function sheetClip(atlas: unknown, sprite: PlaySprite): SheetClip | null {
  const all = atlasFrames(atlas).filter(frame => frame.w > 0 && frame.h > 0)
  if (!all.length) return null
  const meta = record(record(atlas).meta)
  const tags = readTags(meta)
  const tag = tags.find(item => item.name === sprite.tag) || tags[0]
  const frames = tag ? all.slice(tag.from, tag.to + 1) : all
  if (!frames.length) return null
  return {
    frames,
    loop: tagLoop(meta, tag?.name || '', sprite.loop),
    mirror: meta.mirror !== false,
    pivot: readPivot(meta, frames[0], sprite.anchor),
  }
}

/** A still image as a one-frame clip; stills face right and mirror for left. */
export function stillClip(width: number, height: number, anchor: Anchor): SheetClip {
  return { frames: [{ name: 'still', x: 0, y: 0, w: width, h: height, duration: 0 }], loop: false, mirror: true, pivot: anchorPivot(width, height, anchor) }
}

function frameMs(frame: AtlasFrame): number {
  return frame.duration > 0 ? frame.duration : 100
}

/** Milliseconds of one pass through the clip. */
export function clipLength(clip: SheetClip): number {
  return clip.frames.reduce((total, frame) => total + frameMs(frame), 0)
}

/** The frame shown ``elapsed`` ms into the clip: each frame lasts its own duration; a one-shot clip holds its last frame. */
export function clipFrameIndex(clip: SheetClip, elapsed: number): number {
  const count = clip.frames.length
  if (count <= 1) return 0
  const total = clipLength(clip)
  const time = Math.max(0, elapsed)
  if (!clip.loop && time >= total) return count - 1
  let left = clip.loop ? time % total : time
  for (let index = 0; index < count; index += 1) {
    left -= frameMs(clip.frames[index])
    if (left < 0) return index
  }
  return count - 1
}

/**
 * The top-left corner that puts the frame's pivot pixel on ``(x, y)``.
 * Mirrored, the frame flips around the pivot column, so the feet stay where they were.
 */
export function spriteBox(x: number, y: number, pivot: Pivot, width: number, flip: boolean): { left: number; top: number } {
  return { left: flip ? x - (width - 1 - pivot.x) : x - pivot.x, top: y - pivot.y }
}

/**
 * Where to draw copies of a layer ``width`` px wide for the camera at ``camera``.
 * A looping layer repeats to cover the view; a layer without ``loopX`` never wraps and stops at its edge.
 */
export function layerOffsets(camera: number, factor: number, width: number, loopX: boolean, view = PLAY_WIDTH): number[] {
  if (!(width > 0)) return []
  const shift = Math.max(0, camera) * factor
  if (!loopX) return [-Math.min(shift, Math.max(0, width - view)) || 0]
  const offsets: number[] = []
  for (let x = -(shift % width) || 0; x < view; x += width) offsets.push(x)
  return offsets
}

export interface TileRect {
  x: number
  y: number
  w: number
  h: number
}

function tileRect(value: unknown): TileRect | null {
  const tile = record(value)
  const [x, y, w, h] = [finite(tile.x), finite(tile.y), finite(tile.w), finite(tile.h)]
  return x !== null && y !== null && w !== null && h !== null && w > 0 && h > 0 ? { x, y, w, h } : null
}

/** The ground cells of a 3×3 tileset (``tiles.json``): the top edge ``t`` over the centre ``c``. */
export function tilesetCells(data: unknown): { top: TileRect; fill: TileRect } | null {
  const tiles = Array.isArray(record(data).tiles) ? record(data).tiles as unknown[] : []
  const named = new Map(tiles.map(item => [String(record(item).name || ''), tileRect(item)] as const))
  const fill = named.get('c') || named.get('t') || null
  const top = named.get('t') || fill
  return top && fill ? { top, fill } : null
}

/** The camera keeps the hero centred and never shows past the level edges. */
export function cameraFor(heroX: number, world = WORLD_WIDTH, view = PLAY_WIDTH): number {
  return Math.max(0, Math.min(world - view, heroX - view / 2))
}

const KEYS: Record<string, keyof PlayKeys> = {
  ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'jump', ' ': 'jump', Spacebar: 'jump', Shift: 'run', x: 'attack', X: 'attack',
}

/** Sets the control ``key`` maps to; ``false`` for a key the game does not use (it keeps its normal job). */
export function applyKey(keys: PlayKeys, key: string, down: boolean): boolean {
  const control = KEYS[key]
  if (!control) return false
  keys[control] = down
  return true
}

export function releaseKeys(keys: PlayKeys): void {
  keys.left = false
  keys.right = false
  keys.run = false
  keys.jump = false
  keys.attack = false
}

const FALLBACK: Record<string, string> = { run: 'walk', fall: 'jump' }

/** The action the hero shows, then the first one of its fallbacks that has a clip. */
export function heroAction(body: Body, keys: PlayKeys, attacking: boolean, has: (action: string) => boolean): string {
  let action = 'idle'
  if (attacking) action = 'attack'
  else if (!body.onGround) action = body.vy > 0 ? 'fall' : 'jump'
  else if (keys.left !== keys.right) action = keys.run ? 'run' : 'walk'
  while (!has(action) && FALLBACK[action]) action = FALLBACK[action]
  return action
}
