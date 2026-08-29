import { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../../api/client'
import { inputClass } from './styles'
import type { SeriesProject, SeriesShot } from './types'

const SILENT_DURATIONS = [5, 10, 15] as const

function nextSilentDuration(value: number): number {
  return SILENT_DURATIONS.find(duration => duration >= value) ?? SILENT_DURATIONS.at(-1)!
}

export function SeriesShotDurationControl({
  workspace, series, shot, onChange,
}: {
  workspace: string
  series: SeriesProject
  shot: SeriesShot
  onChange: (shot: SeriesShot) => void
}) {
  const [calculating, setCalculating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const onChangeRef = useRef(onChange)
  const shotRef = useRef(shot)
  const hasDialogue = shot.dialogueBeats.some(beat => beat.text.trim())
  const signature = useMemo(() => JSON.stringify({
    dialogue: shot.dialogueBeats.map(beat => beat.text),
    language: series.spokenLanguage || series.language,
    model: series.provider?.videoModel || 'minimax_h3',
  }), [series.language, series.provider?.videoModel, series.spokenLanguage, shot.dialogueBeats])
  const lastCalculatedSignature = useRef(shot.dialogueDuration ? signature : '')

  useEffect(() => {
    onChangeRef.current = onChange
    shotRef.current = shot
  }, [onChange, shot])

  useEffect(() => {
    if (!hasDialogue) {
      lastCalculatedSignature.current = ''
      const currentShot = shotRef.current
      if (currentShot.dialogueDuration) {
        onChangeRef.current({
          ...currentShot,
          durationSeconds: nextSilentDuration(currentShot.durationSeconds),
          dialogueDuration: undefined,
        })
      }
      return
    }
    if (lastCalculatedSignature.current === signature) return
    const previousSignature = lastCalculatedSignature.current
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setCalculating(true)
      setError(null)
      void api.previewSeriesShotDuration(
        workspace, series.id, shotRef.current, controller.signal,
      ).then(planned => {
        if (controller.signal.aborted) return
        lastCalculatedSignature.current = signature
        onChangeRef.current(planned)
      }).catch(reason => {
        if (controller.signal.aborted) return
        lastCalculatedSignature.current = previousSignature
        setError((reason as Error).message)
      }).finally(() => {
        if (!controller.signal.aborted) setCalculating(false)
      })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      lastCalculatedSignature.current = previousSignature
      controller.abort()
    }
  }, [hasDialogue, series.id, signature, workspace])

  if (!hasDialogue) {
    return <label className="text-[10px] text-text-muted">
      Clip solicitado
      <select
        aria-label={`Clip solicitado para shot ${shot.order}`}
        className={`mt-1 ${inputClass}`}
        value={nextSilentDuration(shot.durationSeconds)}
        onChange={event => onChange({
          ...shot,
          durationSeconds: Number(event.target.value),
          dialogueDuration: undefined,
          referenceManifest: undefined,
        })}
      >
        {SILENT_DURATIONS.map(duration => <option key={duration} value={duration}>{duration} segundos</option>)}
      </select>
      <span className="mt-1 block text-[9px] text-text-muted">Sin diálogo: duración visual editable.</span>
    </label>
  }

  const contract = shot.dialogueDuration
  return <div className="rounded-lg border border-border bg-bg-secondary p-2 text-[10px]" aria-live="polite">
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      <span className="text-text-muted">Voz estimada: <strong className="text-text-primary">{contract ? `${contract.estimatedVoiceSeconds.toFixed(3)} s` : 'calculando…'}</strong></span>
      <span className="text-text-muted">Clip solicitado: <strong className="text-text-primary">{contract ? `${contract.requestedClipSeconds.toFixed(3)} s` : 'calculando…'}</strong></span>
      {contract && <span className="text-text-muted">{contract.syllableCount} sílabas · {contract.secondsPerSyllable.toFixed(2)} s/sílaba</span>}
    </div>
    {calculating && <p className="mt-1 text-violet-300">Recalculando al cambiar el diálogo…</p>}
    {contract?.minimumLimited && <p className="mt-1 text-text-muted">El mínimo nativo del modelo deja margen visual no hablado.</p>}
    {contract?.requiresSplit && <p className="mt-1 text-red-300">El diálogo supera el máximo de un clip; divídelo antes de renderizar.</p>}
    {error && <p className="mt-1 text-red-300">{error}</p>}
  </div>
}
