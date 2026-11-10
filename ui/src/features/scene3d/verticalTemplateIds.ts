/** Cards drawn for a 9:16 frame: two or three people talking, and one person talking to camera.
 * `types.ts` imports this file and must not import the builders. */
export const VERTICAL_DIALOGUE_IDS = [
  'vertical-dialogue-stack',
  'vertical-dialogue-ots-a',
  'vertical-dialogue-ots-b',
  'vertical-dialogue-single-a',
  'vertical-dialogue-single-b',
  'vertical-dialogue-walk',
  'vertical-dialogue-seated',
  'vertical-dialogue-trio',
  'vertical-dialogue-listener',
  'vertical-dialogue-low',
  'vertical-dialogue-high',
  'vertical-dialogue-locked',
] as const

export const VERTICAL_TALK_IDS = [
  'vertical-talk-bust',
  'vertical-talk-caption',
  'vertical-talk-three-quarter',
  'vertical-talk-low',
  'vertical-talk-push',
  'vertical-talk-side',
] as const

export const VERTICAL_TEMPLATE_IDS = [...VERTICAL_DIALOGUE_IDS, ...VERTICAL_TALK_IDS] as const

export type VerticalDialogueId = typeof VERTICAL_DIALOGUE_IDS[number]
export type VerticalTalkId = typeof VERTICAL_TALK_IDS[number]
export type VerticalTemplateId = typeof VERTICAL_TEMPLATE_IDS[number]
