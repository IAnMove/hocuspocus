import type { TFunction } from 'i18next'
import { useUiTranslation } from '../../i18n'
import { contactMarks, joinExportReview, reviewVisible, type ExportReviewInput, type ReviewItem, type ReviewSeverity } from './exportReview.ts'

const GEOMETRY_KEYS = {
  below_floor: 'geometryBelowFloor',
  floating: 'geometryFloating',
  intersects: 'geometryIntersects',
  camera_inside: 'geometryCameraInside',
  out_of_frame: 'geometryOutOfFrame',
} as const

const QA_KEYS = {
  black: 'exportReviewQaBlack',
  frozen: 'exportReviewQaFrozen',
  clipping: 'exportReviewQaClipping',
  too_quiet: 'exportReviewQaTooQuiet',
  camera_jump: 'exportReviewQaCameraJump',
  duration_drift: 'exportReviewQaDurationDrift',
  fps_drift: 'exportReviewQaFpsDrift',
  silence: 'exportReviewQaSilence',
} as const

const SEVERITY_KEYS = {
  fail: 'exportReviewSeverityFail',
  watch: 'exportReviewSeverityWatch',
  ok: 'exportReviewSeverityOk',
} as const

function severityClass(severity: ReviewSeverity | 'ok'): string {
  if (severity === 'fail') return 'border-red-400/50'
  if (severity === 'watch') return 'border-amber-400/40'
  return 'border-border'
}

function reviewLabel(t: TFunction<'scene3dEditor'>, item: ReviewItem): string {
  if (item.source === 'geometry') {
    const key = GEOMETRY_KEYS[item.code as keyof typeof GEOMETRY_KEYS]
    if (key) return t(key, { slot: item.slot ?? '', start: item.time.toFixed(2), end: (item.end ?? item.time).toFixed(2) })
  }
  const key = QA_KEYS[item.code as keyof typeof QA_KEYS]
  if (key) return t(key, { time: item.time.toFixed(2) })
  return t('exportReviewQaUnknown', { code: item.code, time: item.time.toFixed(2) })
}

/** Receipt review. Warnings seek the playhead. Export stays available, including on fail. */
export function ExportReviewPanel({ review, duration, onSeek }: {
  review: ExportReviewInput | null
  duration: number
  onSeek: (seconds: number) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!reviewVisible(review)) return null
  const items = joinExportReview(review)
  const marks = contactMarks(duration, items)
  const unreliable = review?.qa?.verdict === 'unreliable'
  return <section data-testid="export-review" aria-label={t('exportReviewTitle')} className="space-y-2 rounded-lg border border-border p-2">
    <h3 className="text-xs font-semibold text-text-primary">{t('exportReviewTitle')}</h3>
    {unreliable && <p className="text-xs text-text-muted">{t('exportReviewUnreliable', { reason: review?.qa?.reason ?? '' })}</p>}
    {items.length === 0
      ? <p className="text-xs text-text-muted">{t('exportReviewClear')}</p>
      : <ul className="space-y-1">
        {items.map(item => <li key={item.id}>
          <button
            type="button"
            data-testid="export-review-warning"
            data-severity={item.severity}
            className={`block min-h-10 w-full rounded border px-2 text-left text-xs ${severityClass(item.severity)}`}
            onClick={() => onSeek(item.time)}
          >{reviewLabel(t, item)}</button>
        </li>)}
      </ul>}
    <div className="flex gap-1" role="group" aria-label={t('exportReviewSheet')}>
      {marks.map((mark, index) => <button
        key={`${index}:${mark.time}`}
        type="button"
        data-testid="export-review-mark"
        data-severity={mark.severity}
        aria-label={t('exportReviewMark', { time: mark.time.toFixed(2), severity: t(SEVERITY_KEYS[mark.severity]) })}
        className={`min-h-10 min-w-8 flex-1 rounded border text-[10px] ${severityClass(mark.severity)}`}
        onClick={() => onSeek(mark.time)}
      >{mark.time.toFixed(1)}</button>)}
    </div>
    <p className="text-xs text-text-muted">{t('exportReviewHint')}</p>
  </section>
}
