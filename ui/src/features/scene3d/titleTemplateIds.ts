/** Kinetic title cards. `types.ts` imports this file and must not import the builders. */
export const TITLE_TEMPLATE_IDS = [
  'title-lower-third',
  'title-kinetic-stage',
  'title-chapter',
  'title-end-card',
] as const

export type TitleTemplateId = typeof TITLE_TEMPLATE_IDS[number]
