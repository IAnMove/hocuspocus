import { useUiTranslation } from '../../i18n'
import type { ModelLicence } from '../../lib/licenceNotice'

/** A short line and a link. Shown only when the licence names excluded territories. */
export function LicenceNotice({ licence }: { licence?: ModelLicence | null }) {
  const { t } = useUiTranslation('common')
  const places = licence?.territoryExcluded ?? []
  if (!places.length || !licence?.url) return null
  return (
    <p className="text-[10px] leading-snug text-text-muted" data-testid="licence-notice">
      {t('licence.territory', { territories: places.join(', ') })}{' '}
      <a href={licence.url} target="_blank" rel="noreferrer" className="underline hover:text-text-primary">
        {t('licence.link')}
      </a>
    </p>
  )
}
