import type { SceneLayer } from '../../types'
import type { TemplateFamily } from './catalog'

export const TEMPLATE_FINISH_VERSION = 1

/** A restrained, editable depth treatment for newly compiled scenes. It never
 * rewrites stored references, source artwork, timing, or subject identity. */
export function finishTemplateLayers(layers: SceneLayer[], family: TemplateFamily, intensity: number): SceneLayer[] {
  return layers.map(item => {
    if (item.type === 'camera') return item
    if (item.atmosphere) return { ...item, atmosphere: { ...item.atmosphere, density: Math.round(12 + 18 * intensity), size: 0.4 + 0.3 * intensity } }
    if (item.id === 'foreground') return { ...item, effects: { blur: 1.2, brightness: 0.85, ...item.effects } }
    if (['background', 'background-scroll'].includes(item.id)) {
      return { ...item, effects: { brightness: family === 'space' ? 0.9 : 0.94, saturation: 0.9, contrast: 1.04, ...item.effects } }
    }
    // Do not grade the actor's skin, costume, or a supplied product image.
    return { ...item, effects: { shadow: 0.22, ...item.effects } }
  })
}
