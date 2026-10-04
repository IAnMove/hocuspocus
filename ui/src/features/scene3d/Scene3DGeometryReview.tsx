import { useState, type MutableRefObject } from 'react'
import { useUiTranslation } from '../../i18n'
import type { GeometryReport, GeometryWarning } from './geometryChecks.ts'
import { collectGeometry } from './geometryReview.ts'
import type { Scene3DStageHandle } from './Scene3DStage.tsx'
import type { Scene3DDocument } from './types.ts'

const CODE_KEY = {
  below_floor: 'geometryBelowFloor',
  floating: 'geometryFloating',
  intersects: 'geometryIntersects',
  camera_inside: 'geometryCameraInside',
  out_of_frame: 'geometryOutOfFrame',
} as const

/** Lists checkGeometry warnings for the open shot. Seeking jumps the playhead. Export stays available. */
export function Scene3DGeometryReview({ stageRef, document, seconds, disabled, onSeek }: {
  stageRef: MutableRefObject<Scene3DStageHandle | null>
  document: Scene3DDocument
  seconds: number
  disabled: boolean
  onSeek: (seconds: number) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [report, setReport] = useState<GeometryReport | 'unavailable' | null>(null)
  const review = () => {
    const stage = stageRef.current
    if (!stage?.geometrySample) {
      setReport('unavailable')
      return
    }
    try {
      setReport(collectGeometry((time, doc) => stage.geometrySample?.(time, doc), document) ?? 'unavailable')
    } finally {
      stage.paint(seconds, document)
    }
  }
  return <div className="space-y-2">
    <button type="button" className="min-h-10 rounded-lg border border-border px-3 text-xs" disabled={disabled} onClick={review}>
      {t('geometryReview')}
    </button>
    {report === 'unavailable' && <p className="text-xs text-text-muted">{t('geometryUnavailable')}</p>}
    {report && report !== 'unavailable' && report.warnings.length === 0 && <p className="text-xs text-text-muted">{t('geometryOk')}</p>}
    {report && report !== 'unavailable' && report.warnings.length > 0 && <GeometryList warnings={report.warnings} onSeek={onSeek} />}
  </div>
}

function GeometryList({ warnings, onSeek }: { warnings: readonly GeometryWarning[]; onSeek: (seconds: number) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  return <div className="space-y-1">
    {warnings.map(warning => <button
      key={`${warning.code}:${warning.slot}:${warning.start}`}
      type="button"
      className="block min-h-10 w-full rounded border border-amber-400/40 px-2 text-left text-xs"
      onClick={() => onSeek(warning.start)}
    >{t(CODE_KEY[warning.code], { slot: warning.slot, start: warning.start.toFixed(2), end: warning.end.toFixed(2) })}</button>)}
    <p className="text-xs text-text-muted">{t('geometryHint')}</p>
  </div>
}
