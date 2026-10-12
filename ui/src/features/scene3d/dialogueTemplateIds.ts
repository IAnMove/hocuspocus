/** Two-figure dialogue shots. `types.ts` imports this file and must not import the builders. */
export const DIALOGUE_TEMPLATE_IDS = [
  'dialogue-ots-a',
  'dialogue-ots-b',
  'dialogue-table',
  'dialogue-triangle',
  'dialogue-embrace',
  'dialogue-phone-split',
] as const

export type DialogueTemplateId = typeof DIALOGUE_TEMPLATE_IDS[number]
