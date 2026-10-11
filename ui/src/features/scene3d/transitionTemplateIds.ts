/** Cut pieces of 3 s or less. `types.ts` imports this file and must not import the builders. */
export const TRANSITION_TEMPLATE_IDS = [
  'transition-whip-pan',
  'transition-iris-in',
  'transition-flash-white',
  'transition-wipe-prop',
  'transition-match-shape',
  'transition-eyecatch',
  'transition-smash-in',
  'transition-rise-off',
] as const

export type TransitionTemplateId = typeof TRANSITION_TEMPLATE_IDS[number]
