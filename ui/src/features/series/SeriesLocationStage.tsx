import { useEffect, useState } from 'react'
import { BASE } from '../../api/http'
import { checkSeriesLocationStage, setSeriesLocationStage, type SeriesStageCheckReply } from '../../api/series'
import { useUiTranslation } from '../../i18n'
import { seriesAssetUrl } from './referenceImages'
import { EYE_HIGH, EYE_LOW, eyeHeightM, fieldsFromStage, overlayLines, plateAsset, stageFromFields, type StageField, type StageFields } from './seriesStageModel'
import { useSeriesStore } from './store'
import { inputClass, primaryButton, secondaryButton } from './styles'
import type { SeriesLocation, SeriesProject } from './types'

const LINE_STYLE = { horizon: 'bg-fuchsia-500', base: 'bg-green-400', top: 'border-t-2 border-dashed border-green-400', floor: 'bg-orange-400' } as const
const FIELDS = [['horizon', 'stage.horizon'], ['baseY', 'stage.refBase'], ['heightPct', 'stage.refHeight'],
  ['heightM', 'stage.refMeters'], ['floorTop', 'stage.floorTop']] as const satisfies ReadonlyArray<readonly [StageField, string]>

/** Calibrate the location plate's perspective once (services/series_stage.py): horizon, one object of known height, optional far floor.
 * Wide and two-shots there then size each person by heightM and depth. The same routes as `series.location.stage.*` and the Wizard. */
export function SeriesLocationStage({ workspace, series, location }: { workspace: string; series: SeriesProject; location: SeriesLocation }) {
  const { t } = useUiTranslation('seriesLab')
  const reload = useSeriesStore(state => state.reload)
  const saved = location.layout2d?.stage
  const [fields, setFields] = useState<StageFields>(() => fieldsFromStage(saved))
  const [grid, setGrid] = useState<SeriesStageCheckReply | null>(null), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [note, setNote] = useState('')
  const savedKey = JSON.stringify(saved ?? null)
  useEffect(() => { setFields(fieldsFromStage(saved)) }, [savedKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const plate = plateAsset(series, location)
  const parsed = stageFromFields(fields)
  const issue = 'issue' in parsed ? parsed.issue : null
  const eye = 'stage' in parsed ? eyeHeightM(parsed.stage) : null
  const eyeOdd = eye !== null && (eye < EYE_LOW || eye > EYE_HIGH)
  const edit = (field: StageField, value: string) => { setFields(current => ({ ...current, [field]: value })); setNote('') }

  const run = async (action: () => Promise<void>) => {
    setError(''); setNote(''); setBusy(true)
    try { await action() } catch (cause) { setError(t('stage.failed', { error: (cause as Error).message })) } finally { setBusy(false) }
  }
  const look = () => run(async () => setGrid(await checkSeriesLocationStage(workspace, series.id, location.id, 'stage' in parsed ? parsed.stage : undefined)))
  const save = () => run(async () => {
    if (!('stage' in parsed)) return
    const reply = await setSeriesLocationStage(workspace, series.id, location.id, parsed.stage)
    setNote(t('stage.saved', { count: reply.affectedShots.length }))
    await reload()
  })
  const clear = () => run(async () => {
    await setSeriesLocationStage(workspace, series.id, location.id, null)
    setFields(fieldsFromStage(null)); setGrid(null); setNote(t('stage.cleared'))
    await reload()
  })
  const guess = grid?.suggestion.suggestion

  return <div className="space-y-2 rounded-lg border border-border p-2" data-testid={`series-location-stage-${location.id}`}>
    <p className="text-xs font-semibold">{t('stage.title')}</p>
    <p className="text-[10px] text-text-muted">{t(saved ? 'stage.active' : 'stage.hint')}</p>
    <p className="text-[10px] text-text-muted">{t('stage.depthHint')}</p>
    <div className="grid grid-cols-2 gap-2 md:grid-cols-5">{FIELDS.map(([field, label]) => <label key={field} className="text-[10px]">{t(label)}
      <input className={inputClass} type="number" step={0.01} value={fields[field]} aria-invalid={issue?.field === field}
        onChange={event => edit(field, event.target.value)} /></label>)}</div>
    {issue && <p role="alert" className="text-[10px] text-amber-300">{t(`stage.errors.${issue.key}`, { field: issue.field ? t(FIELDS.find(([name]) => name === issue.field)![1]) : '' })}</p>}
    {eye !== null && <p role={eyeOdd ? 'alert' : 'status'} data-testid="stage-eye" className={`text-[10px] ${eyeOdd ? 'text-amber-300' : 'text-text-muted'}`}>
      {t(eyeOdd ? 'stage.eyeOdd' : 'stage.eye', { height: eye })}</p>}
    {plate ? <div className="relative overflow-hidden rounded-lg border border-border" data-testid="stage-preview">
      <img className="block w-full" src={seriesAssetUrl(plate)} alt={t('stage.previewAlt')} loading="lazy" />
      {overlayLines(fields).map(line => <div key={line.id} data-testid={`stage-line-${line.id}`} style={{ top: `${line.percent}%` }}
        className={`pointer-events-none absolute inset-x-0 h-0.5 ${LINE_STYLE[line.id]}`} />)}
    </div> : <p className="text-[10px] text-text-muted">{t('stage.noPlate')}</p>}
    <div className="flex flex-wrap items-center gap-2">
      <button className={secondaryButton} disabled={busy || !plate} onClick={() => void look()}>{t('stage.look')}</button>
      <button className={primaryButton} disabled={busy || Boolean(issue)} onClick={() => void save()}>{t('stage.save')}</button>
      <button className={secondaryButton} disabled={busy || !saved} onClick={() => void clear()}>{t('stage.clear')}</button>
    </div>
    {grid && <div className="space-y-1">
      <img className="block w-full rounded-lg border border-border" src={`${BASE}${grid.grid.url}`} alt={t('stage.gridAlt')} data-testid="stage-grid" />
      {guess ? <div className="flex flex-wrap items-center gap-2 text-[10px]" data-testid="stage-guess">
        <span>{t('stage.guess', { horizon: guess.horizon, confidence: t(`stage.confidence.${guess.confidence}`) })}</span>
        <button className={secondaryButton} onClick={() => edit('horizon', String(guess.horizon))}>{t('stage.guessUse')}</button>
      </div> : <p className="text-[10px] text-text-muted">{t('stage.guessNone')}</p>}
      <p className="text-[10px] text-text-muted">{t('stage.guessNote')}</p>
    </div>}
    {note && <p role="status" className="text-[10px] text-emerald-200">{note}</p>}
    {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}
  </div>
}
