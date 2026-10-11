/** Speed beats for GLB casts. `types.ts` imports this file and must not import the builders. */
export const SPEED_TEMPLATE_IDS = [
  'speed-run-toward',
  'speed-foot-chase',
  'speed-flyby',
  'speed-rush-lines',
  'speed-side-dash',
] as const

export type SpeedTemplateId = typeof SPEED_TEMPLATE_IDS[number]
