import { applyScene3DTemplate, SCENE3D_TEMPLATES, type Scene3DTemplateId } from './templates'

/** One entry per reusable shot purpose. Authored looks remain in Examples. */
export const CORE_TEMPLATE_IDS = [
  'two-shot', 'over-shoulder', 'hero-push', 'portrait-arc', 'tracking', 'crane-reveal',
  'establishing', 'high-angle', 'face-closeup', 'face-profile', 'boots-to-face', 'overhead-formation',
  'product-orbit', 'product-detail', 'product-pair', 'product-pedestal',
  'run-loop', 'dance-orbit', 'space-float', 'drive-chase', 'drive-hood', 'drive-wing',
  'speech-dialogue', 'monitor-reveal', 'screen-gallery', 'screen-corridor', 'control-room',
  'sea-deck', 'jungle-ambush', 'spell-duel', 'clone-chase', 'pixel-moon-lake',
] as const satisfies readonly Scene3DTemplateId[]
const core = new Set<Scene3DTemplateId>(CORE_TEMPLATE_IDS)
export const CORE_TEMPLATES = SCENE3D_TEMPLATES.filter(item => core.has(item.id))
export function isCoreTemplate(id: Scene3DTemplateId) { return core.has(id) }

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

/** Preview the composition without loading portal media, face packs or decals. */
export function previewTemplateDocument(id: Scene3DTemplateId) {
  const doc = applyScene3DTemplate(id)
  return { ...doc,
    slots: doc.slots.map(slot => ({ ...slot, speech: undefined, appearance: undefined, screen: undefined })),
    worldSfx: doc.worldSfx?.map(effect => ({ ...effect, sourceUrl: undefined })),
  }
}
