export const CREATIVE_TEMPLATE_IDS = [
  "creative-neon-diner",
  "creative-sun-orchard",
  "creative-vermilion-museum",
  "creative-cobalt-moon",
  "creative-coral-caravan",
  "creative-emerald-hotel",
  "creative-mint-pool",
  "creative-indigo-shrine",
  "creative-ocean-window",
  "creative-velvet-theatre",
  "creative-ochre-terminal",
  "creative-ceramic-room",
  "creative-tangerine-market",
  "creative-botanical-hangar",
  "creative-ink-mountain",
  "creative-submerged-archive",
  "creative-sunset-court",
  "creative-kinetic-gold",
  "creative-lunar-garden",
  "creative-peach-laundry"
] as const

export function isCreativeTemplate(id: string): id is typeof CREATIVE_TEMPLATE_IDS[number] {
  return (CREATIVE_TEMPLATE_IDS as readonly string[]).includes(id)
}
