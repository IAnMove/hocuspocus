import { applyScene3DTemplate, SCENE3D_TEMPLATES, type Scene3DTemplateId } from './templates'

/** Reviewed example families only: the first member represents the composition.
 * Keep every other template by default, including all Pixel worlds, PSX editions,
 * perspectives, portals, effects, speech, screens and procedural environments.
 * Differences in media, palette and small framing adjustments remain selectable
 * as variants; these groups never remove saved template IDs or change documents.
 */
export const TEMPLATE_VARIANT_GROUPS = [
  // Layered moving landscape with one hero and foreground prop.
  [
    'dark-living-sleeping-titan',
    'dark-living-bell-of-ash',
    'dark-living-antler-moon',
    'dark-living-drowned-king',
    'dark-living-red-pilgrim',
    'dark-living-last-aqueduct',
    'dark-living-ember-heart',
    'dark-living-violet-oracle',
    'dark-living-winter-shoulder',
    'dark-living-thorn-crown',
    'dark-living-black-tide',
    'dark-living-golden-ruin',
    'dark-living-hollow-saint',
    'dark-living-fungal-throne',
    'dark-living-storm-bridge',
    'dark-living-sand-library',
    'dark-living-jade-dragon',
    'dark-living-moon-grave',
    'dark-living-copper-trees',
    'dark-living-final-gate',
  ],
  // Fixed camera, one hero, foreground prop and moving exterior. Keep two-distances and time-wounds separate.
  [
    'dark-still-salt-sea',
    'dark-still-still-flame',
    'dark-still-winter-vigil',
    'dark-still-moth-moon',
    'dark-still-ivory-fire',
    'dark-still-copper-night',
  ],
  // Basic vertical cutout stage: hero and one foreground prop. Perspectives stay separate.
  [
    'creative-neon-diner',
    'creative-vermilion-museum',
    'creative-cobalt-moon',
    'creative-mint-pool',
    'creative-indigo-shrine',
    'creative-ochre-terminal',
    'creative-ceramic-room',
    'creative-tangerine-market',
    'creative-ink-mountain',
    'creative-submerged-archive',
    'creative-sunset-court',
    'creative-lunar-garden',
    'creative-peach-laundry',
  ],
  // Vertical cutout stage with foreground and distant props.
  [
    'creative-sun-orchard',
    'creative-emerald-hotel',
    'creative-velvet-theatre',
  ],
  // Vertical cutout stage with two props and a companion.
  [
    'creative-botanical-hangar',
    'creative-kinetic-gold',
  ],
  // Moving exterior with one hero and foreground prop.
  [
    'creative-scarlet-tide-motion',
    'creative-glass-orchard-motion',
  ],
  // Moving exterior with an additional companion.
  [
    'creative-rose-orbit-motion',
    'creative-amber-ice-motion',
    'creative-coral-radio-motion',
    'creative-cobalt-crater-motion',
  ],
  // Two independent videos: moving background and transparent skating character. Keep portals separate.
  [
    'creative-motion-skate-coast',
    'creative-motion-skate-neon',
    'creative-motion-skate-clouds',
  ],
 ] as const satisfies readonly (readonly Scene3DTemplateId[])[]
const variants = new Set<Scene3DTemplateId>(TEMPLATE_VARIANT_GROUPS.flatMap(group => group.slice(1)))
export const CORE_TEMPLATES = SCENE3D_TEMPLATES.filter(item => !variants.has(item.id))
export const CORE_TEMPLATE_IDS = CORE_TEMPLATES.map(item => item.id)
export function isCoreTemplate(id: Scene3DTemplateId) { return !variants.has(id) }

/** Recurses through screens, soundtracks, face packs, effects and saved references. */
export function exampleCollections(value: unknown): string[] {
  const names = new Set<string>()
  const visit = (item: unknown) => {
    if (typeof item === 'string' && item.startsWith('/examples/')) {
      const path = item.slice('/examples/'.length).split(/[?#]/)[0]
      names.add(path.includes('/') ? path.split('/')[0] : 'common')
    } else if (Array.isArray(item)) item.forEach(visit)
    else if (item && typeof item === 'object') Object.values(item).forEach(visit)
  }
  visit(value)
  return [...names].sort()
}
const requirements = new Map<Scene3DTemplateId, string[]>()
export function templateCollections(id: Scene3DTemplateId): string[] {
  if (!requirements.has(id)) requirements.set(id, exampleCollections(applyScene3DTemplate(id)))
  return requirements.get(id)!
}

const builtin = new Map<string, boolean>()
/** False for ids the editor cannot build, such as a workspace template (``user-…``) an agent instantiated. */
export function isBuiltinScene3DTemplate(id: string): boolean {
  if (!builtin.has(id)) {
    try { applyScene3DTemplate(id as Scene3DTemplateId); builtin.set(id, true) } catch { builtin.set(id, false) }
  }
  return builtin.get(id)!
}

/** Preview the composition without loading portal media, face packs or decals. */
export function previewTemplateDocument(id: Scene3DTemplateId) {
  const doc = applyScene3DTemplate(id)
  return { ...doc,
    slots: doc.slots.map(slot => ({ ...slot, speech: undefined, appearance: undefined, screen: undefined })),
    worldSfx: doc.worldSfx?.map(effect => ({ ...effect, sourceUrl: undefined })),
  }
}
