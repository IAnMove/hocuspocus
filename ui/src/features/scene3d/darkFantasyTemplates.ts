import scenes from './darkFantasyScenes.json' with { type: 'json' }
import { DARK_FANTASY_IDS, isDarkFantasyTemplate } from './darkFantasyIds'
import type { Scene3DDocument, Scene3DSlotId } from './types'
import type { Scene3DTemplate } from './templates'
import { parseScene3DDocument } from './document'

export const DARK_FANTASY_TEMPLATES: Scene3DTemplate[] = DARK_FANTASY_IDS.map(id => ({
  id, camera: 'establishment' as const, duration: 6,
  slots: ['subject_1', 'background', 'prop'] as Scene3DSlotId[],
  tags: id.startsWith('dark-psx-') ? ['dark-fantasy', 'psx'] : ['dark-fantasy'],
  frameFormat: scenes[id].height > scenes[id].width ? 'portrait' : 'landscape',
}))

export const DARK_FANTASY_CATEGORIES = Object.fromEntries(DARK_FANTASY_IDS.map(id => [id, 'cinema'])) as Record<typeof DARK_FANTASY_IDS[number], 'cinema'>

export function darkFantasyTemplateDocument(id: string): Scene3DDocument | null {
  return isDarkFantasyTemplate(id) ? parseScene3DDocument(structuredClone(scenes[id])) : null
}
