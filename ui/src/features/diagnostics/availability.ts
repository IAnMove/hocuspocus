import type { AvailabilityItem } from './types.ts'

export function formatVersion(item: AvailabilityItem): string {
  return item.version.recipe || item.version.app || 'n/a'
}

export function explainAvailability(item: AvailabilityItem): string {
  const state = item.available ? 'available' : 'unavailable'
  const repair = item.repair_path ? item.repair_path.summary : 'No repair is required.'
  return [
    `${item.kind} ${item.id} is ${state}.`,
    `component=${item.component}`,
    `driver=${item.driver ?? 'unverified'}`,
    `backend=${item.backend}`,
    `ram_gb_observed=${item.ram_gb_observed ?? 'n/a'}`,
    `vram_gb_observed=${item.vram_gb_observed ?? 'n/a'}`,
    `version=${formatVersion(item)}`,
    `repair_path=${item.repair_path?.id ?? 'none'}`,
    ...item.reasons,
    repair,
  ].join('\n')
}

export function operationsOf(items: AvailabilityItem[]): AvailabilityItem[] {
  return items.filter(item => item.kind === 'operation')
}

export function modelsOf(items: AvailabilityItem[]): AvailabilityItem[] {
  return items.filter(item => item.kind === 'model')
}
