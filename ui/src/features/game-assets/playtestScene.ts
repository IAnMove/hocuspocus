import type { Game, GameAsset } from './types'
import { chosenAttempt, playbackSources, stillFile } from './reviewModel'

const ACTIONS: Record<string, string> = {
  idle: 'idle', walk: 'walk', run: 'run', jump: 'jump', attack: 'attack',
  andar: 'walk', correr: 'run', saltar: 'jump', atacar: 'attack',
}

const SFX: Record<string, string> = {
  jump: 'jump', salto: 'jump', coin: 'coin', moneda: 'coin', hit: 'hit', golpe: 'hit',
}

export const PLAY_WIDTH = 640
export const PLAY_HEIGHT = 360
export const GROUND_Y = 300

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

export interface PlayActor {
  id: string
  name: string
  file: string
}

export interface PlayScene {
  hero: { id: string; name: string; still: string; sheets: Record<string, string> } | null
  enemies: PlayActor[]
  tiles: PlayActor[]
  layers: { file: string; factor: number }[]
  items: PlayActor[]
  music: string | null
  sfxByTrigger: Record<string, string>
  missing: string[]
}

function approved(game: Game): GameAsset[] {
  return game.assets.filter(asset => asset.status === 'approved')
}

function fileOf(asset: GameAsset): string {
  const attempt = chosenAttempt(asset)
  return attempt ? stillFile(attempt.files || {}) : ''
}

function actionName(asset: GameAsset): string {
  const raw = String(asset.spec.action || asset.name || asset.id || '').toLowerCase()
  return ACTIONS[raw] || raw
}

function ownedBy(asset: GameAsset, id: string): boolean {
  return asset.dependsOn.includes(id) || String(asset.spec.character || '') === id
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
  return { x: body.x + vx * step, y, vx, vy, onGround }
}

export function playtestScene(game: Game): PlayScene {
  const assets = approved(game)
  const missing: string[] = []
  const heroAsset = assets.find(asset => asset.kind === 'character' && String(asset.spec.role || '') === 'player') || null
  if (!heroAsset) missing.push('hero')
  const sheets: Record<string, string> = {}
  if (heroAsset) {
    for (const name of ['idle', 'walk', 'run', 'jump', 'attack']) {
      const clip = assets.find(asset => asset.kind === 'animation' && ownedBy(asset, heroAsset.id) && actionName(asset) === name)
      if (clip) sheets[name] = fileOf(clip)
      else missing.push(name)
    }
  }
  const enemies = assets
    .filter(asset => asset.kind === 'character' && asset !== heroAsset)
    .map(asset => ({ id: asset.id, name: asset.name || asset.id, file: fileOf(asset) }))
  const tileset = assets.find(asset => asset.kind === 'tileset')
  const tiles = (tileset ? [tileset] : assets.filter(asset => asset.kind === 'tile'))
    .map(asset => ({ id: asset.id, name: asset.name || asset.id, file: fileOf(asset) }))
  if (!tiles.length) missing.push('tile')
  const background = assets.find(asset => asset.kind === 'background')
  const layers = backgroundLayers(background)
  if (!layers.length) missing.push('background')
  const musicAsset = assets.find(asset => asset.kind === 'music')
  if (!musicAsset) missing.push('music')
  const sfxByTrigger = sfxMap(assets)
  for (const trigger of ['jump', 'coin', 'hit']) {
    if (!sfxByTrigger[trigger]) missing.push(`sfx:${trigger}`)
  }
  const items = assets.filter(asset => asset.kind === 'item').map(asset => ({ id: asset.id, name: asset.name || asset.id, file: fileOf(asset) }))
  return {
    hero: heroAsset ? { id: heroAsset.id, name: heroAsset.name || heroAsset.id, still: fileOf(heroAsset), sheets } : null,
    enemies,
    tiles,
    layers,
    items,
    music: musicAsset ? audioFile(musicAsset) : null,
    sfxByTrigger,
    missing,
  }
}

function backgroundLayers(asset: GameAsset | undefined): { file: string; factor: number }[] {
  if (!asset) return []
  const attempt = chosenAttempt(asset)
  const files = attempt?.files || {}
  const factors = layerFactors(attempt?.metrics)
  const layers = Object.entries(files).filter(([key]) => key.startsWith('layer'))
  if (layers.length) {
    return layers.map(([key, file], index) => ({ file, factor: factors[key] ?? fallbackFactor(index) }))
  }
  const still = fileOf(asset)
  return still ? [{ file: still, factor: fallbackFactor(0) }] : []
}

function fallbackFactor(index: number): number {
  return 0.15 + index * 0.2
}

function layerFactors(metrics: Record<string, unknown> | undefined): Record<string, number> {
  const layers = metrics?.layers
  const factors: Record<string, number> = {}
  if (!Array.isArray(layers)) return factors
  for (const layer of layers) {
    if (!layer || typeof layer !== 'object') continue
    const row = layer as { file?: unknown; factor?: unknown }
    if (typeof row.file === 'string' && typeof row.factor === 'number') factors[row.file] = row.factor
  }
  return factors
}

function audioFile(asset: GameAsset): string {
  const attempt = chosenAttempt(asset)
  return playbackSources(attempt?.files || {})[0]?.file || ''
}

function sfxMap(assets: GameAsset[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const asset of assets) {
    if (asset.kind !== 'sfx') continue
    const raw = String(asset.spec.trigger || asset.name || asset.id || '').toLowerCase()
    const trigger = SFX[raw]
    if (!trigger || map[trigger]) continue
    const file = audioFile(asset)
    if (file) map[trigger] = file
  }
  for (const trigger of ['jump', 'coin', 'hit']) {
    if (!map[trigger]) map[trigger] = ''
  }
  return map
}
