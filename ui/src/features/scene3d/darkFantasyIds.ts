export const DARK_FANTASY_IDS = [
  "dark-cathedral",
  "dark-forest",
  "dark-stairway",
  "dark-moonlake",
  "dark-portal",
  "dark-throne",
  "dark-library",
  "dark-ice",
  "dark-abyss",
  "dark-eclipse"
] as const

export function isDarkFantasyTemplate(id: string): id is typeof DARK_FANTASY_IDS[number] {
  return (DARK_FANTASY_IDS as readonly string[]).includes(id)
}
