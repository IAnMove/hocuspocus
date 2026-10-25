/** Chapter-change shots. `types.ts` imports this file and must not import the builders.
 * Portrait is its own pair: the generic portrait adapter scales fov and offsets and would miss the panel. */
export const COMIC_TEMPLATE_IDS = [
  'comic-panel-exit',
  'comic-panel-enter',
  'comic-panel-exit-portrait',
  'comic-panel-enter-portrait',
] as const

export type ComicTemplateId = typeof COMIC_TEMPLATE_IDS[number]
