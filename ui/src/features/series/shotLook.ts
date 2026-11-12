import type { ParseKeys, TFunction } from 'i18next'
import { FINISH_PRESETS } from '../../lib/scene2d/finish'

/** The 2D camera moves of a Series shot (series_shot_plan.CAMERAS); `static` is no move. */
export const SERIES_CAMERAS = ['static', 'push', 'pull', 'pan-left', 'pan-right', 'drift'] as const
export type SeriesCamera = typeof SERIES_CAMERAS[number]

export const CAMERA_LABELS = {
  static: 'approval.cameras.static', push: 'approval.cameras.push', pull: 'approval.cameras.pull',
  'pan-left': 'approval.cameras.panLeft', 'pan-right': 'approval.cameras.panRight', drift: 'approval.cameras.drift',
} as const satisfies Record<SeriesCamera, ParseKeys<'seriesLab'>>

export const isSeriesCamera = (value: unknown): value is SeriesCamera => SERIES_CAMERAS.some(camera => camera === value)

/** A finish choice (series_finish.py): `paper` (the default), `none`, a Video 2D finish id, or an agent's own amounts. */
export type SeriesFinishChoice = string | {
  texture?: { kind: string; amount: number }
  grain?: { amount: number; size: number }
  vignette?: { amount: number; softness: number }
}

/** The select value of an agent's own amounts, which only an agent writes (series.update, series.shot.update). */
const CUSTOM = 'custom'

/** A stored choice as a select value: its id, `custom` for an agent's own amounts, '' when there is none. */
export function finishValue(choice: SeriesFinishChoice | undefined): string {
  if (choice === undefined || choice === null) return ''
  return typeof choice === 'string' ? choice : CUSTOM
}

/** Paper, none and every Video 2D finish (named in kineticText `finishes.<id>`); an agent's own amounts only while
 * they are the choice, so showing them never loses them. */
export function finishOptions(t: TFunction<'seriesLab'>, names: TFunction<'kineticText'>, current: string) {
  return [
    { value: 'paper', label: t('setup.finishPaper') },
    { value: 'none', label: t('setup.finishNone') },
    ...Object.keys(FINISH_PRESETS).map(id => ({ value: id, label: names(`finishes.${id}` as ParseKeys<'kineticText'>, { defaultValue: id }) })),
    ...(current === CUSTOM ? [{ value: CUSTOM, label: t('setup.finishCustom') }] : []),
  ]
}

/** The choice a select value stores; undefined for the agent's own amounts, which stay as they are. */
export function finishChoice(value: string): string | undefined {
  return value === CUSTOM ? undefined : value
}
