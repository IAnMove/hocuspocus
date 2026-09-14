import scenes from './darkFantasyScenes.json'
import { DARK_FANTASY_IDS, isDarkFantasyTemplate } from './darkFantasyIds'
import type { Scene3DDocument, Scene3DSlotId } from './types'

export const DARK_FANTASY_TEMPLATES = DARK_FANTASY_IDS.map(id => ({
  id, camera: 'establishment' as const, duration: 6,
  slots: ['subject_1', 'background', 'prop'] as Scene3DSlotId[],
}))

export const DARK_FANTASY_CATEGORIES = Object.fromEntries(DARK_FANTASY_IDS.map(id => [id, 'cinema'])) as Record<typeof DARK_FANTASY_IDS[number], 'cinema'>

export function darkFantasyTemplateDocument(id: string): Scene3DDocument | null {
  return isDarkFantasyTemplate(id) ? structuredClone(scenes[id]) as unknown as Scene3DDocument : null
}
