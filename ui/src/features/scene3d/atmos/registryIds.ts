/** Typed ids. `types.ts` imports this file and must not import the set builders. */
export const ATMOS_SET_IDS = ['atmos-clearing', 'atmos-waterfall', 'atmos-moon', 'atmos-mars', 'atmos-snow', 'atmos-desert', 'atmos-beach', 'atmos-crystal-cave', 'atmos-temple'] as const
export type AtmosSetId = (typeof ATMOS_SET_IDS)[number]
export const ATMOS_TEMPLATE_IDS = [
  'atmos-clearing-wide', 'atmos-clearing-backlight',
  'atmos-waterfall-wide', 'atmos-waterfall-low',
  'atmos-moon-wide', 'atmos-moon-low',
  'atmos-mars-wide', 'atmos-mars-low',
  'atmos-snow-wide', 'atmos-snow-low',
  'atmos-desert-wide', 'atmos-desert-low',
  'atmos-beach-wide', 'atmos-beach-low',
  'atmos-crystal-cave-wide', 'atmos-crystal-cave-low',
  'atmos-temple-wide', 'atmos-temple-low',
] as const
export type AtmosTemplateId = (typeof ATMOS_TEMPLATE_IDS)[number]

const extraIds = new Set<string>()

export function bindAtmosExtra(id: string, present: boolean) {
  if (present) extraIds.add(id)
  else extraIds.delete(id)
}

export function isAtmosId(id: string | undefined): boolean {
  if (!id) return false
  return (ATMOS_SET_IDS as readonly string[]).includes(id) || extraIds.has(id)
}
