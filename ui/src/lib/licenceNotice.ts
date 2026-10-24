import type { ModelLicence } from '../types'

export type { ModelLicence }

/** English line the Wizard repeats when it offers a restricted model. The screen uses the same words from i18n. */
export function licenceNoticeLine(licence: ModelLicence | null | undefined): string {
  const places = licence?.territoryExcluded ?? []
  if (!places.length || !licence?.url) return ''
  return `This license does not apply in ${places.join(', ')}. ${licence.url}`
}

export function withLicenceNotice<T extends { family?: string }>(
  row: T,
  families: Array<{ id: string; licence?: ModelLicence | null }>,
): T & { licence_notice?: string } {
  const line = licenceNoticeLine(families.find(family => family.id === row.family)?.licence)
  return line ? { ...row, licence_notice: line } : row
}
