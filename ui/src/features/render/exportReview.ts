/** Joins receipt.qa and receipt.geometry into one review list. Nothing here blocks export. */

export type ReviewSeverity = 'fail' | 'watch'

export type QaWarning = {
  code?: string
  t?: number
  detail?: string
  slot?: string
}

export type GeometryWarningView = {
  code?: string
  severity?: string
  slot?: string
  other?: string
  start?: number
  end?: number
  detail?: string
}

export type QaReport = {
  verdict?: string
  warnings?: QaWarning[]
  reason?: string
}

export type GeometryReportView = {
  verdict?: string
  warnings?: GeometryWarningView[]
}

export type ExportReviewInput = {
  qa?: QaReport
  geometry?: GeometryReportView
}

export type ReviewItem = {
  id: string
  source: 'qa' | 'geometry'
  code: string
  severity: ReviewSeverity
  time: number
  end?: number
  slot?: string
  detail?: string
}

export type ContactMark = {
  time: number
  severity: ReviewSeverity | 'ok'
}

const QA_FAIL = new Set([
  'black', 'frozen', 'clipping', 'too_quiet', 'camera_jump', 'duration_drift', 'fps_drift',
])
const QA_ALLOW = new Set(['still', 'dark'])

function finite(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function qaItem(warning: QaWarning, index: number): ReviewItem | null {
  const code = text(warning.code) ?? 'unknown'
  if (QA_ALLOW.has(code)) return null
  const time = finite(warning.t, 0)
  const severity: ReviewSeverity = QA_FAIL.has(code) ? 'fail' : 'watch'
  return {
    id: `qa:${code}:${time}:${index}`,
    source: 'qa',
    code,
    severity,
    time,
    slot: text(warning.slot),
    detail: text(warning.detail),
  }
}

function geometryItem(warning: GeometryWarningView, index: number): ReviewItem {
  const code = text(warning.code) ?? 'unknown'
  const time = finite(warning.start, 0)
  const end = typeof warning.end === 'number' && Number.isFinite(warning.end) ? warning.end : undefined
  return {
    id: `geometry:${code}:${text(warning.slot) ?? ''}:${time}:${index}`,
    source: 'geometry',
    code,
    severity: warning.severity === 'fail' ? 'fail' : 'watch',
    time,
    end,
    slot: text(warning.slot),
    detail: text(warning.detail),
  }
}

function bySeverityThenTime(left: ReviewItem, right: ReviewItem): number {
  const rank = (severity: ReviewSeverity) => (severity === 'fail' ? 0 : 1)
  return rank(left.severity) - rank(right.severity) || left.time - right.time
}

export function reviewVisible(review: ExportReviewInput | null | undefined): boolean {
  return Boolean(review?.qa || review?.geometry)
}

export function joinExportReview(review: ExportReviewInput | null | undefined): ReviewItem[] {
  const qa = (review?.qa?.warnings ?? []).map(qaItem).filter((item): item is ReviewItem => item !== null)
  const geometry = (review?.geometry?.warnings ?? []).map(geometryItem)
  return [...qa, ...geometry].sort(bySeverityThenTime)
}

function covers(item: ReviewItem, time: number, window: number): boolean {
  if (item.source === 'geometry') {
    const end = item.end ?? item.time
    return time >= item.time && time <= end
  }
  return Math.abs(time - item.time) <= window
}

function worstAt(items: readonly ReviewItem[], time: number, window: number): ContactMark['severity'] {
  let severity: ContactMark['severity'] = 'ok'
  for (const item of items) {
    if (!covers(item, time, window)) continue
    if (item.severity === 'fail') return 'fail'
    severity = 'watch'
  }
  return severity
}

/** Eight times across the shot. Each cell takes the worst warning that covers it. */
export function contactMarks(duration: number, items: readonly ReviewItem[], count = 8): ContactMark[] {
  const span = duration > 0 && Number.isFinite(duration) ? duration : 0
  const total = Math.max(1, Math.min(24, Math.floor(count)))
  const window = Math.max(span / total, 0.05)
  return Array.from({ length: total }, (_, index) => {
    const time = total === 1 ? 0 : (span * index) / (total - 1)
    return { time, severity: worstAt(items, time, window) }
  })
}

export function reviewFromArtifact(saved: { qa?: QaReport; geometry?: GeometryReportView } | null | undefined): ExportReviewInput | null {
  if (!saved?.qa && !saved?.geometry) return null
  return { qa: saved.qa, geometry: saved.geometry }
}
