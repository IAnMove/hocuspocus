/** Group blockings with person props and a crowd. `types.ts` imports this file and must not import the builders. */
export const GROUP_TEMPLATE_IDS = [
  'group-arc-five',
  'group-line-four',
  'group-audience',
  'group-circle',
] as const

export type GroupTemplateId = typeof GROUP_TEMPLATE_IDS[number]
