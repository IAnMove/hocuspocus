import { openSharedShots } from './openShots'
import { reviewDetail } from './target'

export function ReviewShotsButton({
  workspace, productionId, label, disabledReason, className,
}: {
  workspace: string
  productionId: string
  label: string
  disabledReason?: string
  className?: string
}) {
  const detail = reviewDetail(workspace, productionId)
  return <button
    type="button"
    className={className || 'rounded border border-border px-2 py-1 text-xs'}
    data-review-shots={detail?.productionId || ''}
    data-workspace={detail?.workspace || ''}
    disabled={!detail}
    onClick={() => openSharedShots(workspace, productionId)}
  >
    {label}{!detail && disabledReason ? ` — ${disabledReason}` : ''}
  </button>
}
