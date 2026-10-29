import { useUiTranslation } from '../../i18n'
import type { ModelLicence } from '../../lib/licenceNotice'

/** A short line and a link. Shown only when the licence names excluded territories. */
const TERRITORY_KEYS = {
  EU: 'licence.territories.EU',
  UK: 'licence.territories.UK',
  KR: 'licence.territories.KR',
  US: 'licence.territories.US',
} as const

export function LicenceNotice({ licence }: { licence?: ModelLicence | null }) {
  const { t, i18n } = useUiTranslation('common')
  const places = licence?.territoryExcluded ?? []
  if (!places.length || !licence?.url) return null
  const names = places.map(code => (
    code in TERRITORY_KEYS ? t(TERRITORY_KEYS[code as keyof typeof TERRITORY_KEYS]) : code
  ))
  const territories = new Intl.ListFormat(i18n.language, { type: 'conjunction' }).format(names)
  return (
    <p className="text-[10px] leading-snug text-text-muted" data-testid="licence-notice">
      {t('licence.territory', { territories })}{' '}
      <a href={licence.url} target="_blank" rel="noreferrer" className="underline hover:text-text-primary">
        {t('licence.link')}
      </a>
    </p>
  )
}
