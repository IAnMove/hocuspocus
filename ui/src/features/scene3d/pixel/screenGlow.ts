import { Color, PointLight, type Scene } from 'three'
import type { ScreenMediaRuntime } from '../screenMediaRuntime'
import type { Scene3DSlot } from '../types'

const POOL = 6
const lights = new WeakMap<Scene, PointLight[]>()
let sampler: CanvasRenderingContext2D | null | undefined

function pool(scene: Scene) {
  let list = lights.get(scene)
  if (!list) {
    list = Array.from({ length: POOL }, () => { const light = new PointLight(0xffffff, 0, 7, 1.6); scene.add(light); return light })
    lights.set(scene, list)
  }
  return list
}

/** One pixel per screen: the average colour of each picture, read back in
 *  a single call. */
function averageColors(canvases: HTMLCanvasElement[]) {
  if (sampler === undefined) {
    try { sampler = document.createElement('canvas').getContext('2d', { willReadFrequently: true }) } catch { sampler = null }
  }
  if (!sampler || !canvases.length) return []
  sampler.canvas.width = canvases.length; sampler.canvas.height = 1
  canvases.forEach((canvas, i) => sampler!.drawImage(canvas, i, 0, 1, 1))
  const data = sampler.getImageData(0, 0, canvases.length, 1).data
  return canvases.map((_, i) => new Color(data[i * 4] / 255, data[i * 4 + 1] / 255, data[i * 4 + 2] / 255))
}

type Lit = { slot: Scene3DSlot; screen: ScreenMediaRuntime & { canvas: HTMLCanvasElement } }

/** Screens light the room: neighbouring screens share one light placed in
 *  front of them, coloured by what they show right now. */
/** What the screens show, on average, and how strongly they shine: the
 *  painted world takes a tint of it. */
export type ScreenLight = { color: string; amount: number }

export function syncScreenGlow(scene: Scene, slots: readonly Scene3DSlot[], runtimes: (id: string) => ScreenMediaRuntime | undefined, strength: number): ScreenLight | undefined {
  // Scenes without screen light never pay for the extra lights.
  if (strength <= 0 && !lights.has(scene)) return undefined
  const list = pool(scene)
  const lit: Lit[] = []
  if (strength > 0) for (const slot of slots) {
    const screen = runtimes(slot.id)
    if (slot.screen && screen?.ready && screen.canvas) lit.push({ slot, screen: screen as Lit['screen'] })
  }
  lit.sort((a, b) => a.slot.position[0] - b.slot.position[0])
  const colors = averageColors(lit.map(item => item.screen.canvas))
  const groups = Math.min(POOL, lit.length)
  list.forEach((light, g) => {
    const members = groups ? lit.map((item, i) => ({ item, color: colors[i] })).filter((_, i) => Math.floor(i * groups / lit.length) === g) : []
    if (!members.length) { light.intensity = 0; return }
    const color = new Color(0, 0, 0), at = [0, 0, 0]
    for (const { item, color: sample } of members) {
      const { position, rotationY, scale } = item.slot, screen = item.slot.screen!
      color.add(sample)
      at[0] += position[0] + Math.sin(rotationY) * .9
      at[1] += position[1] + screen.height * scale * .7
      at[2] += position[2] + Math.cos(rotationY) * .9
    }
    color.multiplyScalar(1 / members.length)
    const brightness = Math.max(color.r, color.g, color.b)
    light.color.copy(brightness > 0 ? color.clone().multiplyScalar(1 / brightness) : color)
    light.position.set(at[0] / members.length, at[1] / members.length, at[2] / members.length)
    light.intensity = strength * brightness * 6 * Math.sqrt(members.length)
  })
  if (!colors.length) return undefined
  const mean = colors.reduce((sum, color) => sum.add(color), new Color(0, 0, 0)).multiplyScalar(1 / colors.length)
  return { color: '#' + mean.getHexString(), amount: strength * Math.max(mean.r, mean.g, mean.b) }
}
