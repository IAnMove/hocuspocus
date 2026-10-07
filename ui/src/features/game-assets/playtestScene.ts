import type { Game, GameAsset } from './types'
import { approvedAttempt, loopSamples, musicFile, playbackSources } from './reviewModel'

/** Spanish and English words for the actions the hero plays; the server stores the English id. */
const ACTIONS: Record<string, string> = {
  idle: 'idle', walk: 'walk', run: 'run', jump: 'jump', fall: 'fall', attack: 'attack',
  reposo: 'idle', andar: 'walk', caminar: 'walk', correr: 'run', saltar: 'jump', caer: 'fall', atacar: 'attack',
}

const SFX: Record<string, SfxTrigger> = {
  jump: 'jump', salto: 'jump', saltar: 'jump',
  coin: 'coin', moneda: 'coin', pickup: 'coin', recoger: 'coin',
  hit: 'hit', golpe: 'hit', attack: 'hit', ataque: 'hit', atacar: 'hit',
}

export const PLAY_WIDTH = 640
export const PLAY_HEIGHT = 360
export const GROUND_Y = 300
/** The level is three screens wide; the camera follows the hero. */
export const WORLD_WIDTH = PLAY_WIDTH * 3

/** The hero clips the playtest needs; ``fall`` is optional and falls back to ``jump``. */
export const HERO_ACTIONS = ['idle', 'walk', 'run', 'jump', 'attack'] as const
export const SFX_TRIGGERS = ['jump', 'coin', 'hit'] as const
export type SfxTrigger = typeof SFX_TRIGGERS[number]

export interface Body {
  x: number
  y: number
  vx: number
  vy: number
  onGround: boolean
}

export interface PlayInput {
  left: boolean
  right: boolean
  run: boolean
  jump: boolean
}

/** Where a sprite's pivot sits when its atlas gives none: feet for characters and items, centre for effects. */
export type Anchor = 'bottom' | 'center'

/** One approved image: a sheet with its atlas, or a still (``atlas`` empty). */
export interface PlaySprite {
  file: string
  atlas: string
  /** The frame tag to play; the first tag when the atlas has no such tag. */
  tag: string
  /** ``spec.loop`` (else the attempt metric); the atlas ``meta.loop`` wins when it has one. */
  loop: boolean
  anchor: Anchor
}

export interface PlayActor {
  id: string
  name: string
  sprite: PlaySprite | null
}

export interface PlayHero extends PlayActor {
  clips: Partial<Record<string, PlaySprite>>
}

export interface PlayLayer {
  file: string
  factor: number
}

/** A single tile, or a 3×3 tileset with its ``tiles.json``. */
export interface PlayGround {
  name: string
  file: string
  tiles: string
}

export interface PlayMusic {
  file: string
  loop: { start: number; end: number } | null
}

export type MissingCode = 'hero' | 'animation' | 'tile' | 'background' | 'music' | 'sfx'

export interface PlayMissing {
  code: MissingCode
  name: string
}

export interface PlayScene {
  hero: PlayHero | null
  enemies: PlayActor[]
  items: PlayActor[]
  ground: PlayGround | null
  layers: PlayLayer[]
  /** ``spec.loopX``: false means the layers were not seam-healed and must not wrap. */
  loopX: boolean
  vfx: (PlaySprite & { additive: boolean }) | null
  music: PlayMusic | null
  sfx: Record<SfxTrigger, string[]>
  missing: PlayMissing[]
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Approved assets that still have a usable approved attempt: exactly what the export packs. */
function approvedAssets(game: Game): GameAsset[] {
  return game.assets.filter(asset => asset.status === 'approved' && approvedAttempt(asset) !== null)
}

function filesOf(asset: GameAsset): Record<string, string> {
  return approvedAttempt(asset)?.files || {}
}

function loopOf(asset: GameAsset): boolean {
  const spec = asset.spec.loop
  if (typeof spec === 'boolean') return spec
  return approvedAttempt(asset)?.metrics?.loop === true
}

/** The approved sheet (with its atlas) or the approved ``main`` still; the 4× ``preview`` is a last resort. */
export function spriteOf(asset: GameAsset, anchor: Anchor, tag = ''): PlaySprite | null {
  const files = filesOf(asset)
  const sheet = files.sheet || files.main || ''
  if (files.atlas && sheet) return { file: sheet, atlas: files.atlas, tag, loop: loopOf(asset), anchor }
  const still = files.main || files.preview || ''
  return still ? { file: still, atlas: '', tag: '', loop: false, anchor } : null
}

function actor(asset: GameAsset, anchor: Anchor): PlayActor {
  return { id: asset.id, name: asset.name || asset.id, sprite: spriteOf(asset, anchor) }
}

function actionName(asset: GameAsset): string {
  const raw = String(asset.spec.action || '').toLowerCase()
  return ACTIONS[raw] || raw
}

function ownedBy(asset: GameAsset, id: string): boolean {
  return String(asset.spec.character || '') === id || asset.dependsOn.includes(id)
}

function role(asset: GameAsset): string {
  return text(asset.spec.role) || 'player' // the server defaults a character's role to player
}

export function integerScale(viewWidth: number): number {
  if (viewWidth < PLAY_WIDTH) return 1
  return Math.max(1, Math.min(4, Math.floor(viewWidth / PLAY_WIDTH)))
}

export function stepBody(body: Body, input: PlayInput, dt: number): Body {
  const step = Math.max(0, Math.min(0.05, dt))
  const speed = input.run ? 160 : 90
  let vx = 0
  if (input.left) vx -= speed
  if (input.right) vx += speed
  let vy = body.vy
  let onGround = body.onGround
  if (input.jump && onGround) {
    vy = -320
    onGround = false
  }
  vy += 980 * step
  let y = body.y + vy * step
  if (y >= GROUND_Y) {
    y = GROUND_Y
    vy = 0
    onGround = true
  }
  const x = Math.max(16, Math.min(WORLD_WIDTH - 16, body.x + vx * step))
  return { x, y, vx, vy, onGround }
}

function heroOf(assets: GameAsset[], missing: PlayMissing[]): PlayHero | null {
  const asset = assets.find(item => item.kind === 'character' && role(item) === 'player')
  if (!asset) {
    missing.push({ code: 'hero', name: '' })
    return null
  }
  const clips: Partial<Record<string, PlaySprite>> = {}
  for (const clip of assets) {
    if (clip.kind !== 'animation' || !ownedBy(clip, asset.id)) continue
    const action = actionName(clip)
    if (action && !clips[action]) clips[action] = spriteOf(clip, 'bottom', text(clip.spec.action)) || undefined
  }
  for (const action of HERO_ACTIONS) {
    if (!clips[action]) missing.push({ code: 'animation', name: action })
  }
  return { ...actor(asset, 'bottom'), clips }
}

function groundOf(assets: GameAsset[]): PlayGround | null {
  const tileset = assets.find(asset => asset.kind === 'tileset' && filesOf(asset).main && filesOf(asset).tiles)
  if (tileset) return { name: tileset.name || tileset.id, file: filesOf(tileset).main, tiles: filesOf(tileset).tiles }
  const tile = assets.find(asset => asset.kind === 'tile' && filesOf(asset).main)
  return tile ? { name: tile.name || tile.id, file: filesOf(tile).main, tiles: '' } : null
}

function layerRows(metrics: Record<string, unknown> | undefined): { file: string; factor: number }[] {
  const rows = metrics?.layers
  if (!Array.isArray(rows)) return []
  const found: { file: string; factor: number }[] = []
  for (const row of rows) {
    const entry = row && typeof row === 'object' ? row as { file?: unknown; factor?: unknown } : {}
    if (typeof entry.file === 'string' && typeof entry.factor === 'number') found.push({ file: entry.file, factor: entry.factor })
  }
  return found
}

/** Layers of the approved candidate, far (small factor) first; ``metrics.layers`` maps each file key to its factor. */
export function backgroundLayers(asset: GameAsset | undefined): PlayLayer[] {
  if (!asset) return []
  const attempt = approvedAttempt(asset)
  const files = attempt?.files || {}
  const factors = new Map(layerRows(attempt?.metrics).map(row => [row.file, row.factor]))
  const keys = Object.keys(files).filter(key => key.startsWith('layer')).sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
  const layers = keys.map((key, index) => ({ file: files[key], factor: factors.get(key) ?? (index === keys.length - 1 ? 1 : 0.1 + index * 0.25) }))
  if (!layers.length && files.main) layers.push({ file: files.main, factor: 0.1 })
  return layers.sort((left, right) => left.factor - right.factor)
}

function triggerOf(asset: GameAsset): SfxTrigger | null {
  const raw = `${text(asset.spec.trigger)} ${asset.name} ${asset.id}`.toLowerCase()
  for (const word of raw.split(/[^a-zñ]+/)) {
    if (SFX[word]) return SFX[word]
  }
  return null
}

function sfxMap(assets: GameAsset[]): Record<SfxTrigger, string[]> {
  const map: Record<SfxTrigger, string[]> = { jump: [], coin: [], hit: [] }
  for (const asset of assets) {
    const trigger = asset.kind === 'sfx' ? triggerOf(asset) : null
    if (!trigger || map[trigger].length) continue
    map[trigger] = playbackSources(filesOf(asset)).map(item => item.file)
  }
  return map
}

function musicOf(assets: GameAsset[]): PlayMusic | null {
  const asset = assets.find(item => item.kind === 'music' && musicFile(filesOf(item)))
  if (!asset) return null
  return { file: musicFile(filesOf(asset)), loop: loopSamples(approvedAttempt(asset)?.metrics) }
}

function vfxOf(assets: GameAsset[]): PlayScene['vfx'] {
  const asset = assets.find(item => item.kind === 'vfx')
  const sprite = asset ? spriteOf(asset, 'center') : null
  return asset && sprite ? { ...sprite, additive: asset.spec.blend !== 'alpha' } : null
}

export function playtestScene(game: Game): PlayScene {
  const assets = approvedAssets(game)
  const missing: PlayMissing[] = []
  const hero = heroOf(assets, missing)
  const ground = groundOf(assets)
  if (!ground) missing.push({ code: 'tile', name: '' })
  const background = assets.find(asset => asset.kind === 'background')
  const layers = backgroundLayers(background)
  if (!layers.length) missing.push({ code: 'background', name: '' })
  const music = musicOf(assets)
  if (!music) missing.push({ code: 'music', name: '' })
  const sfx = sfxMap(assets)
  for (const trigger of SFX_TRIGGERS) {
    if (!sfx[trigger].length) missing.push({ code: 'sfx', name: trigger })
  }
  return {
    hero,
    enemies: assets.filter(asset => asset.kind === 'character' && ['enemy', 'boss'].includes(role(asset))).map(asset => actor(asset, 'bottom')),
    items: assets.filter(asset => asset.kind === 'item').map(asset => actor(asset, 'bottom')),
    ground,
    layers,
    loopX: background?.spec.loopX !== false,
    vfx: vfxOf(assets),
    music,
    sfx,
    missing,
  }
}
