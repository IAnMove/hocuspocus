import { DARK_LIVING_IDS } from './darkLivingIds'
import { DARK_STILLNESS_IDS } from './darkStillnessIds'

export const DARK_FANTASY_IDS = [
  ...DARK_STILLNESS_IDS,
  ...DARK_LIVING_IDS,
  "dark-cathedral",
  "dark-forest",
  "dark-stairway",
  "dark-moonlake",
  "dark-portal",
  "dark-throne",
  "dark-library",
  "dark-ice",
  "dark-abyss",
  "dark-eclipse",
  "dark-vertical-ivory-gate",
  "dark-vertical-saffron-well",
  "dark-vertical-crimson-tide",
  "dark-vertical-frozen-bell",
  "dark-vertical-bone-stair",
  "dark-vertical-jade-rift",
  "dark-vertical-ashen-rose",
  "dark-vertical-violet-gravity",
  "dark-vertical-ember-totem",
  "dark-vertical-white-abyss",
  "dark-psx-ivory-gate",
  "dark-psx-saffron-well",
  "dark-psx-crimson-tide",
  "dark-psx-frozen-bell",
  "dark-psx-bone-stair",
  "dark-psx-jade-rift",
  "dark-psx-ashen-rose",
  "dark-psx-violet-gravity",
  "dark-psx-ember-totem",
  "dark-psx-white-abyss"
] as const

export function isDarkFantasyTemplate(id: string): id is typeof DARK_FANTASY_IDS[number] {
  return (DARK_FANTASY_IDS as readonly string[]).includes(id)
}
