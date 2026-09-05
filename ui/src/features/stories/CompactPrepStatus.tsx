import { useUiTranslation } from '../../i18n'

export function CompactPrepStatus({ ready, approved }: { ready: boolean; approved: boolean }) {
  const { t } = useUiTranslation('storyLab')
  return (
    <span className={`rounded-full border px-2 py-1 text-[9px] ${ready
      ? approved ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      : 'border-border bg-bg-tertiary text-text-muted'}`}>
      {ready ? approved ? t('status.approved') : t('compact.readyToApprove') : t('compact.pending')}
    </span>
  )
}
