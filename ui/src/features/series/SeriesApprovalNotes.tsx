import { useCallback, useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { draftNote } from './reviewModel'
import { textareaClass } from './styles'
import { readApprovalNote, saveApprovalNote, writeApprovalNote } from './approvalNoteDraft'
import type { SeriesReviewReply, SeriesReviewStage, SeriesShotReview } from './types'

const DEBOUNCE_MS = 800

export type SaveNote = (note: { id?: string; text: string; stage: SeriesReviewStage }) => Promise<SeriesReviewReply | undefined>

/** The shot's notes: earlier ones listed, and one box for the user's note at this stage, saved as they type. */
export function SeriesApprovalNotes({ draftKey, shotId, entry, stage, onSave }: {
  draftKey: string; shotId: string; entry: SeriesShotReview; stage: SeriesReviewStage; onSave: SaveNote
}) {
  const { t } = useUiTranslation('seriesLab')
  const draft = draftNote(entry, stage)
  const [text, setText] = useState(() => readApprovalNote(draftKey)?.text ?? draft?.text ?? '')
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'failed' | 'pending'>(() => readApprovalNote(draftKey) ? 'pending' : 'idle')
  const [noteId, setNoteId] = useState(draft?.id)
  const idRef = useRef(draft?.id)
  const timer = useRef<number | undefined>(undefined)
  const flush = useCallback(async () => {
    window.clearTimeout(timer.current); timer.current = undefined
    if (!readApprovalNote(draftKey)) return
    setState('saving')
    try {
      idRef.current = await saveApprovalNote(draftKey, async note => {
        if (!note.text.trim() && !note.id) return undefined
        const reply = await onSave({ ...(note.id ? { id: note.id } : {}), text: note.text.trim() ? note.text : '', stage })
        return note.text.trim() ? reply?.noteIds?.[shotId] ?? note.id : undefined
      })
      setNoteId(idRef.current)
      setState(readApprovalNote(draftKey) ? 'pending' : 'saved')
    } catch { setState('failed') }
  }, [draftKey, onSave, shotId, stage])
  const flushRef = useRef(flush)
  useEffect(() => { flushRef.current = flush }, [flush])
  // A note typed just before the card goes away (a filter, another tab) is still saved.
  useEffect(() => () => { if (timer.current !== undefined) void flushRef.current() }, [])
  const change = (value: string) => {
    setText(value); writeApprovalNote(draftKey, value, readApprovalNote(draftKey)?.id ?? idRef.current); setState('pending')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void flushRef.current() }, DEBOUNCE_MS)
  }
  const earlier = entry.notes.filter(note => note.id !== noteId)
  return <div className="space-y-1.5">
    {earlier.length > 0 && <ul aria-label={t('approval.notes.earlier')} className="space-y-1">
      {earlier.map(note => <li key={note.id} className={`rounded-lg border px-2 py-1.5 text-[11px] ${note.by === 'agent' ? 'border-blue-500/30 bg-blue-500/5' : 'border-border bg-bg-tertiary'}`}>
        <span className="mr-1 text-[10px] text-text-muted">{t(`approval.notes.by.${note.by}`)} · {t(`approval.stage.${note.stage}`)} · {new Date(note.at).toLocaleString()}</span>
        <span className="whitespace-pre-wrap text-text-secondary">{note.text}</span>
      </li>)}
    </ul>}
    <label className="block text-[10px] font-semibold uppercase tracking-wide text-text-muted" htmlFor={`series-approval-note-${shotId}`}>
      {t('approval.notes.label', { stage: t(`approval.stage.${stage}`) })}
    </label>
    <textarea id={`series-approval-note-${shotId}`} className={`${textareaClass} min-h-16 text-sm sm:text-xs`} value={text} maxLength={2000}
      placeholder={t('approval.notes.placeholder')} onChange={event => change(event.target.value)} />
    <p role="status" className={`text-[10px] ${state === 'failed' ? 'text-red-300' : 'text-text-muted'}`}>{state === 'idle' ? '' : t(`approval.notes.${state}`)}</p>
    {(state === 'failed' || state === 'pending') && <button type="button" className="text-xs underline" onClick={() => void flush()}>{t('approval.notes.retry')}</button>}
  </div>
}
