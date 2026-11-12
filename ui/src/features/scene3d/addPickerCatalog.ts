import { TEXT_TEMPLATES } from '../../lib/kineticText'
import { FX_CATALOG } from '../sceneFx/types'
import { WORLD_SFX_KINDS } from '../sceneFx/world'

export type AddPickerCategory = 'all' | 'world' | 'overlay' | 'demo' | 'text' | 'prop'

export type AddPickerAction =
  | { type: 'world'; kind: string }
  | { type: 'overlay'; kind: string }
  | { type: 'world-demo'; demo: 'depth' | 'duel' | 'mixed' }
  | { type: 'showcase'; showcase: 'all' | 'anime' | 'retro' }
  | { type: 'text'; templateId: string }

export type AddPickerItem = {
  id: string
  category: Exclude<AddPickerCategory, 'all' | 'prop'>
  labelNs: 'sceneFx' | 'kineticText'
  labelKey: string
  action: AddPickerAction
}

const DEMOS: AddPickerItem[] = [
  { id: 'world-demo:depth', category: 'demo', labelNs: 'sceneFx', labelKey: 'worldDemo.depth', action: { type: 'world-demo', demo: 'depth' } },
  { id: 'world-demo:duel', category: 'demo', labelNs: 'sceneFx', labelKey: 'worldDemo.duel', action: { type: 'world-demo', demo: 'duel' } },
  { id: 'world-demo:mixed', category: 'demo', labelNs: 'sceneFx', labelKey: 'worldDemo.mixed', action: { type: 'world-demo', demo: 'mixed' } },
  { id: 'showcase:all', category: 'demo', labelNs: 'sceneFx', labelKey: 'showcase', action: { type: 'showcase', showcase: 'all' } },
  { id: 'showcase:anime', category: 'demo', labelNs: 'sceneFx', labelKey: 'animeShowcase', action: { type: 'showcase', showcase: 'anime' } },
  { id: 'showcase:retro', category: 'demo', labelNs: 'sceneFx', labelKey: 'retroShowcase', action: { type: 'showcase', showcase: 'retro' } },
]

/** Every named effect, screen effect, demo and animated-text template the old buttons offered. */
export function addPickerCatalog(): AddPickerItem[] {
  const world = WORLD_SFX_KINDS.map((kind): AddPickerItem => ({
    id: `world:${kind}`,
    category: 'world',
    labelNs: 'sceneFx',
    labelKey: `presets.${kind}`,
    action: { type: 'world', kind },
  }))
  const overlay = FX_CATALOG.map((item): AddPickerItem => ({
    id: `overlay:${item.id}`,
    category: 'overlay',
    labelNs: 'sceneFx',
    labelKey: `presets.${item.id}`,
    action: { type: 'overlay', kind: item.id },
  }))
  const texts = TEXT_TEMPLATES.map((item): AddPickerItem => ({
    id: `text:${item.id}`,
    category: 'text',
    labelNs: 'kineticText',
    labelKey: item.labelKey,
    action: { type: 'text', templateId: item.id },
  }))
  return [...world, ...overlay, ...DEMOS, ...texts]
}

export function filterAddPickerItems(
  items: readonly AddPickerItem[],
  category: AddPickerCategory,
  query: string,
  labelOf: (item: AddPickerItem) => string,
): AddPickerItem[] {
  const needle = query.trim().toLowerCase()
  return items.filter(item => {
    if (category !== 'all' && item.category !== category) return false
    if (!needle) return true
    return labelOf(item).toLowerCase().includes(needle) || item.id.toLowerCase().includes(needle)
  })
}
