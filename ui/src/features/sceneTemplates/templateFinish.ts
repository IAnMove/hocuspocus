import type { SceneLayer } from '../../types'
import type { TemplateFamily } from './catalog'

export const TEMPLATE_FINISH_VERSION = 2

/** A restrained, editable depth treatment for newly compiled scenes. It never
 * rewrites stored references, source artwork, timing, or subject identity. */
export function finishTemplateLayers(layers: SceneLayer[], family: TemplateFamily, intensity: number): SceneLayer[] {
  return layers.map(item => {
    if (item.type === 'camera') return item
    // Intensity scales the kind's own preset (half to one and a half times as many particles, a little smaller or
    // larger); a fixed 12-30 particles of size .4-.7 were invisible over a real plate.
    if (item.atmosphere) return { ...item, atmosphere: { ...item.atmosphere,
      density: Math.max(5, Math.round(item.atmosphere.density * (.5 + intensity))), size: item.atmosphere.size * (.8 + .4 * intensity) } }
    if (item.id === 'foreground') return { ...item, effects: { blur: 1.2, brightness: 0.85, ...item.effects } }
    if (['background', 'background-scroll'].includes(item.id)) {
      return { ...item, effects: { brightness: family === 'space' ? 0.9 : 0.94, saturation: 0.9, contrast: 1.04, ...item.effects } }
    }
    // Do not grade the actor's skin, costume, or a supplied product image.
    return { ...item, effects: { shadow: 0.22, ...item.effects } }
  })
}
