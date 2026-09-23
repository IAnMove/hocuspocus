export const PIXEL_TEMPLATE_IDS = ['pixel-tv-wall', 'pixel-moon-lake', 'pixel-tv-lake', 'pixel-aurora-peaks'] as const
export type PixelTemplateId = typeof PIXEL_TEMPLATE_IDS[number]

export function isPixelTemplate(id: string): id is PixelTemplateId {
  return (PIXEL_TEMPLATE_IDS as readonly string[]).includes(id)
}
