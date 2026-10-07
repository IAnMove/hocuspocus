import type { Game, GameAsset } from './types'

export const fieldClass = 'w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm'
export const buttonClass = 'rounded-md border border-border bg-card px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50'
export const panelClass = 'rounded-lg border border-border bg-bg-secondary p-3'

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

export function assetImage(asset: GameAsset, workspace: string): string | null {
  const attempt = asset.attempts.find(item => item.id === asset.approvedAttemptId)
    || asset.attempts.find(item => item.status === 'ok' && item.decision !== 'rejected')
  const file = Object.values(attempt?.files || {}).find(value => typeof value === 'string' && /\.(png|webp|jpe?g)$/i.test(value))
  if (!file) return null
  const path = file.split('/').map(encodeURIComponent).join('/')
  return `/api/v1/file/${path}?workspace=${encodeURIComponent(workspace)}`
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
  const slug = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return slug || 'personaje'
}
