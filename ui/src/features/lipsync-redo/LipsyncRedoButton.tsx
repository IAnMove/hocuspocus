import { controlReason } from '../../i18n/controlLabel'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import {
  confirmLipsyncDownload, runLipsyncRedo, type LipsyncEngine, type LipsyncRedoInput,
} from './request'

function wizardLine(key: string, options?: Record<string, unknown>): string {
  const translate = i18n.t as (key: string, options?: Record<string, unknown>) => string
  return String(translate(`wizard:${key}`, options))
}

type Pending = { model: string, bytes: number }

/** One control on a finished take. The original stays; the server appends the new take. */
export function LipsyncRedoButton({ workspace, target, namespace, labelKey, engineKey }: {
  workspace: string
  target: Omit<LipsyncRedoInput, 'workspace' | 'engine'>
  namespace: 'productionShots' | 'seriesLab'
  labelKey: string
  engineKey: string
}) {
  const { t } = useTranslation(namespace)
  const label = (key: string) => String((t as (key: string) => string)(key))
  const [engine, setEngine] = useState<LipsyncEngine>('infinitetalk')
  const [note, setNote] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)

  async function redo() {
    setBusy(true)
    try {
      const next = await runLipsyncRedo({ ...target, workspace, engine }, wizardLine)
      setNote(next.note)
      setPending(next.pending)
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error))
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  async function download() {
    if (!pending) return
    setBusy(true)
    try {
      await confirmLipsyncDownload(pending.model)
      setNote(wizardLine('replies.lipsDownloadStarted', { model: pending.model, bytes: pending.bytes }))
      setPending(null)
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return <span className="flex flex-wrap items-center gap-1">
    <select data-action="lipsync-engine" aria-label={label(engineKey)} value={engine} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')}
      onChange={() => setEngine('infinitetalk')}>
      <option value="infinitetalk">infinitetalk</option>
    </select>
    <button type="button" data-action="lipsync-redo" data-lipsync-source={target.source} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => { void redo() }}>{label(labelKey)}</button>
    {pending ? <button type="button" data-action="lipsync-download" disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => { void download() }}>{wizardLine('replies.lipsDownload')}</button> : null}
    {note ? <span role="status">{note}</span> : null}
  </span>
}
