export const PIXEL_TEMPLATE_IDS = ['pixel-tv-wall', 'pixel-moon-lake', 'pixel-tv-lake', 'pixel-aurora-peaks', 'pixel-neon-city', 'pixel-desert-sun', 'pixel-lighthouse', 'pixel-firefly-forest', 'pixel-planet-rise', 'pixel-night-train', 'pixel-storm-lake', 'pixel-volcano', 'pixel-drive-in', 'pixel-cherry-garden', 'pixel-coral-reef', 'pixel-balloons', 'pixel-night-fair', 'pixel-snow-village', 'pixel-waterfall', 'pixel-orbit', 'pixel-tulip-fields', 'pixel-neon-alley', 'pixel-castle-fireworks', 'pixel-glow-tide', 'pixel-lantern-festival', 'pixel-rainy-window', 'pixel-night-express', 'pixel-whole-day', 'pixel-eclipse', 'pixel-four-seasons', 'pixel-cathedral', 'pixel-koi-pond', 'pixel-moon-caravan', 'pixel-synthwave', 'pixel-monsoon', 'pixel-murmuration', 'pixel-night-launch', 'pixel-crystal-cave', 'pixel-starry-night', 'pixel-mist-rising', 'pixel-roadside-motel', 'pixel-tidal-abbey', 'pixel-mirage', 'pixel-cloud-shadows', 'pixel-fjord', 'pixel-clockwork', 'pixel-orrery'] as const
export type PixelTemplateId = typeof PIXEL_TEMPLATE_IDS[number]

export function isPixelTemplate(id: string): id is PixelTemplateId {
  return (PIXEL_TEMPLATE_IDS as readonly string[]).includes(id)
}
