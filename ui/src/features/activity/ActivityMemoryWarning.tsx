import { useUiTranslation } from '../../i18n'

function paceDegraded(performance: unknown): boolean {
  if (performance == null || typeof performance !== 'object') return false
  return (performance as { degraded?: unknown }).degraded === true
}

export function ActivityMemoryWarning({ performance }: { performance: unknown }) {
  const { t } = useUiTranslation('activity')
  if (!paceDegraded(performance)) return null
  return (
    <span
      role="status"
      data-testid="activity-memory-warning"
      className="shrink-0 truncate text-amber-300"
      title={t('memoryDegraded')}
    >
      {t('memoryDegraded')}
    </span>
  )
}
