import { controlReason } from '../../i18n/controlLabel'
import { useUiTranslation } from '../../i18n'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed'

/** Disabled, with the same reason the creator shows as an error, until a subject image exists. */
export function FaceRigOpenButton({ hasSubject, busy, onClick }: { hasSubject: boolean; busy: boolean; onClick: () => void }) {
  const { t } = useUiTranslation('characters')
  const reason = !hasSubject
    ? t('creator.errors.needViewOrUpload')
    : controlReason(busy, 'disabled.actionInProgress')
  return (
    <button type="button" className={`${button} mt-2`} disabled={busy || !hasSubject} title={reason} onClick={onClick}>
      {t('creator.openFaceRig')}
    </button>
  )
}
