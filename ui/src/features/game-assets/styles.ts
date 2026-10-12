import type { Game, GameAsset, GameAttempt } from './types'

export const fieldClass = 'w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm'
export const buttonClass = 'rounded-md border border-border bg-card px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50'
export const panelClass = 'rounded-lg border border-border bg-bg-secondary p-3'
export const errorClass = 'text-sm text-red-500'

/** A tab or list button; the selected one keeps a visible border and weight. */
export function choiceClass(selected: boolean): string {
  const base = 'rounded-md border px-3 py-1.5 text-sm disabled:opacity-50'
  return selected ? `${base} border-accent-blue bg-muted font-medium` : `${base} border-border bg-card hover:bg-muted`
}

const HEX = /^#[0-9a-fA-F]{6}$/

export function isHexColor(value: string): boolean {
  return HEX.test(value.trim())
}

type Rgb = [number, number, number]

function channelRange(pixels: Rgb[]): { channel: 0 | 1 | 2; span: number } {
  let channel: 0 | 1 | 2 = 0
  let span = -1
  for (const index of [0, 1, 2] as const) {
    let low = 255
    let high = 0
    for (const pixel of pixels) {
      low = Math.min(low, pixel[index])
      high = Math.max(high, pixel[index])
    }
    if (high - low > span) {
      span = high - low
      channel = index
    }
  }
  return { channel, span }
}

function average(pixels: Rgb[]): Rgb {
  const total = pixels.reduce((sum, pixel) => [sum[0] + pixel[0], sum[1] + pixel[1], sum[2] + pixel[2]] as Rgb, [0, 0, 0])
  return total.map(value => Math.round(value / pixels.length)) as Rgb
}

function hex(pixel: Rgb): string {
  return `#${pixel.map(value => value.toString(16).padStart(2, '0')).join('')}`
}

/** Median cut over RGBA bytes. Alpha below 128 is ignored. */
export function colorsFromImageData(data: Uint8ClampedArray, count: number): string[] {
  const pixels: Rgb[] = []
  const step = Math.max(1, Math.floor(data.length / 4 / 4000))
  for (let index = 0; index < data.length; index += 4 * step) {
    if (data[index + 3] < 128) continue
    pixels.push([data[index], data[index + 1], data[index + 2]])
  }
  if (!pixels.length) return []
  const target = Math.max(1, Math.min(64, count || 8))
  let buckets = [pixels]
  while (buckets.length < target) {
    let chosen = -1
    let widest = 0
    buckets.forEach((bucket, index) => {
      const range = channelRange(bucket)
      if (bucket.length > 1 && range.span > widest) {
        widest = range.span
        chosen = index
      }
    })
    if (chosen < 0) break
    const bucket = buckets[chosen]
    const channel = channelRange(bucket).channel
    const sorted = [...bucket].sort((left, right) => left[channel] - right[channel])
    const mid = Math.max(1, Math.floor(sorted.length / 2))
    buckets = [...buckets.slice(0, chosen), ...buckets.slice(chosen + 1), sorted.slice(0, mid), sorted.slice(mid)]
  }
  return buckets.map(bucket => hex(average(bucket)))
}

const IMAGE = /\.(png|webp|jpe?g)$/i

/** The still of one attempt: ``preview`` or ``main`` first, else any image file. */
export function attemptImage(attempt: GameAttempt | undefined, workspace: string): string | null {
  const files = attempt?.files || {}
  const file = [files.preview, files.main, ...Object.values(files)].find(value => typeof value === 'string' && IMAGE.test(value))
  if (!file) return null
  const path = file.split('/').map(encodeURIComponent).join('/')
  return `/api/v1/file/${path}?workspace=${encodeURIComponent(workspace)}`
}

/** An attempt the user may still pick: it succeeded and nobody rejected it. */
export function usableAttempt(attempt: GameAttempt): boolean {
  return attempt.status === 'ok' && attempt.decision !== 'rejected'
}

export function assetImage(asset: GameAsset, workspace: string): string | null {
  const attempt = asset.attempts.find(item => item.id === asset.approvedAttemptId) || asset.attempts.find(usableAttempt)
  return attemptImage(attempt, workspace)
}

export function waitingApprovals(game: Game): { id: string; name: string; count: number }[] {
  const characters = new Map(game.assets.filter(asset => asset.kind === 'character').map(asset => [asset.id, asset]))
  const counts = new Map<string, number>()
  for (const asset of game.assets) {
    if (asset.kind === 'character') continue
    for (const dep of asset.dependsOn || []) {
      const character = characters.get(dep)
      if (character && character.status !== 'approved') counts.set(character.id, (counts.get(character.id) || 0) + 1)
    }
  }
  return [...counts].map(([id, count]) => ({ id, name: characters.get(id)?.name || id, count }))
}

export function slugFromName(name: string): string {
  const slug = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return slug || 'personaje'
}

/** The server's id limit (``MAX_ID``) and the folder names Windows refuses. */
export const MAX_ASSET_ID = 64
const RESERVED = new Set(['con', 'prn', 'aux', 'nul', ...[1, 2, 3, 4, 5, 6, 7, 8, 9].flatMap(n => [`com${n}`, `lpt${n}`])])

/** Cut at a hyphen when one falls inside the limit, like ``game_library._truncate``. */
export function truncateId(slug: string, limit = MAX_ASSET_ID): string {
  if (slug.length <= limit) return slug
  const head = slug.slice(0, limit + 1)
  const cut = head.includes('-') ? head.slice(0, head.lastIndexOf('-')) : slug.slice(0, limit)
  return cut.replace(/-+$/g, '') || slug.slice(0, limit)
}

/** A fresh asset id for a character name: slug, at most 64 characters, not reserved, not taken. */
export function newCharacterId(name: string, assets: GameAsset[]): string {
  const slug = truncateId(slugFromName(name))
  const wanted = RESERVED.has(slug) ? `${slug}-personaje` : slug
  const taken = new Set(assets.map(asset => asset.id))
  let candidate = wanted
  for (let suffix = 2; taken.has(candidate); suffix += 1) {
    const tail = `-${suffix}`
    candidate = `${wanted.slice(0, MAX_ASSET_ID - tail.length).replace(/-+$/g, '')}${tail}`
  }
  return candidate
}
