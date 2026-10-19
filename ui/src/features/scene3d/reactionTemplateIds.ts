/** One-figure reaction shots on the face. `types.ts` imports this file and must not import the builders. */
export const REACTION_TEMPLATE_IDS = [
  'reaction-push-face',
  'reaction-orbit-face',
  'reaction-turn-to-camera',
  'reaction-look-up',
  'reaction-impact',
] as const

export type ReactionTemplateId = typeof REACTION_TEMPLATE_IDS[number]
