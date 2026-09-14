import scenes from './creativeScenes.json' with { type: 'json' }
import { CREATIVE_TEMPLATE_IDS, isCreativeTemplate } from './creativeTemplateIds'
import { parseScene3DDocument } from './document'
import type { Scene3DTemplate } from './templates'

export const CREATIVE_TEMPLATES: Scene3DTemplate[] = CREATIVE_TEMPLATE_IDS.map(id => ({
  id, camera: 'establishment', duration: 6, slots: ['subject_1', 'background', 'prop'],
  tags: ['creative', 'psx'], frameFormat: 'portrait',
}))
export const CREATIVE_CATEGORIES = Object.fromEntries(CREATIVE_TEMPLATE_IDS.map(id => [id, 'cinema'])) as Record<typeof CREATIVE_TEMPLATE_IDS[number], 'cinema'>

export function creativeTemplateDocument(id: string) {
  return isCreativeTemplate(id) ? parseScene3DDocument(structuredClone(scenes[id])) : null
}
