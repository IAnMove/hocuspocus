export const DARK_CUTOUT_MOTION_IDS = ['dark-motion-knight-passage', 'dark-motion-knight-embers'] as const
export const CREATIVE_CUTOUT_MOTION_IDS = ['creative-motion-skate-coast', 'creative-motion-skate-neon', 'creative-motion-skate-clouds', 'creative-motion-skate-portal'] as const
export function isCutoutMotionTemplate(id: string) {
  return [...DARK_CUTOUT_MOTION_IDS, ...CREATIVE_CUTOUT_MOTION_IDS].some(value => value === id)
}
