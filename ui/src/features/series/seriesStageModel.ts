import type { SeriesStage } from '../../api/series'
import type { SeriesAsset, SeriesLocation, SeriesProject } from './types'

/** What the stage form holds: text, so a half-typed number is not rewritten under the cursor. */
export type StageFields = { horizon: string; baseY: string; heightPct: string; heightM: string; floorTop: string }
export type StageField = keyof StageFields
export type StageIssue = { key: 'number' | 'belowHorizon' | 'floorTop'; field?: StageField }

/** The limits of services/series_stage.py `normalize_stage`; the server checks them again. */
const LIMITS: Record<Exclude<StageField, 'floorTop'>, [number, number]> = {
  horizon: [0, 0.95], baseY: [0.05, 1], heightPct: [0.01, 1.5], heightM: [0.05, 30],
}
const MIN_BELOW = 0.01
const text = (value: number) => String(Math.round(value * 10000) / 10000)

export function fieldsFromStage(stage?: SeriesStage | null): StageFields {
  return stage
    ? { horizon: text(stage.horizon), baseY: text(stage.ref.baseY), heightPct: text(stage.ref.heightPct), heightM: text(stage.ref.heightM),
        floorTop: stage.floorTop === undefined ? '' : text(stage.floorTop) }
    : { horizon: '', baseY: '', heightPct: '', heightM: '2', floorTop: '' }
}

const num = (value: string): number | null => (value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null)

/** The stage the fields spell out, or what is wrong with them (the same rules as the server). */
export function stageFromFields(fields: StageFields): { stage: SeriesStage } | { issue: StageIssue } {
  const values = {} as Record<Exclude<StageField, 'floorTop'>, number>
  for (const field of Object.keys(LIMITS) as Array<keyof typeof LIMITS>) {
    const value = num(fields[field])
    if (value === null || value < LIMITS[field][0] || value > LIMITS[field][1]) return { issue: { key: 'number', field } }
    values[field] = value
  }
  if (values.baseY - values.horizon < MIN_BELOW) return { issue: { key: 'belowHorizon', field: 'baseY' } }
  const stage: SeriesStage = { horizon: values.horizon, ref: { baseY: values.baseY, heightPct: values.heightPct, heightM: values.heightM } }
  if (fields.floorTop.trim() !== '') {
    const top = num(fields.floorTop)
    if (top === null || top < 0 || top > 1 || top - values.horizon < MIN_BELOW) return { issue: { key: 'floorTop', field: 'floorTop' } }
    stage.floorTop = top
  }
  return { stage }
}

export type StageLine = { id: 'horizon' | 'base' | 'top' | 'floor'; percent: number }

/** The lines to draw over the plate, as % of its height from the top: each one as soon as its own numbers are valid. */
export function overlayLines(fields: StageFields): StageLine[] {
  const [horizon, base, height, floor] = [num(fields.horizon), num(fields.baseY), num(fields.heightPct), num(fields.floorTop)]
  const lines: StageLine[] = []
  const percent = (fraction: number) => Math.round(fraction * 100000) / 1000
  if (horizon !== null) lines.push({ id: 'horizon', percent: percent(horizon) })
  if (base !== null) lines.push({ id: 'base', percent: percent(base) })
  if (base !== null && height !== null) lines.push({ id: 'top', percent: percent(base - height) })
  if (floor !== null) lines.push({ id: 'floor', percent: percent(floor) })
  return lines
}

/** The picture the stage is read from: the location's plate, background or first reference that is a still image. */
export function plateAsset(series: SeriesProject, location: SeriesLocation): SeriesAsset | null {
  const layout = location.layout2d ?? {}
  const ids = [layout.plateAssetId, layout.backgroundAssetId, ...location.referenceAssetIds].filter((id): id is string => Boolean(id))
  for (const id of ids) {
    const asset = series.assets?.[id]
    if (asset && ['image', 'location'].includes(asset.kind)) return asset
  }
  return null
}

/** The camera heights (metres) that need no remark: far from them the horizon or the reference was probably misread. */
export const EYE_LOW = 1.0
export const EYE_HIGH = 2.4

/** The camera height the stage implies: the metres between the reference's foot and the horizon (services/series_stage.py `eye_height_m`). */
export function eyeHeightM(stage: SeriesStage): number {
  return Math.round((stage.ref.baseY - stage.horizon) * stage.ref.heightM / stage.ref.heightPct * 100) / 100
}
