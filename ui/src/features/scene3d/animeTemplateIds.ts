/** Classic TV-anime shots. `types.ts` imports this file and must not import the builders. */
export const ANIME_TEMPLATE_IDS = [
  'anime-speedline-charge',
  'anime-impact-frame',
  'anime-snap-zoom',
  'anime-sword-clash',
  'anime-face-off',
  'anime-airship-flyby',
  'anime-fleet-approach',
  'anime-eyecatch',
] as const

export type AnimeTemplateId = typeof ANIME_TEMPLATE_IDS[number]
