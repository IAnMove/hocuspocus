import type { ModelLicence } from '../types'

export type { ModelLicence }

type LicenceFamily = {
  id: string
  licence?: ModelLicence | null
  licenceRecords?: ModelLicence[] | null
}

/** English line the Wizard repeats when it offers a restricted model. The screen uses the same words from i18n. */
export function licenceNoticeLine(licence: ModelLicence | null | undefined): string {
  const places = licence?.territoryExcluded ?? []
  if (!places.length || !licence?.url) return ''
  return `This license does not apply in ${places.join(', ')}. ${licence.url}`
}

/** The record for this model. A mixed family does not lend its neighbour's licence. */
export function licenceForModel(
  model: { family?: string; licenceId?: string } | null | undefined,
  families: LicenceFamily[],
): ModelLicence | null {
  const family = families.find(item => item.id === model?.family)
  if (!family) return null
  if (model?.licenceId) {
    if (family.licence?.id === model.licenceId) return family.licence
    return family.licenceRecords?.find(record => record.id === model.licenceId) ?? null
  }
  return family.licence ?? null
}

export function withLicenceNotice<T extends { family?: string; licenceId?: string }>(
  row: T,
  families: LicenceFamily[],
): Omit<T, 'licenceId'> & { licence_notice?: string } {
  const line = licenceNoticeLine(licenceForModel(row, families))
  const rest = { ...row }
  delete rest.licenceId
  return line ? { ...rest, licence_notice: line } : rest
}
